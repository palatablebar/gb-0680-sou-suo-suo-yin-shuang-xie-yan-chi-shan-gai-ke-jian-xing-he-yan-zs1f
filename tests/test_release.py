import csv,io
import pytest
from app.pipeline import calculate,execute,load_sample
from app import store
from app.release import build
from app.modules.m5_latency.rules import evaluate as gate
from app.modules.m6_parity.rules import evaluate as reconcile
from app.modules.m7_backfills.rules import evaluate as archive
from app.errors import DomainError
@pytest.fixture
def backlog(): return load_sample("backlog.csv")
@pytest.fixture
def quota_run(backlog): return calculate(backlog,{"release_quota":"2"})
def vis(doc,state,source_op="upsert",source_at="2026-11-16T10:00:00Z",visible=None):
    return {"doc_id":doc,"visibility_state":state,"source_op":source_op,"index_op":"upsert","source_version":"2","index_version":"1","source_at":source_at,"visible_at":visible,"op":source_op,"_sources":[1]}
def test_takedown_outranks_earlier_update():
    "TRAP-27 纯到达序会让先到的更新占满额度，撤下被挤到队尾；放行单撤下类优先"
    rows=[vis("U1","STALE_INDEX","upsert","2026-11-16T10:00:00Z"),vis("D1","STALE_INDEX","delete","2026-11-16T10:09:00Z")]
    manifest,_=build(rows,{"release_quota":"1"})
    assert manifest["entries"][0]["doc_id"]=="D1" and manifest["entries"][0]["selected"] is True
    assert manifest["entries"][1]["doc_id"]=="U1" and manifest["entries"][1]["skip_reason"]=="QUOTA_EXCEEDED"
def test_release_range_is_unique_prefix(quota_run):
    rel=quota_run["stages"][4]["release"]
    ranks=[e["rank"] for e in rel["entries"] if e["selected"]]
    assert ranks==list(range(1,len(ranks)+1))==list(range(1,rel["range"]["to_rank"]+1))
    assert rel["selected"]+rel["skipped"]==rel["backlog"]
    assert sorted(e["position"] for e in rel["entries"])==list(range(1,rel["backlog"]+1))
def test_release_id_deterministic():
    "TRAP-29 放行单内容寻址，不含时间戳，同一积压同一参数得到同一放行单"
    rows=[vis("U1","MISSING_INDEX"),vis("D1","DELETE_NOT_CONFIRMED","delete")]
    a,_=build(rows,{"release_quota":"1"});b,_=build(rows,{"release_quota":"1"});c,_=build(rows,{"release_quota":"2"})
    assert a["release_id"]==b["release_id"] and a["release_id"]!=c["release_id"]
def test_index_ahead_held_not_consuming_quota():
    "TRAP-30 索引已有更新写入时按删除一刀切会误删正常更新，转人工且不占额度"
    rows=[vis("A1","INDEX_AHEAD","delete"),vis("U1","MISSING_INDEX")]
    manifest,_=build(rows,{"release_quota":"1"})
    hold=[e for e in manifest["entries"] if e["doc_id"]=="A1"][0]
    picked=[e for e in manifest["entries"] if e["doc_id"]=="U1"][0]
    assert hold["selected"] is False and hold["skip_reason"]=="INDEX_AHEAD" and hold["rank"] is None
    assert picked["selected"] is True
def test_gate_marks_skipped_not_synced():
    rows=[vis("U1","MISSING_INDEX"),vis("D1","DELETE_NOT_CONFIRMED","delete")]
    out=gate(rows,{"parameters":{"release_quota":"1"}})
    skipped=[r for r in out["rows"] if r["release_selected"] is False]
    assert skipped and all(r["gate"]=="未入选" and r["reported"]=="0" for r in skipped)
def test_consistent_rows_stay_outside_manifest():
    out=gate([vis("C1","CONSISTENT",visible="2026-11-16T10:00:30Z")],{"parameters":{}})
    assert out["rows"][0]["gate"]=="通过" and out["rows"][0]["release_position"] is None
    assert out["release"]["backlog"]==0
def test_reconcile_rejects_impersonation():
    "TRAP-28 未入选文档不得记为已同步，对账硬拦截"
    release={"release_id":"r1","backlog":1,"selected":0,"skipped":1,"entries":[{"doc_id":"d1","position":1,"rank":None,"action":"update","selected":False,"skip_reason":"QUOTA_EXCEEDED"}]}
    rows=[{"doc_id":"d1","release_selected":False,"release_position":1,"reported":"1","expected":"1","_sources":[3]}]
    with pytest.raises(DomainError) as e: reconcile(rows,{"quarantine":[],"release":release})
    assert e.value.code=="RELEASE_IMPERSONATION"
def test_reconcile_release_balance(quota_run):
    m=quota_run["stages"][5]["metrics"]
    assert m["release_balanced"] is True and m["released"]+m["skipped"]==m["backlog"]
def test_archive_seal_covers_release(quota_run):
    rel=quota_run["stages"][4]["release"];m=quota_run["stages"][6]["metrics"]
    assert m["release_id"]==rel["release_id"] and m["ready"] is True
def test_archive_blocks_unbalanced_release():
    context={"parity":{"metrics":{"balanced":True,"release_balanced":False}},"release":{"release_id":"r1","backlog":1,"selected":1,"skipped":0,"entries":[]}}
    with pytest.raises(DomainError) as e: archive([],context)
    assert e.value.code=="UNBALANCED"
def test_rerun_same_backlog_no_new_records(backlog):
    a=execute(backlog,{"release_quota":"2"});b=execute(backlog,{"release_quota":"2"})
    assert a["run_id"]==b["run_id"] and len(store.history())==1
    assert a["stages"][4]["release"]["release_id"]==b["stages"][4]["release"]["release_id"]
def test_position_and_reason_queryable(client,backlog):
    p=client.post("/api/runs",json={"sample":"backlog.csv","parameters":{"release_quota":"2"}}).get_json()
    detail=client.get("/api/runs/"+p["run_id"]).get_json()
    entries=detail["stages"][4]["release"]["entries"]
    skipped=[e for e in entries if not e["selected"]]
    assert skipped and all(e["position"] and e["skip_reason"] for e in skipped)
def test_page_and_export_share_release(client,backlog):
    p=client.post("/api/runs",json={"sample":"backlog.csv","parameters":{"release_quota":"2"}}).get_json()
    rel=p["stages"][4]["release"]["release_id"]
    assert rel in client.get("/latency").data.decode()
    rows=list(csv.reader(io.StringIO(client.get("/api/runs/"+p["run_id"]+"/archive").data.decode("utf-8-sig"))))
    assert rows[0][4]=="release_id"
    assert any(r[4]==rel and r[7] for r in rows[1:])
def test_bad_quota_rejected():
    for bad in ("-1","1.5"):
        with pytest.raises(DomainError) as e: gate([vis("U1","MISSING_INDEX")],{"parameters":{"release_quota":bad}})
        assert e.value.code=="BAD_QUOTA"
