import sys
sys.path.insert(0, ".")
from backend.app.core.config import get_settings
from core.db import AlertRepository, _durations, _average, build_analysis_summary
from collections import defaultdict

def main():
    settings = get_settings()
    repo = AlertRepository(settings.sql_connection_string)
    raw_metrics = repo.get_pipeline_metrics(1, days=90)
    summary = build_analysis_summary(raw_metrics, window_days=90)

    stage_rows = [r for r in raw_metrics if r['stage_name'] == '__default']
    stage_run_map = { r['run_id']: r['stage_duration_seconds'] for r in stage_rows if r.get('stage_duration_seconds') is not None }
    stage_avg = sum(stage_run_map.values()) / len(stage_run_map)
    print(f"Authoritative stage average duration: {stage_avg:.4f}s across {len(stage_run_map)} runs\n")

    task_groups = defaultdict(list)
    for r in stage_rows:
        if r.get('task_name'):
            task_groups[r['task_name']].append(r['duration_seconds'])

    print(f"{'Task Name':<42} | {'Avg Duration':<12} | {'Calculated %':<12} | {'Samples':<8}")
    print("-" * 80)
    total_pct = 0.0
    for task_name, durations in sorted(task_groups.items(), key=lambda x: -sum(x[1])/len(x[1])):
        avg_d = sum(durations) / len(durations)
        pct = round(100.0 * avg_d / stage_avg, 1)
        total_pct += pct
        print(f"{task_name:<42} | {avg_d:.4f}s      | {pct:>5.1f}%       | {len(durations):<8}")
    print("-" * 80)
    print(f"{'Sum of all task percentages':<42} |              | {total_pct:>5.1f}%       |")

if __name__ == '__main__':
    main()
