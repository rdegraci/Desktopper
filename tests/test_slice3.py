import os
import tempfile
import unittest
from pathlib import Path


class Slice3SchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        from app.server import create_app

        self.flask_app = create_app()
        self.client = self.flask_app.test_client()

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_get_schema_version_zero(self) -> None:
        res = self.client.get("/api/schema")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["version"], 0)
        self.assertEqual(data["app"]["title"], "Desktopper")
        self.assertEqual(data["tables"], {})
        self.assertEqual(data["screens"], [])

    def test_missing_schema_file_is_recreated(self) -> None:
        path = self.appdir / "schema.json"
        self.assertTrue(path.is_file())
        path.unlink()
        res = self.client.get("/api/schema")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["version"], 0)
        self.assertTrue(path.is_file())

    def test_schema_read_is_logged(self) -> None:
        self.client.get("/api/schema")
        logs = self.client.get("/api/logs?limit=100").get_json()
        events = logs["events"]
        self.assertTrue(any(e.get("event") == "schema.read" for e in events))

    def test_home_has_global_search_input(self) -> None:
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="global-search"', html)
        js = self.client.get("/js/app.js").get_data(as_text=True)
        self.assertNotIn("/api/intent", js)
        self.assertNotIn("window.open", js)

    def test_ops_js_has_no_intent_post(self) -> None:
        js = self.client.get("/js/ops.js").get_data(as_text=True)
        self.assertNotIn("/api/intent", js)
        self.assertIn("schema.version", js)


if __name__ == "__main__":
    unittest.main()
