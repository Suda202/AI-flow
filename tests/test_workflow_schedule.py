from pathlib import Path
import unittest


class WorkflowScheduleTests(unittest.TestCase):
    def test_digest_workflow_has_native_fallback_and_daily_guard(self):
        workflow = Path(".github/workflows/digest.yml").read_text()

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("schedule:", workflow)
        self.assertIn("cron: '10 2 * * *'", workflow)
        self.assertIn("force:", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("name: Check for successful run today", workflow)
        self.assertIn("id: daily_guard", workflow)
        self.assertEqual(
            workflow.count("if: steps.daily_guard.outputs.should_run == 'true'"),
            8,
        )


if __name__ == "__main__":
    unittest.main()
