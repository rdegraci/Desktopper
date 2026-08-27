import json
import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_config, read_or_create_schema
from app.engine import apply_diff
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

INVALID_DIFF = {"drop_tables": ["contacts"], "summary": "no"}


class ReplIntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def _client(self, complete):
        return create_app(llm_complete=complete).test_client()

    def test_clarify_does_not_bump_version(self) -> None:
        def fake(_messages):
            return json.dumps(
                {
                    "action": "clarify",
                    "message": "What fields do you need?",
                    "open_questions": ["Due dates?"],
                }
            )

        client = self._client(fake)
        res = client.post("/api/intent", json={"text": "Task tracker", "mode": "repl"})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["action"], "clarify")
        self.assertIsNone(body.get("version"))
        self.assertEqual(read_or_create_schema(self.appdir)["version"], 0)

    def test_propose_does_not_bump_version(self) -> None:
        def fake(_messages):
            return json.dumps(
                {
                    "action": "propose",
                    "message": "I'll add contacts.",
                    "proposed_diff": CONTACTS_DIFF,
                }
            )

        client = self._client(fake)
        res = client.post("/api/intent", json={"text": "Contacts", "mode": "repl"})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["action"], "propose")
        self.assertTrue(body["validation"]["ok"])
        self.assertEqual(read_or_create_schema(self.appdir)["version"], 0)

    def test_propose_invalid_diff_returns_200_with_errors(self) -> None:
        def fake(_messages):
            return json.dumps(
                {
                    "action": "propose",
                    "message": "Bad plan.",
                    "proposed_diff": INVALID_DIFF,
                }
            )

        client = self._client(fake)
        res = client.post("/api/intent", json={"text": "Drop", "mode": "repl"})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["action"], "propose")
        self.assertFalse(body["validation"]["ok"])
        self.assertTrue(body["validation"]["errors"])

    def test_apply_increments_version(self) -> None:
        def fake(_messages):
            return json.dumps(
                {
                    "action": "apply",
                    "message": "Added contacts.",
                    "proposed_diff": CONTACTS_DIFF,
                }
            )

        client = self._client(fake)
        res = client.post("/api/intent", json={"text": "Do it", "mode": "repl"})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["action"], "apply")
        self.assertEqual(body["version"], 1)

    def test_apply_diff_skips_llm(self) -> None:
        calls = {"n": 0}

        def fake(_messages):
            calls["n"] += 1
            return json.dumps({"action": "apply", "message": "x", "proposed_diff": CONTACTS_DIFF})

        client = self._client(fake)
        res = client.post("/api/intent", json={"mode": "repl", "apply_diff": CONTACTS_DIFF})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(calls["n"], 0)
        self.assertEqual(res.get_json()["version"], 1)

    def test_apply_invalid_diff_returns_422(self) -> None:
        client = self._client(lambda _m: "{}")
        res = client.post("/api/intent", json={"mode": "repl", "apply_diff": INVALID_DIFF})
        self.assertEqual(res.status_code, 422)
        self.assertIn("rejected_diff", res.get_json())

    def test_legacy_text_only_unchanged(self) -> None:
        def fake(_messages):
            return json.dumps(CONTACTS_DIFF)

        client = self._client(fake)
        res = client.post("/api/intent", json={"text": "Track contacts."})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertIn("summary", body)
        self.assertNotIn("action", body)
        self.assertEqual(body["version"], 1)


if __name__ == "__main__":
    unittest.main()
