import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_config
from app.engine import apply_diff
from app.log import read_recent_events, setup_logging


def _schema_diff() -> dict:
    return {
        "summary": "Contacts and books.",
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
                    },
                    {
                        "name": "secret",
                        "type": "TEXT",
                        "label": "Secret",
                        "nullable": True,
                        "widget": "text",
                        "hidden": True,
                    },
                ],
            },
            {
                "name": "books",
                "label": "Books",
                "columns": [
                    {
                        "name": "title",
                        "type": "TEXT",
                        "label": "Title",
                        "nullable": False,
                        "widget": "text",
                    }
                ],
            },
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
                "id": "books_list",
                "type": "list",
                "table": "books",
                "title": "Books",
                "columns": ["title"],
            },
        ],
    }


class Slice6SearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        self.cfg = load_config(self.appdir)
        setup_logging(self.cfg)
        apply_diff(self.cfg, _schema_diff())
        from app.server import create_app

        self.client = create_app().test_client()
        self.client.post(
            "/api/tables/contacts",
            json={"name": "Ada Lovelace", "secret": "hiddenxyz"},
        )
        self.client.post("/api/tables/contacts", json={"name": "Grace Hopper"})
        self.client.post("/api/tables/books", json={"title": "Ada notes"})
        self.client.post("/api/tables/contacts", json={"name": "100% juice"})

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_two_tokens_require_both(self) -> None:
        both = self.client.get("/api/tables/contacts?q=Ada+Lovelace")
        self.assertEqual(both.status_code, 200)
        names = [r["name"] for r in both.get_json()]
        self.assertEqual(names, ["Ada Lovelace"])
        one = self.client.get("/api/tables/contacts?q=Ada+Zebra")
        self.assertEqual(one.get_json(), [])

    def test_percent_is_literal(self) -> None:
        hits = self.client.get("/api/tables/contacts?q=%25")
        names = [r["name"] for r in hits.get_json()]
        self.assertEqual(names, ["100% juice"])
        all_rows = self.client.get("/api/tables/contacts?q=")
        self.assertGreater(len(all_rows.get_json()), 1)

    def test_global_two_tables_hidden_not_searched(self) -> None:
        empty = self.client.get("/api/search?q=")
        self.assertEqual(empty.get_json(), {"hits": []})
        ada = self.client.get("/api/search?q=Ada")
        self.assertEqual(ada.status_code, 200)
        hits = ada.get_json()["hits"]
        tables = {h["table"] for h in hits}
        self.assertEqual(tables, {"contacts", "books"})
        hidden = self.client.get("/api/search?q=hiddenxyz")
        self.assertEqual(hidden.get_json()["hits"], [])
        events = read_recent_events(self.appdir / self.cfg.logging.file, 200)
        info = [e for e in events if e.get("level") == "info"]
        for event in info:
            blob = json_dumps(event)
            self.assertNotIn("hiddenxyz", blob)


def json_dumps(event: dict) -> str:
    import json

    return json.dumps(event)


if __name__ == "__main__":
    unittest.main()
