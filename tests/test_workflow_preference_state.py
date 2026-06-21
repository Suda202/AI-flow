import unittest
from pathlib import Path


class WorkflowPreferenceStateTests(unittest.TestCase):
    def test_digest_workflow_restores_analyzes_and_saves_preference_state(self):
        workflow = Path(".github/workflows/digest.yml").read_text()

        self.assertGreaterEqual(workflow.count("preference_state.json"), 3)
        analysis_block = workflow.split("- name: Analyze feedback and update preferences", 1)[1]
        analysis_block = analysis_block.split("- name: Run digest", 1)[0]
        self.assertIn("DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}", analysis_block)
        self.assertIn("DEEPSEEK_API_BASE: ${{ secrets.DEEPSEEK_API_BASE }}", analysis_block)
        self.assertIn("DEEPSEEK_MODEL: ${{ secrets.DEEPSEEK_MODEL }}", analysis_block)
        self.assertNotIn("GEMINI_API_KEY", workflow)

    def test_runtime_and_docs_use_deepseek_names(self):
        paths = [
            "main.py",
            "update_preferences.py",
            ".github/workflows/digest.yml",
            "README.md",
            "QUICK_START.md",
            "FEISHU_APP_SETUP.md",
            "GET_USER_ID.md",
            "docs/superpowers/plans/2026-06-21-continuous-preference-learning.md",
            "docs/superpowers/specs/2026-06-21-continuous-preference-learning-design.md",
        ]

        for path in paths:
            with self.subTest(path=path):
                self.assertNotIn("MINIMAX_", Path(path).read_text())

    def test_python_dependencies_do_not_include_gemini_sdk(self):
        requirements = Path("requirements.txt").read_text()

        self.assertNotIn("google-genai", requirements)


if __name__ == "__main__":
    unittest.main()
