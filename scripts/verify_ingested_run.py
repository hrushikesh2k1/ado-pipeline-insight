from __future__ import annotations
import os,sys
from datetime import datetime,timezone
from pathlib import Path
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT)); load_dotenv(ROOT/".env")
from core.ado_client import AzureDevOpsClient
from core.db import AlertRepository

def dt(v):
    if v is None:return None
    if isinstance(v,datetime):return v
    return datetime.fromisoformat(str(v).replace("Z","+00:00"))
def time_ok(a,b,tol=1.0):
    a,b=dt(a),dt(b)
    if a is None or b is None:return a is None and b is None
    if a.tzinfo is None:a=a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:b=b.replace(tzinfo=timezone.utc)
    return abs((a-b).total_seconds())<=tol
def num_ok(a,b,tol=.25):
    if a is None or b is None:return a is None and b is None
    return abs(float(a)-float(b))<=tol
def sql_rows(repo,run_id):
    with repo._connect() as c:
        cur=c.cursor(); out={}
        for level,table in [("stage","pipeline_stages"),("job","pipeline_jobs"),("task","pipeline_tasks")]:
            cur.execute("SELECT record_id,stage_name,job_name,task_name,start_time,finish_time,duration_seconds,result,retry_count,is_degraded,data_quality FROM dbo."+table+" WHERE run_id=?",run_id)
            cols=[x[0] for x in cur.description]; out[level]=[dict(zip(cols,r)) for r in cur.fetchall()]
        cur.execute("SELECT run_id,pipeline_id,start_time,finish_time,result,is_degraded,data_quality FROM dbo.pipeline_runs WHERE run_id=?",run_id)
        cols=[x[0] for x in cur.description]; r=cur.fetchone(); out["run"]=dict(zip(cols,r)) if r else None
        return out
def byid(rows):return {str(r["record_id"]):r for r in rows if r.get("record_id") is not None}
def verify(client,repo,run_id):
    project=os.environ["ADO_PROJECT"]; build=client.get_build(project,run_id); timeline=client.get_timeline(project,run_id); exp=client.flatten_timeline(build,timeline); got=sql_rows(repo,run_id); failures=[]
    print("\n"+"="*72); print("VERIFY ADO RUN #"+str(run_id)); print("="*72)
    print("Pipeline: "+str(build.get("definition",{}).get("name"))+" (id="+str(build.get("definition",{}).get("id"))+")")
    print("ADO timeline records: "+str(len(timeline.get("records",[])))+" | normalized: "+str(len(exp)))
    r=got["run"]
    if not r: failures.append("pipeline_runs row missing")
    else:
        checks=[("pipeline_id",int(build["definition"]["id"]),int(r["pipeline_id"])),("result",build.get("result"),r.get("result")),("start_time",build.get("startTime"),r.get("start_time")),("finish_time",build.get("finishTime"),r.get("finish_time"))]
        for n,e,a in checks:
            ok=(e==a) if n in ("pipeline_id","result") else time_ok(e,a)
            print(f"{n:12} {'PASS' if ok else 'FAIL'} | ADO={e} | SQL={a}")
            if not ok:failures.append(f"run {n} mismatch")
        if r.get("is_degraded") or r.get("data_quality")!="complete":failures.append("SQL run is degraded")
    for level in ("stage","job","task"):
        ee=byid([m.__dict__ for m in exp if m.level==level]); aa=byid(got[level]); print(f"\n{level.upper()}: expected={len(ee)} SQL={len(aa)}")
        for k in sorted(set(ee)|set(aa)):
            e,a=ee.get(k),aa.get(k)
            if e is None:failures.append(f"{level} {k} unexpected"); print("  FAIL unexpected "+k); continue
            if a is None:failures.append(f"{level} {k} missing"); print("  FAIL missing "+k); continue
            ok=num_ok(e.get("duration_seconds"),a.get("duration_seconds")) and e.get("result")==a.get("result") and time_ok(e.get("start_time"),a.get("start_time")) and time_ok(e.get("finish_time"),a.get("finish_time")) and not a.get("is_degraded") and a.get("data_quality")=="complete"
            label=" / ".join(str(x) for x in (e.get("stage_name"),e.get("job_name"),e.get("task_name")) if x)
            print(f"  {'PASS' if ok else 'FAIL'} {label} | duration ADO={e.get('duration_seconds')} SQL={a.get('duration_seconds')}")
            if not ok:failures.append(f"{level} {k} telemetry mismatch")
    print("\n"+"-"*72)
    if failures:
        print("RESULT: FAILED ("+str(len(failures))+" issue(s))"); [print("  - "+x) for x in failures[:20]]; return False
    print("RESULT: VERIFIED - SQL matches the Azure DevOps timeline"); return True
def latest(repo,n):
    with repo._connect() as c:
        cur=c.cursor(); cur.execute("SELECT TOP (?) run_id FROM dbo.pipeline_runs ORDER BY start_time DESC,run_id DESC",n); return [int(x[0]) for x in cur.fetchall()]
def main():
    args=sys.argv[1:]
    if not args or (args[0]=="--latest" and len(args)!=2):raise SystemExit("Usage: python scripts/verify_ingested_run.py <run_id> [run_id ...] | --latest <count>")
    for n in ("SQL_CONNECTION_STRING","ADO_ORGANIZATION","ADO_PROJECT","ADO_PAT"):
        if not os.environ.get(n):raise SystemExit("Missing required environment variable: "+n)
    repo=AlertRepository(os.environ["SQL_CONNECTION_STRING"]); ids=latest(repo,int(args[1])) if args[0]=="--latest" else [int(x) for x in args]; client=AzureDevOpsClient(os.environ["ADO_ORGANIZATION"],os.environ["ADO_PAT"]); results=[verify(client,repo,i) for i in ids]
    print("\n"+"="*72); print(f"OVERALL: {'VERIFIED' if all(results) else 'FAILED'} | runs checked={len(results)}"); print("="*72); raise SystemExit(0 if all(results) else 2)
if __name__=="__main__":main()
