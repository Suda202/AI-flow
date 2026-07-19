import unittest
from pathlib import Path


class MultisourceWorkflowTests(unittest.TestCase):
    def test_workflow_exposes_ai_flow_source_controls(self):
        workflow = Path(".github/workflows/digest.yml").read_text()

        self.assertIn("name: AI Flow Daily", workflow)
        for variable in (
            "INFORMATION_TAKE",
            "INFORMATION_CANDIDATE_TAKE",
            "FOLLOW_BUILDERS_ENABLED",
            "AI_NEWS_RADAR_ENABLED",
            "QMREADER_ENABLED",
        ):
            self.assertIn(f"{variable}: ${{{{ vars.{variable} }}}}", workflow)


if __name__ == "__main__":
    unittest.main()
