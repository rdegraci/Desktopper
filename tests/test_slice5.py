import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_config
from app.engine import apply_diff
from app.log import read_recent_events, setup_logging


CONTACTS_DIFF = {
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
                },
                {
                    "name": "age",
                    "type": "INTEGER",
                    "label": "Age",
                    "nullable": True,
                    "widget": "number",
                },
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
        }
    ],
}


class Slice5CrudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        self.cfg = load_config(self.appdir)
        setup_logging(self.cfg)
        apply_diff(self.cfg, CONTACTS_DIFF)
        from app.server import create_app

        self.client = create_app().test_client()

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_crud_round_trip(self) -> None:
        created = self.client.post(
            "/api/tables/contacts",
            json={"name": "Ada", "age": 36, "bogus": "ignore"},
        )
        self.assertEqual(created.status_code, 201)
        row = created.get_json()
        self.assertEqual(row["name"], "Ada")
        self.assertEqual(row["age"], 36)
        self.assertNotIn("bogus", row)
        self.assertTrue(row["created_at"])
        self.assertTrue(row["updated_at"])
        row_id = row["id"]

        listed = self.client.get("/api/tables/contacts?limit=10&offset=0")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.get_json()), 1)

        got = self.client.get(f"/api/tables/contacts/{row_id}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.get_json()["name"], "Ada")

        updated = self.client.put(
            f"/api/tables/contacts/{row_id}", json={"name": "Ada Lovelace"}
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["name"], "Ada Lovelace")

        opts = self.client.get("/api/tables/contacts/options")
        self.assertEqual(opts.status_code, 200)
        self.assertEqual(opts.get_json()[0]["label"], "Ada Lovelace")

        deleted = self.client.delete(f"/api/tables/contacts/{row_id}")
        self.assertEqual(deleted.status_code, 204)
        missing = self.client.get(f"/api/tables/contacts/{row_id}")
        self.assertEqual(missing.status_code, 404)

        events = read_recent_events(self.appdir / self.cfg.logging.file, 80)
        kinds = {e.get("event") for e in events}
        self.assertIn("crud.insert", kinds)
        self.assertIn("crud.update", kinds)
        self.assertIn("crud.delete", kinds)
        for event in events:
            if str(event.get("event", "")).startswith("crud."):
                detail = event.get("detail") or {}
                self.assertEqual(detail.get("table"), "contacts")
                self.assertIn("id", detail)
                self.assertNotIn("name", detail)

    def test_unknown_table_and_bad_type(self) -> None:
        res = self.client.get("/api/tables/no_such_table")
        self.assertEqual(res.status_code, 404)
        bad = self.client.post("/api/tables/contacts", json={"name": "x", "age": "nope"})
        self.assertEqual(bad.status_code, 400)

    def test_sql_uses_bound_parameters(self) -> None:
        src = Path("app/crud.py").read_text(encoding="utf-8")
        self.assertIn(" = ?", src)
        self.assertIn("(row_id,)", src)
        self.assertIn("(limit, offset)", src)
        self.assertNotIn("WHERE id = \" +", src)
        self.assertNotIn("WHERE id = ' +", src)


if __name__ == "__main__":
    unittest.main()
