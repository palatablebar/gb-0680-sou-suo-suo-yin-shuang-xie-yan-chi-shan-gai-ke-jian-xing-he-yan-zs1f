import hashlib,json
from app.config import RULE_VERSION
from app.errors import DomainError
from app.values import number
POLICY="takedown_first_then_arrival"
DEFAULT_QUOTA=100
TAKEDOWN_STATES={"DELETE_NOT_CONFIRMED","ORPHAN_INDEX"}
LATE_STATES={"STALE_INDEX","OP_MISMATCH"}
UPDATE_STATES={"MISSING_INDEX","CONTENT_MISMATCH"}
def quota_from(params):
    value=number((params or {}).get("release_quota",str(DEFAULT_QUOTA)))
    if value<0 or value!=value.to_integral_value(): raise DomainError("BAD_QUOTA","放行额度需为非负整数")
    return int(value)
def classify(row):
    "放行动作以版本裁决后的最终状态为准：索引超前绝不按删除一刀切，转人工核对。"
    state=row.get("visibility_state")
    if state=="INDEX_AHEAD": return "hold","INDEX_AHEAD"
    if state in TAKEDOWN_STATES: return "takedown",None
    if state in LATE_STATES: return ("takedown",None) if row.get("source_op")=="delete" else ("update",None)
    if state in UPDATE_STATES: return "update",None
    return "hold","NEEDS_REVIEW"
def build(rows,params=None):
    "形成本次放行的唯一积压队列范围。返回(放行单, 对齐表)。放行单为纯内容寻址，不含时间戳，重跑同一积压得到同一release_id。"
    quota=quota_from(params)
    backlog=[(index,row) for index,row in enumerate(rows) if row.get("visibility_state")!="CONSISTENT"]
    arrival=sorted(backlog,key=lambda item:(str(item[1].get("source_at") or ""),str(item[1].get("doc_id") or "")))
    entries=[];alignment={}
    for position,(index,row) in enumerate(arrival,1):
        action,hold=classify(row)
        entry={"doc_id":row.get("doc_id"),"position":position,"rank":None,"action":action,"selected":False,"skip_reason":hold,"visibility_state":row.get("visibility_state"),"source_at":row.get("source_at")}
        entries.append(entry);alignment[index]=entry
    releasable=[e for e in entries if e["action"]=="takedown"]+[e for e in entries if e["action"]=="update"]
    selected=releasable[:quota];skipped=releasable[quota:]
    for rank,entry in enumerate(selected,1): entry["rank"]=rank;entry["selected"]=True
    for entry in skipped: entry["skip_reason"]="QUOTA_EXCEEDED"
    holds=[e for e in entries if e["action"]=="hold"]
    ordered=selected+skipped+holds
    canonical=json.dumps({"rule_version":RULE_VERSION,"policy":{"order":POLICY,"quota":quota},"entries":[[e["doc_id"],e["position"],e["rank"],e["action"],e["selected"],e["skip_reason"]] for e in ordered]},sort_keys=True,ensure_ascii=False)
    manifest={"release_id":hashlib.sha256(canonical.encode()).hexdigest()[:20],"policy":{"order":POLICY,"quota":quota},"rule_version":RULE_VERSION,"backlog":len(entries),"selected":len(selected),"skipped":len(skipped)+len(holds),"range":{"from_rank":1,"to_rank":len(selected)} if selected else None,"entries":ordered}
    return manifest,alignment
