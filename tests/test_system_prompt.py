import unittest
from pathlib import Path

from app.system_prompt import SYSTEM_PROMPT, load_system_prompt


class SystemPromptTests(unittest.TestCase):
    def test_prompt_comes_from_app_module(self) -> None:
        text = load_system_prompt()
        self.assertIn("spec editor", text)
        self.assertIn("add_tables", text)
        self.assertIn("add_formulas", text)
        self.assertIn("add_reminders", text)
        self.assertIn("add_layouts", text)
        final_path = Path("docs/cache/FINAL-PROMPT.md")
        if final_path.is_file():
            self.assertIn("formulas, rules, reminders", text)

    def test_llm_and_intent_do_not_read_cache(self) -> None:
        llm = Path("app/llm.py").read_text(encoding="utf-8")
        intent = Path("app/intent.py").read_text(encoding="utf-8")
        self.assertNotIn("docs/cache", llm)
        self.assertNotIn("MVP-PROMPT", llm)
        self.assertNotIn("docs/cache", intent)
        self.assertIn("app.system_prompt", intent)


if __name__ == "__main__":
    unittest.main()
