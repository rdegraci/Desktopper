import json
import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_config
from app.ops_thread import append_entry, clear_thread, read_thread
from app.server import create_app


class OpsThreadModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_append_and_read(self) -> None:
        append_entry(self.appdir, {"role": "user", "text": "hello"})
        append_entry(self.appdir, {"role": "assistant", "action": "apply", "message": "done"})
        entries = read_thread(self.appdir)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["role"], "user")
        self.assertEqual(entries[0]["text"], "hello")
        self.assertIn("ts", entries[0])
        self.assertEqual(entries[1]["action"], "apply")

    def test_clear_thread(self) -> None:
        append_entry(self.appdir, {"role": "user", "text": "x"})
        clear_thread(self.appdir)
        self.assertEqual(read_thread(self.appdir), [])

    def test_skips_corrupt_lines(self) -> None:
        path = self.appdir / "ops_thread.jsonl"
        self.appdir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"role":"user","text":"ok"}\nnot json\n{"role":"assistant","message":"m"}\n',
            encoding="utf-8",
        )
        entries = read_thread(self.appdir)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["text"], "ok")
        self.assertEqual(entries[1]["message"], "m")


class OpsThreadApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        self.cfg = load_config()
        self.client = create_app().test_client()

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_get_thread_empty(self) -> None:
        res = self.client.get("/api/ops/thread")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["entries"], [])

    def test_delete_thread(self) -> None:
        append_entry(self.appdir, {"role": "user", "text": "x"})
        res = self.client.delete("/api/ops/thread")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])
        self.assertEqual(read_thread(self.appdir), [])

    def test_intent_appends_thread_entries(self) -> None:
        contacts_diff = {
            "summary": "Add contacts.",
            "add_tables": [
                {
                    "name": "contacts",
                    "label": "Contacts",
                    "columns": [
                        {
                            "name": "name",
                            "type": "TEXT",
                            "label": "Name",
                            "nullable": False,
                            "widget": "text",
                        }
                    ],
                }
            ],
            "add_screens": [
                {
                    "id": "contacts_list",
                    "type": "list",
                    "table": "contacts",
                    "title": "Contacts",
                    "columns": ["name"],
                },
                {
                    "id": "contacts_form",
                    "type": "form",
                    "table": "contacts",
                    "title": "Contact",
                },
            ],
        }

        def fake(_messages):
            return json.dumps(contacts_diff)

        client = create_app(llm_complete=fake).test_client()
        res = client.post("/api/intent", json={"text": "Track contacts."})
        self.assertEqual(res.status_code, 200)
        entries = read_thread(self.appdir)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["role"], "user")
        self.assertEqual(entries[0]["text"], "Track contacts.")
        self.assertEqual(entries[1]["role"], "assistant")
        self.assertEqual(entries[1]["action"], "apply")
        self.assertEqual(entries[1]["version"], 1)


if __name__ == "__main__":
    unittest.main()
