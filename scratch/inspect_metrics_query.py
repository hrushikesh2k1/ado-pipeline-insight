import sys
sys.path.insert(0, ".")
from backend.app.core.config import get_settings
from core.db import AlertRepository

def main():
    settings = get_settings()
    repo = AlertRepository(settings.sql_connection_string)
    rows = repo.get_pipeline_metrics(1, days=90)
    print(f"Total rows returned by get_pipeline_metrics: {len(rows)}")
    default_rows = [r for r in rows if r['stage_name'] == '__default']
    print(f"Total __default rows: {len(default_rows)}")

    # Let's inspect unique task names and their duration_seconds in default_rows
    from collections import Counter, defaultdict
    task_counts = Counter(r['task_name'] for r in default_rows)
    print("\nTask counts in __default:")
    for name, cnt in task_counts.items():
        durations = [r['duration_seconds'] for r in default_rows if r['task_name'] == name]
        avg_d = sum(durations) / len(durations) if durations else 0
        print(f"  {repr(name)}: count={cnt}, avg_duration={avg_d:.3f}s, sample={durations[:3]}")

    # Inspect all rows for run_id=1
    print("\nAll rows in get_pipeline_metrics for run 1:")
    # We need run_id, but get_pipeline_metrics doesn't select run_id! Let's check columns:
    print("Columns:", list(rows[0].keys()) if rows else [])

if __name__ == '__main__':
    main()
