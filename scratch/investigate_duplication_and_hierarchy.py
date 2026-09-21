import sys
sys.path.insert(0, ".")
from backend.app.core.db import fetch_all

def main():
    # Inspect pipeline_jobs for run_id=1
    print("=== pipeline_jobs for run_id=1 ===")
    jobs = fetch_all("SELECT * FROM pipeline_jobs WHERE run_id=1")
    for j in jobs:
        print("Job:", {k: v for k, v in j.items() if k != 'failure_log_excerpt'})

    # Inspect pipeline_stages for run_id=1
    print("\n=== pipeline_stages for run_id=1 ===")
    stages = fetch_all("SELECT * FROM pipeline_stages WHERE run_id=1")
    for s in stages:
        print("Stage:", {k: v for k, v in s.items() if k != 'failure_log_excerpt'})

    # Inspect pipeline_tasks for run_id=1
    print("\n=== pipeline_tasks for run_id=1 ===")
    tasks = fetch_all("SELECT * FROM pipeline_tasks WHERE run_id=1")
    for t in tasks:
        print("Task:", {k: v for k, v in t.items() if k != 'failure_log_excerpt'})

if __name__ == '__main__':
    main()
