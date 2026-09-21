import unittest
from datetime import datetime, timezone
from core.db import build_analysis_summary

class TestAnalyticsRegression(unittest.TestCase):
    def test_task_contribution_percentage_uses_stage_duration(self):
        """
        Regression test for 318% anomaly:
        Checkout task duration 1.117s in a stage with actual duration 5.342s
        must produce 20.9%, NOT 318%.
        """
        rows = [
            {
                "run_id": 1,
                "pipeline_name": "pipeline-1",
                "stage_name": "__default",
                "stage_duration_seconds": 5.342,
                "task_name": "Checkout project-1@main to s",
                "task_record_id": "rec-checkout-1",
                "duration_seconds": 1.117,
                "result": "succeeded",
                "start_time": datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc),
            },
            {
                "run_id": 1,
                "pipeline_name": "pipeline-1",
                "stage_name": "__default",
                "stage_duration_seconds": 5.342,
                "task_name": "Initialize job",
                "task_record_id": "rec-init-1",
                "duration_seconds": 0.521,
                "result": "succeeded",
                "start_time": datetime(2026, 8, 30, 12, 0, 1, tzinfo=timezone.utc),
            },
            {
                "run_id": 1,
                "pipeline_name": "pipeline-1",
                "stage_name": "__default",
                "stage_duration_seconds": 5.342,
                "task_name": "Run a script",
                "task_record_id": "rec-script-1",
                "duration_seconds": 0.216,
                "result": "succeeded",
                "start_time": datetime(2026, 8, 30, 12, 0, 2, tzinfo=timezone.utc),
            },
        ]

        summary = build_analysis_summary(rows, window_days=30)
        self.assertEqual(len(summary["stages"]), 1)
        stage = summary["stages"][0]
        self.assertEqual(stage["name"], "__default")
        self.assertEqual(stage["avg_duration_s"], 5.3)

        checkout = next(t for t in stage["tasks"] if "Checkout" in t["name"])
        self.assertEqual(checkout["avg_duration_s"], 1.1)
        # Expected: 1.117 / 5.342 * 100 = 20.9%
        self.assertEqual(checkout["pct_of_parent_duration"], 20.9)
        self.assertNotEqual(checkout["pct_of_parent_duration"], 318.0)

    def test_multi_run_stage_and_task_averages(self):
        """
        Verify multiple runs with varying stage and task durations.
        Run 1: Stage 5.0s, Task 1.0s
        Run 2: Stage 6.0s, Task 1.2s
        Stage average: 5.5s
        Task average: 1.1s
        Task percentage: 1.1 / 5.5 * 100 = 20.0%
        """
        rows = [
            {
                "run_id": 1,
                "pipeline_name": "pipeline-1",
                "stage_name": "Build",
                "stage_duration_seconds": 5.0,
                "task_name": "Compile",
                "task_record_id": "rec-compile-1",
                "duration_seconds": 1.0,
                "result": "succeeded",
                "start_time": datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc),
            },
            {
                "run_id": 2,
                "pipeline_name": "pipeline-1",
                "stage_name": "Build",
                "stage_duration_seconds": 6.0,
                "task_name": "Compile",
                "task_record_id": "rec-compile-2",
                "duration_seconds": 1.2,
                "result": "succeeded",
                "start_time": datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc),
            },
        ]

        summary = build_analysis_summary(rows, window_days=30)
        stage = summary["stages"][0]
        self.assertEqual(stage["avg_duration_s"], 5.5)
        compile_task = stage["tasks"][0]
        self.assertEqual(compile_task["avg_duration_s"], 1.1)
        self.assertEqual(compile_task["pct_of_parent_duration"], 20.0)

    def test_fallback_when_stage_duration_seconds_absent(self):
        """
        Ensure backward compatibility with fixtures where stage_duration_seconds is None.
        """
        rows = [
            {
                "run_id": 1,
                "pipeline_name": "pipeline-legacy",
                "stage_name": "TestStage",
                "task_name": "TestTask",
                "duration_seconds": 2.0,
                "result": "succeeded",
                "start_time": datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc),
            }
        ]
        summary = build_analysis_summary(rows, window_days=30)
        self.assertEqual(len(summary["stages"]), 1)
        self.assertEqual(summary["stages"][0]["avg_duration_s"], 2.0)

if __name__ == "__main__":
    unittest.main()
