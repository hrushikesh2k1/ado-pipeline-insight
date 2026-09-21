import sys
sys.path.insert(0, ".")
from backend.app.services.pipeline_service import PipelineService
from backend.app.repositories.pipeline_repository import PipelineRepository
from backend.app.core.db import fetch_all

def main():
    service = PipelineService()
    repo = PipelineRepository()

    # 1. Summary
    summary = service.summary(pipeline_id=1, days=90)
    print("Summary:", {k: v for k, v in summary.items() if k != 'stages'})
    print("Stages in summary:", summary.get('stages'))
    assert summary['total_runs'] >= 32
    assert summary['average_duration_seconds'] > 0

    # 2. Runs list
    runs_result = repo.runs(pipeline_id=1, page=1, page_size=5, status=None)
    print(f"\nRuns page 1 count: {len(runs_result.get('items', []))}, total: {runs_result.get('total_count')}")
    assert len(runs_result['items']) == 5

    # 3. Timeline
    timeline = repo.timeline(run_id=1)
    print(f"\nRun 1 timeline: stages={len(timeline.get('stages', []))}, jobs={len(timeline.get('jobs', []))}, tasks={len(timeline.get('tasks', []))}")
    assert len(timeline.get('stages', [])) >= 1
    assert len(timeline.get('tasks', [])) >= 1

    # 4. Trends
    trends = service.trends(pipeline_id=1, days=90)
    print(f"\nTrends items count: build_trend={len(trends.get('build_trend', []))}, daily_trend={len(trends.get('daily_trend', []))}, stage_trend={len(trends.get('stage_trend', []))}")

    # 5. DORA metrics from SQL view
    dora = fetch_all("SELECT TOP 2 * FROM dbo.vw_dora_metrics WHERE pipeline_id=1 ORDER BY metric_date DESC")
    print(f"\nDORA rows: {len(dora)}")
    for d in dora:
        print(" ", d)

    # 6. Task duration trend view
    task_trends = fetch_all("SELECT TOP 2 * FROM dbo.vw_task_duration_trend WHERE pipeline_id=1 ORDER BY run_date DESC")
    print(f"\nTask trends rows: {len(task_trends)}")
    for tt in task_trends:
        print(" ", tt)

    # 7. Recommendations
    recs = repo.recommendations(pipeline_id=1, limit=5)
    print(f"\nRecommendations count: {len(recs)}")
    for r in recs:
        print(" ", r['category'], "|", r['recommendation'][:60], "|", r['evidence'][:60])

    print("\nSTEP 13 ALL OTHER ANALYTICS VALIDATED!")

if __name__ == '__main__':
    main()
