import unittest
from pathlib import Path

from app.system_prompt import FINAL_SYSTEM_PROMPT, REPL_APPENDIX, SYSTEM_PROMPT, load_system_prompt


class SystemPromptTests(unittest.TestCase):
    def test_load_returns_final_prompt(self) -> None:
        self.assertEqual(load_system_prompt(), FINAL_SYSTEM_PROMPT)
        self.assertEqual(load_system_prompt("apply"), FINAL_SYSTEM_PROMPT)

    def test_load_repl_includes_appendix(self) -> None:
        repl = load_system_prompt("repl")
        self.assertTrue(repl.startswith(FINAL_SYSTEM_PROMPT))
        self.assertIn("Ops REPL mode", repl)
        self.assertIn(REPL_APPENDIX.strip()[:40], repl)

    def test_system_prompt_is_alias(self) -> None:
        self.assertEqual(SYSTEM_PROMPT, FINAL_SYSTEM_PROMPT)

    def test_final_sections_present(self) -> None:
        text = FINAL_SYSTEM_PROMPT
        self.assertIn("spec editor", text)
        self.assertIn("add_tables", text)
        self.assertIn("add_formulas", text)
        self.assertIn("add_reminders", text)
        self.assertIn("add_layouts", text)
        self.assertIn("update_columns", text)
        self.assertIn("remove_columns", text)
        self.assertIn('"type": "layout"', text)
        self.assertIn("layout_id", text)
        self.assertIn("add_hooks", text)
        self.assertIn("Changing fields", text)
        self.assertIn("Empty schema bootstrap", text)
        self.assertNotIn("ignore those parts", text)

    def test_no_cache_read_in_loader(self) -> None:
        src = Path("app/system_prompt.py").read_text(encoding="utf-8")
        self.assertNotIn("read_text", src)
        self.assertNotIn("Path(", src)
        self.assertIn("def load_system_prompt", src)

    def test_llm_and_intent_do_not_read_cache(self) -> None:
        llm = Path("app/llm.py").read_text(encoding="utf-8")
        intent = Path("app/intent.py").read_text(encoding="utf-8")
        self.assertNotIn("docs/cache", llm)
        self.assertNotIn("MVP-PROMPT", llm)
        self.assertNotIn("docs/cache", intent)
        self.assertIn("app.system_prompt", intent)


if __name__ == "__main__":
    unittest.main()
