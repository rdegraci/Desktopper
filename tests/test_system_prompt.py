import unittest
from pathlib import Path

from app.system_prompt import SYSTEM_PROMPT, load_system_prompt


class SystemPromptTests(unittest.TestCase):
    def test_prompt_comes_from_app_module(self) -> None:
        text = load_system_prompt()
        self.assertEqual(text, SYSTEM_PROMPT)
        self.assertIn("schema editor", text)
        self.assertIn("add_tables", text)
        self.assertIn('"empty"', text)
        self.assertIn('"role"', text)
        self.assertIn("update_tables", text)
        self.assertNotIn("docs/cache", text)

    def test_llm_and_intent_do_not_read_cache(self) -> None:
        llm = Path("app/llm.py").read_text(encoding="utf-8")
        intent = Path("app/intent.py").read_text(encoding="utf-8")
        self.assertNotIn("docs/cache", llm)
        self.assertNotIn("MVP-PROMPT", llm)
        self.assertNotIn("docs/cache", intent)
        self.assertIn("app.system_prompt", intent)


if __name__ == "__main__":
    unittest.main()
