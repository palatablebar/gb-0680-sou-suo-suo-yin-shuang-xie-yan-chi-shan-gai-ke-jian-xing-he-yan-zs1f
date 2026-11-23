import hashlib,json
from decimal import Decimal
from app.errors import DomainError
from app.reasons import sources
def evaluate(rows,context):
    stages=[v for v in context.values() if isinstance(v,dict) and "metrics" in v]
    balances=[s["metrics"][key] for s in stages for key in ("balanced","release_balanced") if key in s["metrics"]]
    if balances and not all(balances): raise DomainError("UNBALANCED","来源行或放行单未对平，不能归档")
    ids=[str(r.get("doc_id",r.get("_line",""))) for r in rows]
    if len(ids)!=len(set(ids)): raise DomainError("ARCHIVE_DUPLICATE","归档业务键重复")
    release=context.get("release")
    sealed={"rows":rows,"release_id":release["release_id"]} if release else rows
    encoded=json.dumps(sealed,ensure_ascii=False,sort_keys=True,default=str).encode()
    metrics={"records":len(rows),"source_lines":len(set(x for row in rows for x in sources(row))),"sha256":hashlib.sha256(encoded).hexdigest(),"ready":True,"differences":sum(r.get("status")=="差异" for r in rows)}
    if release: metrics.update(release_id=release["release_id"],backlog=release["backlog"],released=release["selected"],skipped=release["skipped"])
    return {"rows":rows,"quarantine":[],"metrics":metrics}
