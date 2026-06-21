import unittest
from pathlib import Path


class WorkflowPreferenceStateTests(unittest.TestCase):
    def test_digest_workflow_restores_analyzes_and_saves_preference_state(self):
        workflow = Path(".github/workflows/digest.yml").read_text()

        self.assertGreaterEqual(workflow.count("preference_state.json"), 3)
        analysis_block = workflow.split("- name: Analyze feedback and update preferences", 1)[1]
        analysis_block = analysis_block.split("- name: Run digest", 1)[0]
        self.assertIn("MINIMAX_API_KEY: ${{ secrets.MINIMAX_API_KEY }}", analysis_block)
        self.assertIn("MINIMAX_API_BASE: ${{ secrets.MINIMAX_API_BASE }}", analysis_block)
        self.assertIn("MINIMAX_MODEL: ${{ secrets.MINIMAX_MODEL }}", analysis_block)
        self.assertNotIn("GEMINI_API_KEY", workflow)

    def test_python_dependencies_do_not_include_gemini_sdk(self):
        requirements = Path("requirements.txt").read_text()

        self.assertNotIn("google-genai", requirements)


if __name__ == "__main__":
    unittest.main()
