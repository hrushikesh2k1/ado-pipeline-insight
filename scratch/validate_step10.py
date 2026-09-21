import sys
sys.path.insert(0, ".")
from backend.app.core.db import fetch_all
from backend.app.core.config import get_settings
from core.db import AlertRepository, build_analysis_summary

def main():
    sql_rows = fetch_all("""
        SELECT task_name, AVG(avg_duration_seconds) AS sql_avg_duration,
               AVG(pct_of_parent_duration) AS sql_pct_of_parent
        FROM dbo.vw_task_duration_trend
        WHERE pipeline_id = 1
        GROUP BY task_name
        ORDER BY sql_pct_of_parent DESC
    """)

    settings = get_settings()
    repo = AlertRepository(settings.sql_connection_string)
    raw = repo.get_pipeline_metrics(1, days=90)
    summary = build_analysis_summary(raw, window_days=90)
    py_tasks = {t['name']: t for s in summary['stages'] for t in s['tasks']}

    print(f"{'Task Name':<40} | {'SQL View %':<12} | {'Python Analytics %':<20}")
    print("-" * 76)
    for r in sql_rows:
        tname = r['task_name']
        sql_pct = round(r['sql_pct_of_parent'], 2) if r['sql_pct_of_parent'] is not None else 0.0
        py_pct = py_tasks.get(tname, {}).get('pct_of_parent_duration', 'Filtered (<5%)')
        print(f"{tname:<40} | {sql_pct:>8.2f}%   | {str(py_pct):>15}%")

if __name__ == '__main__':
    main()
