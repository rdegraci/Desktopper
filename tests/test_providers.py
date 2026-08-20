import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_config, redact_value
from app.llm import build_chat_request, LlmError, public_error_message
from app.providers import UnknownLlmProviderError


def _write_conf(appdir: Path, llm_block: str) -> None:
    (appdir / "conf.yaml").write_text(
        f"""
server:
  bind: "127.0.0.1"
  port: 8000
llm:
{llm_block}
app:
  timezone: UTC
  support_name: Desktopper
logging:
  level: info
  file: desktopper.jsonl
  max_bytes: 2000000
  backup_count: 3
""",
        encoding="utf-8",
    )


class XaiProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_example_defaults_to_xai_grok(self) -> None:
        cfg = load_config(self.appdir)
        self.assertEqual(cfg.llm.provider, "xai")
        self.assertEqual(cfg.llm.base_url, "https://api.x.ai/v1")
        self.assertEqual(cfg.llm.model, "grok-4.6")
        self.assertEqual(cfg.llm.reasoning_effort, "low")

    def test_xai_api_key_alias_and_llm_key_wins(self) -> None:
        _write_conf(self.appdir, "  provider: xai\n  model: grok-4.6\n")
        (self.appdir / ".env").write_text("XAI_API_KEY=xai-abcdefghijklmnopqrstuvwxyz\n")
        cfg = load_config(self.appdir)
        self.assertEqual(cfg.llm_api_key, "xai-abcdefghijklmnopqrstuvwxyz")
        (self.appdir / ".env").write_text(
            "LLM_API_KEY=sk-abcdefghijklmnopqrstuvwxyz\n"
            "XAI_API_KEY=xai-abcdefghijklmnopqrstuvwxyz\n"
        )
        cfg = load_config(self.appdir)
        self.assertEqual(cfg.llm_api_key, "sk-abcdefghijklmnopqrstuvwxyz")

    def test_unknown_provider_is_refused(self) -> None:
        _write_conf(self.appdir, "  provider: not_a_vendor\n")
        with self.assertRaises(UnknownLlmProviderError) as ctx:
            load_config(self.appdir)
        self.assertEqual(ctx.exception.error_code, "unknown_llm_provider")

    def test_openai_compatible_keeps_max_tokens(self) -> None:
        _write_conf(
            self.appdir,
            '  provider: openai_compatible\n  base_url: "http://127.0.0.1:11434/v1"\n  model: llama3.2\n',
        )
        cfg = load_config(self.appdir)
        self.assertEqual(cfg.llm.provider, "openai_compatible")
        url, headers, payload = build_chat_request(
            cfg, [{"role": "user", "content": "hi"}]
        )
        self.assertEqual(url, "http://127.0.0.1:11434/v1/chat/completions")
        self.assertIn("max_tokens", payload)
        self.assertNotIn("max_completion_tokens", payload)
        self.assertNotIn("reasoning_effort", payload)
        self.assertNotIn("Authorization", headers)

    def test_xai_chat_payload(self) -> None:
        cfg = load_config(self.appdir)
        cfg.llm_api_key = "xai-abcdefghijklmnopqrstuvwxyz0123"
        url, headers, payload = build_chat_request(
            cfg, [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
        )
        self.assertEqual(url, "https://api.x.ai/v1/chat/completions")
        self.assertEqual(payload["model"], "grok-4.6")
        self.assertEqual(payload["max_completion_tokens"], cfg.llm.max_tokens)
        self.assertNotIn("max_tokens", payload)
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertNotIn("search_parameters", payload)
        self.assertEqual(payload["prompt_cache_key"], "desktopper-intent")
        self.assertEqual(headers["Authorization"], "Bearer " + cfg.llm_api_key)
        self.assertEqual(headers["x-grok-conv-id"], "desktopper-intent")
        self.assertNotIn(cfg.llm_api_key, str(payload))

    def test_redacts_xai_keys(self) -> None:
        secret = "xai-abcdefghijklmnopqrstuvwxyz0123"
        blob = redact_value({"msg": f"key={secret}"})
        self.assertNotIn(secret, str(blob))
        self.assertIn("[redacted]", blob["msg"])

    def test_public_error_includes_provider_body(self) -> None:
        exc = LlmError(
            "llm_down",
            "LLM HTTP 410.",
            '{"error":"Live search is deprecated."}',
        )
        msg = public_error_message(exc)
        self.assertIn("410", msg)
        self.assertIn("Live search is deprecated", msg)


if __name__ == "__main__":
    unittest.main()
