from decimal import Decimal
from app.reasons import sources
from app.errors import DomainError
def evaluate(rows,context):
    intake=context.get("intake")
    bad=context.get("quarantine",[])
    accepted=set(x for row in rows for x in sources(row))
    rejected=set(x for row in bad for x in sources(row))
    if accepted & rejected: raise DomainError("LINEAGE_OVERLAP","同一来源行被重复裁决")
    m={"accepted_inputs":len(accepted),"quarantine_inputs":len(rejected),"output_records":len(rows)}
    if intake:
        excluded=intake["duplicate"]+intake["blank"]+intake["repeated_headers"]
        m.update(input=intake["input"],excluded=excluded,balanced=intake["input"]==len(accepted)+len(rejected)+excluded)
    else:m.update(input=len(accepted)+len(rejected),excluded=0,balanced=True)
    release=context.get("release")
    if release:
        for row in rows:
            if row.get("release_selected") is False and Decimal(str(row.get("reported","0")))!=0: raise DomainError("RELEASE_IMPERSONATION","未入选文档不能记为已同步")
        positions=[e["position"] for e in release["entries"]]
        row_positions={r.get("release_position") for r in rows if r.get("release_position") is not None}
        m.update(release_id=release["release_id"],backlog=release["backlog"],released=release["selected"],skipped=release["skipped"],release_balanced=len(positions)==len(set(positions)) and release["selected"]+release["skipped"]==release["backlog"] and row_positions==set(positions))
    output=[]
    for row in rows:
        expected=Decimal(str(row.get("expected","0")));reported=Decimal(str(row.get("reported","0")))
        output.append({**row,"difference":str(expected-reported),"status":"通过" if expected==reported else "差异"})
    m.update(expected_total=str(sum((Decimal(str(r.get("expected","0"))) for r in rows),Decimal(0))),reported_total=str(sum((Decimal(str(r.get("reported","0"))) for r in rows),Decimal(0))),differences=sum(r["status"]=="差异" for r in output))
    return {"rows":output,"quarantine":[],"metrics":m}
