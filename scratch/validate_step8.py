import json
import sys
sys.path.insert(0, ".")
from backend.app.core.config import get_settings
from core.db import AlertRepository, build_analysis_summary

def main():
    settings = get_settings()
    repo = AlertRepository(settings.sql_connection_string)
    raw_metrics = repo.get_pipeline_metrics(1, days=90)
    print(f"Total metric rows from get_pipeline_metrics: {len(raw_metrics)}")
    task_rows = [r for r in raw_metrics if r.get("task_record_id")]
    unique_keys = set((r['run_id'], r['task_record_id']) for r in task_rows)
    print(f"Task rows count: {len(task_rows)}, Unique (run_id, task_record_id): {len(unique_keys)}")
    assert len(task_rows) == len(unique_keys), "Task rows must be unique!"

    summary = build_analysis_summary(raw_metrics, window_days=90)
    print(json.dumps(summary, indent=2))

    default_stage = next(s for s in summary['stages'] if s['name'] == '__default')
    checkout = next(t for t in default_stage['tasks'] if 'Checkout' in t['name'])
    print(f"\n__default stage avg_duration_s: {default_stage['avg_duration_s']}")
    print(f"Checkout task avg_duration_s: {checkout['avg_duration_s']}")
    print(f"Checkout task pct_of_parent_duration: {checkout['pct_of_parent_duration']}%")

    assert default_stage['avg_duration_s'] == 5.3, f"Expected 5.3, got {default_stage['avg_duration_s']}"
    assert checkout['pct_of_parent_duration'] == 20.9, f"Expected 20.9, got {checkout['pct_of_parent_duration']}"
    print("\nSTEP 8 VALIDATION PASSED!")

if __name__ == '__main__':
    main()
