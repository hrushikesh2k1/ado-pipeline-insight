import sys
import json
sys.path.insert(0, ".")
from backend.app.core.db import fetch_all

def main():
    # 1. Inspect stages for pipeline 1
    stages = fetch_all("""
        SELECT s.run_id, s.record_id, s.stage_name, s.start_time, s.finish_time, s.duration_seconds, s.result
        FROM pipeline_stages s
        JOIN pipeline_runs r ON r.run_id = s.run_id
        WHERE r.pipeline_id = 1
        ORDER BY s.run_id, s.start_time
    """)
    print(f"Total stage records for pipeline 1: {len(stages)}")
    stage_names = set(s['stage_name'] for s in stages)
    print(f"Unique stage names: {stage_names}")
    for s in stages[:5]:
        print("Stage sample:", s)

    # 2. Inspect jobs for pipeline 1
    jobs = fetch_all("""
        SELECT j.run_id, j.record_id, j.stage_name, j.job_name, j.start_time, j.finish_time, j.duration_seconds, j.result
        FROM pipeline_jobs j
        JOIN pipeline_runs r ON r.run_id = j.run_id
        WHERE r.pipeline_id = 1
        ORDER BY j.run_id, j.start_time
    """)
    print(f"\nTotal job records for pipeline 1: {len(jobs)}")
    for j in jobs[:5]:
        print("Job sample:", j)

    # 3. Inspect tasks for Checkout project-1@main to s
    tasks = fetch_all("""
        SELECT t.run_id, t.record_id, t.stage_name, t.job_name, t.task_name, t.start_time, t.finish_time, t.duration_seconds, t.result
        FROM pipeline_tasks t
        JOIN pipeline_runs r ON r.run_id = t.run_id
        WHERE r.pipeline_id = 1 AND t.task_name = 'Checkout project-1@main to s'
        ORDER BY t.run_id
    """)
    print(f"\nTotal Checkout tasks for pipeline 1: {len(tasks)}")
    for t in tasks[:10]:
        print("Task sample:", t)

    # 4. Check all tasks for a single run (e.g. the first run)
    sample_run_id = tasks[0]['run_id'] if tasks else 1
    print(f"\nAll tasks for run_id={sample_run_id}:")
    run_tasks = fetch_all(f"""
        SELECT record_id, stage_name, job_name, task_name, start_time, finish_time, duration_seconds, result
        FROM pipeline_tasks
        WHERE run_id = {sample_run_id}
        ORDER BY start_time
    """)
    for rt in run_tasks:
        print("  ", rt)

if __name__ == '__main__':
    main()
