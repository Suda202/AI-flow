import unittest
from pathlib import Path


class WorkflowPreferenceStateTests(unittest.TestCase):
    def test_digest_workflow_restores_analyzes_and_saves_preference_state(self):
        workflow = Path(".github/workflows/digest.yml").read_text()

        self.assertGreaterEqual(workflow.count("preference_state.json"), 3)
        analysis_block = workflow.split("- name: Analyze feedback and update preferences", 1)[1]
        analysis_block = analysis_block.split("- name: Run digest", 1)[0]
        self.assertIn("GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}", analysis_block)


if __name__ == "__main__":
    unittest.main()
