from datetime import datetime, timedelta, timezone
from typing import Any
from backend.app.core.db import fetch_all, fetch_one

class PipelineRepository:
    def list_options(self) -> dict[str, Any]:
        rows = fetch_all("""
            SELECT pipeline_id, pipeline_name, organization_name, project_name
            FROM dbo.pipelines ORDER BY organization_name, project_name, pipeline_name
        """)
        return {"organizations": sorted({r["organization_name"] for r in rows if r.get("organization_name")}), "projects": sorted({r["project_name"] for r in rows if r.get("project_name")}), "pipelines": rows}

    def summary(self, pipeline_id: int | None, days: int) -> dict[str, Any]:
        start = datetime.now(timezone.utc) - timedelta(days=days)
        where = "r.start_time >= ? AND r.finish_time IS NOT NULL"; params: list[Any] = [start]
        if pipeline_id is not None: where += " AND r.pipeline_id = ?"; params.append(pipeline_id)
        run_rows = fetch_all(f"""SELECT r.run_id,r.pipeline_id,r.queue_time,r.start_time,r.finish_time,r.result,r.is_degraded,r.data_quality,DATEDIFF(second,r.start_time,r.finish_time) duration_seconds FROM dbo.pipeline_runs r WHERE {where} AND r.start_time IS NOT NULL""", tuple(params))
        durations=[float(r["duration_seconds"]) for r in run_rows if r.get("duration_seconds") is not None]
        queues=[float((r["start_time"]-r["queue_time"]).total_seconds()) for r in run_rows if r.get("start_time") and r.get("queue_time")]
        successful=sum(1 for r in run_rows if r.get("result") in {"succeeded","partiallySucceeded"}); failed=sum(1 for r in run_rows if r.get("result")=="failed")
        stages=fetch_all(f"""SELECT s.stage_name,AVG(s.duration_seconds) avg_duration_seconds,COUNT(*) samples,SUM(CASE WHEN s.result='failed' THEN 1 ELSE 0 END) failed_count FROM dbo.pipeline_stages s JOIN dbo.pipeline_runs r ON r.run_id=s.run_id WHERE {where} AND r.is_degraded=0 AND s.duration_seconds IS NOT NULL GROUP BY s.stage_name ORDER BY avg_duration_seconds DESC""", tuple(params))
        return {"pipeline_id":pipeline_id,"window_days":days,"total_runs":len(run_rows),"successful_runs":successful,"failed_runs":failed,"success_rate_pct":round(successful*100/len(run_rows),2) if run_rows else 0,"failure_rate_pct":round(failed*100/len(run_rows),2) if run_rows else 0,"degraded_runs":sum(1 for r in run_rows if r.get("is_degraded")) ,"average_duration_seconds":round(sum(durations)/len(durations),2) if durations else None,"p90_duration_seconds":percentile(durations,.9),"average_queue_seconds":round(sum(queues)/len(queues),2) if queues else None,"stages":stages}

    def runs(self, pipeline_id: int | None, page: int, page_size: int, status: str | None) -> dict[str, Any]:
        page=max(1,page); page_size=max(1,min(100,page_size)); clauses=["1=1"]; params: list[Any]=[]
        if pipeline_id is not None: clauses.append("r.pipeline_id=?"); params.append(pipeline_id)
        if status: clauses.append("r.result=?"); params.append(status)
        where=" AND ".join(clauses); count=fetch_one(f"SELECT COUNT(*) total FROM dbo.pipeline_runs r WHERE {where}",tuple(params))["total"]
        params.extend([(page-1)*page_size,page_size])
        items=fetch_all(f"""SELECT r.run_id,r.pipeline_id,p.pipeline_name,p.organization_name,p.project_name,r.source_branch,r.queue_time,r.start_time,r.finish_time,r.result,r.is_degraded,r.data_quality,r.build_number,DATEDIFF(second,r.start_time,r.finish_time) duration_seconds FROM dbo.pipeline_runs r JOIN dbo.pipelines p ON p.pipeline_id=r.pipeline_id WHERE {where} ORDER BY r.start_time DESC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY""",tuple(params))
        return {"page":page,"page_size":page_size,"total_count":int(count),"total_pages":max(1,(int(count)+page_size-1)//page_size),"items":items}

    def trends(self, pipeline_id: int | None, days: int) -> dict[str, Any]:
        start=datetime.now(timezone.utc)-timedelta(days=days); clauses=["r.start_time>=?"]; params:[Any]=[start]
        if pipeline_id is not None: clauses.append("r.pipeline_id=?"); params.append(pipeline_id)
        where=" AND ".join(clauses)
        build=fetch_all(f"""SELECT r.run_id,r.start_time run_date,r.pipeline_id,p.pipeline_name,DATEDIFF(second,r.start_time,r.finish_time) duration_seconds,r.result FROM dbo.pipeline_runs r JOIN dbo.pipelines p ON p.pipeline_id=r.pipeline_id WHERE {where} ORDER BY r.start_time""",tuple(params))
        daily=fetch_all(f"""SELECT run_date,pipeline_id,pipeline_name,AVG(avg_duration_seconds) avg_duration_seconds,MAX(p90_duration_seconds) p90_duration_seconds FROM dbo.vw_pipeline_duration_trend WHERE run_date>=CAST(? AS date) {(' AND pipeline_id=?' if pipeline_id is not None else '')} GROUP BY run_date,pipeline_id,pipeline_name ORDER BY run_date""",tuple([start.date(), *([pipeline_id] if pipeline_id is not None else [])]))
        stage=fetch_all(f"""SELECT CAST(r.start_time AS date) run_date,s.stage_name,AVG(s.duration_seconds) avg_duration_seconds FROM dbo.pipeline_runs r JOIN dbo.pipeline_stages s ON s.run_id=r.run_id WHERE {where} AND s.duration_seconds IS NOT NULL GROUP BY CAST(r.start_time AS date),s.stage_name ORDER BY run_date""",tuple(params))
        return {"build_trend":build,"daily_trend":daily,"stage_trend":stage}

    def recommendations(self,pipeline_id:int,limit:int=50)->list[dict[str,Any]]:
        return fetch_all("SELECT TOP (?) id,pipeline_id,category,severity,stage_name,task_name,recommendation,evidence,generated_at FROM dbo.ai_recommendations WHERE pipeline_id=? ORDER BY generated_at DESC,id DESC",(limit,pipeline_id))

    def timeline(self,run_id:int)->dict[str,Any]:
        stages=fetch_all("SELECT id,record_id,stage_name,agent_name,start_time,finish_time,duration_seconds,result,retry_count,failure_log_excerpt FROM dbo.pipeline_stages WHERE run_id=? ORDER BY start_time",(run_id,))
        jobs=fetch_all("SELECT id,record_id,stage_name,job_name,pool_name,agent_name,start_time,finish_time,duration_seconds,result,retry_count,failure_log_excerpt FROM dbo.pipeline_jobs WHERE run_id=? ORDER BY start_time",(run_id,))
        tasks=fetch_all("SELECT id,record_id,stage_name,job_name,task_name,agent_name,start_time,finish_time,duration_seconds,result,retry_count,failure_log_excerpt FROM dbo.pipeline_tasks WHERE run_id=? ORDER BY start_time",(run_id,))
        return {"run_id":run_id,"stages":stages,"jobs":jobs,"tasks":tasks}

    def run_analysis(self,run_id:int)->dict[str,Any]:
        run=fetch_one("""SELECT r.run_id,r.pipeline_id,p.pipeline_name,p.organization_name,p.project_name,r.source_branch,r.source_version,r.requested_by,r.queue_time,r.start_time,r.finish_time,r.result,r.data_quality,r.build_number,DATEDIFF(second,r.start_time,r.finish_time) duration_seconds FROM dbo.pipeline_runs r JOIN dbo.pipelines p ON p.pipeline_id=r.pipeline_id WHERE r.run_id=?""",(run_id,))
        if not run: raise ValueError(f"Run {run_id} was not found")
        hierarchy=self.timeline(run_id)
        stage_durations=[float(x["duration_seconds"]) for x in hierarchy["stages"] if x.get("duration_seconds") is not None]
        job_durations=[float(x["duration_seconds"]) for x in hierarchy["jobs"] if x.get("duration_seconds") is not None]
        task_durations=[float(x["duration_seconds"]) for x in hierarchy["tasks"] if x.get("duration_seconds") is not None]
        longest_stage=max(hierarchy["stages"],key=lambda x:x.get("duration_seconds") or 0,default=None)
        longest_job=max(hierarchy["jobs"],key=lambda x:x.get("duration_seconds") or 0,default=None)
        longest_task=max(hierarchy["tasks"],key=lambda x:x.get("duration_seconds") or 0,default=None)
        failed=[x for level in ("stages","jobs","tasks") for x in hierarchy[level] if str(x.get("result") or "").lower()=="failed"]
        run_seconds=float(run["duration_seconds"] or 0)
        return {"run":run,"stages":hierarchy["stages"],"jobs":hierarchy["jobs"],"tasks":hierarchy["tasks"],"metrics":{"run_duration_seconds":run_seconds,"stage_count":len(hierarchy["stages"]),"job_count":len(hierarchy["jobs"]),"task_count":len(hierarchy["tasks"]),"failed_records":len(failed),"stage_duration_total_seconds":round(sum(stage_durations),2),"job_duration_total_seconds":round(sum(job_durations),2),"task_duration_total_seconds":round(sum(task_durations),2),"longest_stage":longest_stage,"longest_job":longest_job,"longest_task":longest_task,"queue_seconds":round((run["start_time"]-run["queue_time"]).total_seconds(),2) if run.get("start_time") and run.get("queue_time") else None}}

    def logs(self,run_id:int)->dict[str,Any]:
        rows=fetch_all("SELECT task_name,failure_log_excerpt,result FROM dbo.pipeline_tasks WHERE run_id=? AND (failure_log_excerpt IS NOT NULL OR result='failed')",(run_id,)); excerpts=[r["failure_log_excerpt"] for r in rows if r.get("failure_log_excerpt")]; return {"run_id":run_id,"log":"\n\n".join(excerpts) if excerpts else "No detailed failure log was captured for this run."}

    def pools(self,days:int)->list[dict[str,Any]]:
        start=datetime.now(timezone.utc)-timedelta(days=days); return fetch_all("SELECT metric_date,pool_name,total_runs,total_jobs,avg_job_duration_seconds,avg_queue_wait_seconds,active_agents_count FROM dbo.vw_agent_pool_saturation WHERE metric_date>=CAST(? AS date) ORDER BY metric_date DESC,total_jobs DESC",(start,))

def percentile(values:list[float],p:float)->float|None:
    if not values:return None
    values=sorted(values); pos=(len(values)-1)*p; low=int(pos); high=min(low+1,len(values)-1); return round(values[low]+(values[high]-values[low])*(pos-low),2)
