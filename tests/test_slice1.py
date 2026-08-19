import os
import tempfile
import unittest
from pathlib import Path

from app.config import BindRefusedError, ensure_appdir, load_config


class Slice1ConfigTests(unittest.TestCase):
    def test_copy_once_does_not_overwrite_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            appdir = Path(tmp)
            os.environ["DESKTOPPER_APPDIR"] = str(appdir)
            self.addCleanup(os.environ.pop, "DESKTOPPER_APPDIR", None)
            ensure_appdir(appdir)
            env_path = appdir / ".env"
            env_path.write_text("LLM_API_KEY=keepme\n", encoding="utf-8")
            ensure_appdir(appdir)
            self.assertEqual(env_path.read_text(encoding="utf-8"), "LLM_API_KEY=keepme\n")

    def test_bind_all_interfaces_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            appdir = Path(tmp)
            os.environ["DESKTOPPER_APPDIR"] = str(appdir)
            self.addCleanup(os.environ.pop, "DESKTOPPER_APPDIR", None)
            ensure_appdir(appdir)
            conf = appdir / "conf.yaml"
            text = conf.read_text(encoding="utf-8")
            text = text.replace('bind: "127.0.0.1"', 'bind: "0.0.0.0"')
            conf.write_text(text, encoding="utf-8")
            with self.assertRaises(BindRefusedError) as ctx:
                load_config(appdir)
            self.assertEqual(ctx.exception.error_code, "bind_refused")


class Slice1FlaskTests(unittest.TestCase):
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

    def test_home_has_ops_link_not_intent(self) -> None:
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('href="/ops"', html)
        self.assertIn('target="_blank"', html)
        self.assertNotIn("intent-text", html)
        self.assertNotIn("window.open", html)

    def test_ops_page(self) -> None:
        res = self.client.get("/ops")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('href="/"', html)
        self.assertIn("later slice", html)

    def test_schema_and_logs(self) -> None:
        res = self.client.get("/api/schema")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["version"], 0)
        self.assertEqual(data["app"]["title"], "Desktopper")
        logs = self.client.get("/api/logs?limit=50")
        self.assertEqual(logs.status_code, 200)
        body = logs.get_json()
        self.assertIn("events", body)
        events = body["events"]
        self.assertTrue(any(e.get("event") == "config.load" for e in events))
        for event in events:
            blob = str(event)
            self.assertNotIn("keepme", blob)

    def test_rejects_dotdot_static(self) -> None:
        res = self.client.get("/css/../ops.html")
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
