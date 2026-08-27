import json
import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_config, read_or_create_schema
from app.engine import apply_diff
from app.log import read_recent_events, setup_logging
from app.server import create_app


CONTACTS_DIFF = {
    "summary": "Add a contacts table.",
    "app": {"title": "Rolodex"},
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

PHONE_DIFF = {
    "summary": "Add a phone field.",
    "add_columns": [
        {
            "table": "contacts",
            "column": {
                "name": "phone",
                "type": "TEXT",
                "label": "Phone",
                "nullable": True,
                "widget": "text",
            },
        }
    ],
}

SECRET_KEY = "sk-abcdefghijklmnopqrstuvwxyz012345"


class Slice8IntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        (self.appdir / ".env").write_text(
            f"LLM_API_KEY={SECRET_KEY}\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def _client(self, complete):
        self.cfg = load_config(self.appdir)
        setup_logging(self.cfg)
        return create_app(llm_complete=complete).test_client()

    def _log_text(self) -> str:
        path = self.appdir / self.cfg.logging.file
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")

    def test_fake_llm_creates_tables_and_increments_version(self) -> None:
        def fake(_messages):
            return "```json\n" + json.dumps(CONTACTS_DIFF) + "\n```"

        client = self._client(fake)
        before = read_or_create_schema(self.appdir)
        self.assertEqual(before["version"], 0)
        self.assertEqual(before["tables"], {})
        res = client.post("/api/intent", json={"text": "Track my contacts."})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertIn("contacts", body["schema"]["tables"])
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["summary"], "Add a contacts table.")
        after = read_or_create_schema(self.appdir)
        self.assertEqual(after["version"], 1)
        self.assertIn("contacts", after["tables"])

    def test_fake_llm_invalid_json_leaves_version(self) -> None:
        def fake(_messages):
            return "```json\nnot a spec\n```"

        client = self._client(fake)
        res = client.post("/api/intent", json={"text": "Anything."})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["error_code"], "llm_parse")
        self.assertEqual(read_or_create_schema(self.appdir)["version"], 0)
        events = read_recent_events(self.appdir / self.cfg.logging.file, 80)
        fails = [e for e in events if e.get("event") == "intent.apply.fail"]
        self.assertTrue(fails)
        self.assertEqual(fails[-1]["detail"]["error_code"], "llm_parse")
        parse_events = [e for e in events if e.get("event") == "llm.parse"]
        self.assertTrue(parse_events)
        head = (parse_events[-1].get("detail") or {}).get("output_head") or ""
        self.assertLessEqual(len(head), 500)
        self.assertIn("not a spec", head)

    def test_fake_llm_add_column_after_insert_keeps_row(self) -> None:
        self.cfg = load_config(self.appdir)
        setup_logging(self.cfg)
        apply_diff(self.cfg, CONTACTS_DIFF)

        def fake(_messages):
            return json.dumps(PHONE_DIFF)

        client = create_app(llm_complete=fake).test_client()
        created = client.post("/api/tables/contacts", json={"name": "Ada"})
        self.assertEqual(created.status_code, 201)
        row_id = created.get_json()["id"]
        res = client.post("/api/intent", json={"text": "Add a phone number."})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["version"], 2)
        row = client.get(f"/api/tables/contacts/{row_id}").get_json()
        self.assertEqual(row["name"], "Ada")
        self.assertIsNone(row["phone"])

    def test_validate_fail_jsonl_has_no_api_key(self) -> None:
        def fake(_messages):
            return json.dumps({"drop_tables": ["contacts"], "summary": "no"})

        client = self._client(fake)
        res = client.post("/api/intent", json={"text": "Drop everything."})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(read_or_create_schema(self.appdir)["version"], 0)
        events = read_recent_events(self.appdir / self.cfg.logging.file, 80)
        fails = [e for e in events if e.get("event") == "engine.validate.fail"]
        self.assertTrue(fails)
        self.assertFalse(fails[-1].get("ok"))
        blob = self._log_text()
        self.assertNotIn("LLM_API_KEY", blob)
        self.assertNotIn(SECRET_KEY, blob)


class Slice8OpsJsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.src = Path("static/js/ops.js").read_text(encoding="utf-8")
        self.html = Path("static/ops.html").read_text(encoding="utf-8")

    def test_ops_page_contract(self) -> None:
        self.assertIn("/api/intent", self.src)
        self.assertIn("/api/ops/thread", self.src)
        self.assertIn("/api/logs", self.src)
        self.assertIn("Refresh the App tab", self.src)
        self.assertNotIn("innerHTML", self.src)
        self.assertNotIn("BroadcastChannel", self.src)
        self.assertNotIn("WebSocket", self.src)
        self.assertIn('href="/"', self.html)
        self.assertIn("schema-version", self.html)
        self.assertIn("intent-text", self.html)
        self.assertIn("intent-busy", self.html)
        self.assertIn("ops-thread", self.html)
        self.assertIn("ops-thread-clear", self.html)
        self.assertIn("intent-guidance", self.html)
        self.assertIn("intent-bootstrap-hint", self.html)
        self.assertIn("loadThread", self.src)
        self.assertIn("renderThread", self.src)
        self.assertIn("sendIntent", self.src)
        self.assertIn("applyProposedDiff", self.src)
        self.assertIn('mode: "repl"', self.src)
        self.assertIn("spinner-border", self.html)
        self.assertIn("d-none", self.html)
        self.assertIn("setBusy", self.src)


if __name__ == "__main__":
    unittest.main()
