import os
import tempfile
import unittest
from pathlib import Path

import yaml

from app.auth import OWNER_ROLE, create_user, ensure_owner, list_users, login
from app.config import load_config
from app.host_db import ensure_host_tables
from app.server import create_app


class AuthBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def _write_conf(self, auth: dict) -> None:
        self.appdir.mkdir(parents=True, exist_ok=True)
        (self.appdir / "conf.yaml").write_text(
            yaml.safe_dump(
                {
                    "server": {"bind": "127.0.0.1", "port": 8000},
                    "llm": {"provider": "openai_compatible", "model": "test"},
                    "auth": auth,
                }
            ),
            encoding="utf-8",
        )
        (self.appdir / ".env").write_text("LLM_API_KEY=\n", encoding="utf-8")

    def _bootstrap(self, auth: dict):
        self._write_conf(auth)
        cfg = load_config(self.appdir)
        ensure_host_tables(cfg.appdir)
        ensure_owner(cfg)
        return cfg

    def test_ensure_owner_uses_conf_yaml_defaults(self) -> None:
        cfg = self._bootstrap({"owner": {"name": "admin", "password": "admin"}})
        users = list_users(cfg)
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["name"], "admin")
        self.assertEqual(users[0]["role"], OWNER_ROLE)
        token, user = login(cfg, "admin", "admin")
        self.assertTrue(token)
        self.assertEqual(user["role"], OWNER_ROLE)

    def test_env_password_overrides_conf_yaml(self) -> None:
        self._write_conf({"owner": {"name": "admin", "password": "admin"}})
        (self.appdir / ".env").write_text(
            "LLM_API_KEY=\nDESKTOPPER_OWNER_PASSWORD=fromenv\n",
            encoding="utf-8",
        )
        cfg = load_config(self.appdir)
        ensure_host_tables(cfg.appdir)
        ensure_owner(cfg)
        with self.assertRaises(ValueError):
            login(cfg, "admin", "admin")
        login(cfg, "admin", "fromenv")

    def test_get_users_requires_owner_session(self) -> None:
        cfg = self._bootstrap({"owner": {"name": "admin", "password": "admin"}})
        client = create_app().test_client()
        anon = client.get("/api/users")
        self.assertEqual(anon.status_code, 403)
        owner_token, _ = login(cfg, "admin", "admin")
        create_user(cfg, "guest1", "secret", "guest")
        guest_token, _ = login(cfg, "guest1", "secret")
        owner_client = create_app().test_client()
        owner_client.set_cookie("desktopper_session", owner_token)
        ok = owner_client.get("/api/users")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(len(ok.get_json()["users"]), 2)
        guest_client = create_app().test_client()
        guest_client.set_cookie("desktopper_session", guest_token)
        denied = guest_client.get("/api/users")
        self.assertEqual(denied.status_code, 403)

    def test_create_user_rejects_owner_role(self) -> None:
        cfg = self._bootstrap({"owner": {"name": "admin", "password": "admin"}})
        with self.assertRaises(ValueError):
            create_user(cfg, "other", "secret", OWNER_ROLE)


if __name__ == "__main__":
    unittest.main()
