import sys
sys.path.insert(0, ".")
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import json
from backend.app.core.db import fetch_all
from core.db import _stats, _durations, _average

def test_build_summary():
    start = datetime.now(timezone.utc) - timedelta(days=90)
    query = """
        SELECT r.run_id, r.pipeline_id, p.pipeline_name,
               COALESCE(s.stage_name, t.stage_name) AS stage_name,
               s.duration_seconds AS stage_duration_seconds,
               s.start_time AS stage_start_time,
               s.result AS stage_result,
               t.job_name, t.task_name, t.record_id AS task_record_id,
               COALESCE(t.duration_seconds, s.duration_seconds) AS duration_seconds,
               COALESCE(t.result, s.result) AS result,
               COALESCE(t.retry_count, 0) AS retry_count,
               r.queue_time,
               COALESCE(t.start_time, s.start_time) AS start_time,
               t.failure_log_excerpt
        FROM pipeline_runs r
        JOIN pipelines p ON p.pipeline_id = r.pipeline_id
        LEFT JOIN pipeline_stages s ON s.run_id = r.run_id
        LEFT JOIN pipeline_tasks t ON t.run_id = r.run_id AND t.stage_name = s.stage_name
        WHERE r.pipeline_id = 1 AND r.start_time >= ?
    """
    rows = fetch_all(query, (start,))
    print(f"Total rows: {len(rows)}")

    # Check task uniqueness by (run_id, task_record_id)
    task_rows = [r for r in rows if r.get("task_record_id")]
    unique_task_keys = set((r['run_id'], r['task_record_id']) for r in task_rows)
    print(f"Task rows: {len(task_rows)}, Unique (run_id, task_record_id): {len(unique_task_keys)}")
    assert len(task_rows) == len(unique_task_keys), "Task rows are not unique!"

    # Now run the proposed build_analysis_summary logic
    grouped = defaultdict(list)
    for row in rows:
        if row.get("stage_name"):
            grouped[row["stage_name"]].append(row)

    stages = []
    for stage_name, stage_rows in grouped.items():
        stage_run_map = {}
        for row in stage_rows:
            run_key = row.get("run_id") or id(row)
            if run_key not in stage_run_map:
                stage_dur = row.get("stage_duration_seconds")
                if stage_dur is None and not row.get("task_name"):
                    stage_dur = row.get("duration_seconds")
                stage_run_map[run_key] = {
                    "duration_seconds": stage_dur,
                    "start_time": row.get("stage_start_time") or row.get("start_time"),
                    "result": row.get("stage_result") or row.get("result"),
                    "retry_count": row.get("retry_count", 0),
                }

        stage_records = list(stage_run_map.values())
        stage_durations = _durations(stage_records)
        if not stage_durations:
            stage_durations = _durations(stage_rows)
            stage_average = _average(stage_durations)
            stage_stats = _stats(stage_rows)
        else:
            stage_average = _average(stage_durations)
            stage_stats = _stats(stage_records)

        task_groups = defaultdict(list)
        for row in stage_rows:
            if row.get("task_name"):
                task_groups[row["task_name"]].append(row)

        tasks = []
        for task_name, task_rows in task_groups.items():
            stats = _stats(task_rows)
            stats["name"] = task_name
            task_avg = _average(_durations(task_rows))
            stats["pct_of_parent_duration"] = round(100 * task_avg / stage_average, 1) if stage_average else 0
            if stats["pct_of_parent_duration"] >= 5 or stats["failure_rate_pct"] > 0 or stats["retry_rate_pct"] > 0:
                tasks.append(stats)

        stage_stats.update({
            "name": stage_name,
            "tasks": sorted(tasks, key=lambda item: item["avg_duration_s"], reverse=True)
        })
        stages.append(stage_stats)

    summary = {"pipeline": rows[0].get("pipeline_name"), "window_days": 90, "stages": stages}
    print("\nSummary JSON payload:")
    print(json.dumps(summary, indent=2))

    # Verify Checkout task
    default_stage = next(s for s in stages if s["name"] == "__default")
    print(f"\n__default stage avg_duration_s: {default_stage['avg_duration_s']}")
    checkout_task = next(t for t in default_stage["tasks"] if "Checkout" in t["name"])
    print(f"Checkout task avg_duration_s: {checkout_task['avg_duration_s']}")
    print(f"Checkout task pct_of_parent_duration: {checkout_task['pct_of_parent_duration']}%")

    assert default_stage['avg_duration_s'] == 5.3, f"Expected 5.3, got {default_stage['avg_duration_s']}"
    assert checkout_task['pct_of_parent_duration'] == 20.9, f"Expected 20.9, got {checkout_task['pct_of_parent_duration']}"
    print("\nALL ASSERTIONS PASSED!")

if __name__ == '__main__':
    test_build_summary()
