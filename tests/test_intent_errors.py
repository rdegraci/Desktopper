import json
import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_config
from app.server import create_app


BAD_ADD_COLUMNS_DIFF = {
    "summary": "Add checkbox.",
    "add_columns": [
        {
            "table": "contacts",
            "name": "done",
            "type": "INTEGER",
            "widget": "checkbox",
        }
    ],
}


class IntentErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        (self.appdir / ".env").write_text("LLM_API_KEY=test\n", encoding="utf-8")

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_validation_failure_returns_detail_and_rejected_diff(self) -> None:
        def fake_complete(_messages):
            return json.dumps(BAD_ADD_COLUMNS_DIFF)

        app = create_app()
        app.config["LLM_COMPLETE"] = fake_complete
        client = app.test_client()
        resp = client.post("/api/intent", json={"text": "add a done checkbox"})
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertIn("unknown keys", body["error"])
        self.assertEqual(body["error_code"], "unknown_key")
        self.assertIn("detail", body)
        self.assertEqual(body["detail"]["path"], "add_columns[0]")
        self.assertIn("name", body["detail"]["unknown_keys"])
        self.assertIn("rejected_diff", body)
        self.assertEqual(body["rejected_diff"]["summary"], "Add checkbox.")
