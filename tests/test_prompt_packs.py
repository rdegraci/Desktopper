"""Tests for Ops prompt pack parsing and example loading."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.config import repo_root
from app.prompt_packs import (
    list_example_packs,
    load_example_pack,
    parse_prompt_pack,
    resolve_example_pack_path,
)
from app.server import create_app

TRACKER = repo_root() / "examples" / "Pivotal-Kanban-Tracker.md"


class ParsePromptPackTests(unittest.TestCase):
    def test_tracker_pack_shape(self) -> None:
        text = TRACKER.read_text(encoding="utf-8")
        pack = parse_prompt_pack(text, filename=TRACKER.name)
        self.assertEqual(pack["title"], "Ops prompts: Tracker-style app")
        self.assertEqual(len(pack["steps"]), 4)
        titles = [s["title"] for s in pack["steps"]]
        self.assertIn("Core model (tables + screens only)", titles[0])
        self.assertIn("List scopes", titles[1])
        self.assertIn("Board home", titles[2])
        self.assertIn("Optional polish", titles[3])
        self.assertFalse(pack["steps"][0]["optional"])
        self.assertFalse(pack["steps"][1]["optional"])
        self.assertFalse(pack["steps"][2]["optional"])
        self.assertTrue(pack["steps"][3]["optional"])
        self.assertIn("Build a lightweight Pivotal Tracker", pack["steps"][0]["intent"])
        self.assertIn("add scopes", pack["steps"][1]["intent"])
        self.assertNotIn("```", pack["steps"][0]["intent"])

    def test_step_heading_alias(self) -> None:
        md = (
            "# Demo pack\n\n"
            "## Step 1 — First\n\n"
            "```text\nDo the first thing.\n```\n\n"
            "## Step 2 — Second\n\n"
            "```\nDo the second thing.\n```\n"
        )
        pack = parse_prompt_pack(md)
        self.assertEqual(pack["title"], "Demo pack")
        self.assertEqual(len(pack["steps"]), 2)
        self.assertEqual(pack["steps"][0]["intent"], "Do the first thing.")
        self.assertEqual(pack["steps"][1]["intent"], "Do the second thing.")

    def test_title_from_filename_when_no_h1(self) -> None:
        md = "## Prompt 1 — Only step\n\n```text\nHello\n```\n"
        pack = parse_prompt_pack(md, filename="My-Cool-Pack.md")
        self.assertEqual(pack["title"], "My Cool Pack")
        self.assertEqual(len(pack["steps"]), 1)

    def test_optional_from_prose_outside_fence(self) -> None:
        md = (
            "# Pack\n\n"
            "## Prompt 1 — Polish\n\n"
            "This step is optional.\n\n"
            "```text\nPolish the form.\n```\n"
        )
        pack = parse_prompt_pack(md)
        self.assertTrue(pack["steps"][0]["optional"])

    def test_field_optional_in_intent_does_not_mark_step(self) -> None:
        md = (
            "# Pack\n\n"
            "## Prompt 1 — Core\n\n"
            "```text\nAdd name (optional text).\n```\n"
        )
        pack = parse_prompt_pack(md)
        self.assertFalse(pack["steps"][0]["optional"])


class ExamplePackPathTests(unittest.TestCase):
    def test_list_includes_tracker(self) -> None:
        packs = list_example_packs()
        names = [p["filename"] for p in packs]
        self.assertIn("Pivotal-Kanban-Tracker.md", names)
        tracker = next(p for p in packs if p["filename"] == "Pivotal-Kanban-Tracker.md")
        self.assertEqual(tracker["id"], "Pivotal-Kanban-Tracker")
        self.assertIn("Tracker", tracker["title"])

    def test_load_tracker_by_stem_and_filename(self) -> None:
        by_stem = load_example_pack("Pivotal-Kanban-Tracker")
        by_name = load_example_pack("Pivotal-Kanban-Tracker.md")
        self.assertIsNotNone(by_stem)
        self.assertIsNotNone(by_name)
        assert by_stem is not None and by_name is not None
        self.assertEqual(len(by_stem["steps"]), 4)
        self.assertEqual(by_stem["filename"], "Pivotal-Kanban-Tracker.md")
        self.assertEqual(by_stem["steps"][0]["intent"], by_name["steps"][0]["intent"])

    def test_reject_path_traversal(self) -> None:
        self.assertIsNone(resolve_example_pack_path("../README.md"))
        self.assertIsNone(resolve_example_pack_path("../../etc/passwd"))
        self.assertIsNone(resolve_example_pack_path("foo/bar.md"))
        self.assertIsNone(load_example_pack("../README.md"))

    def test_missing_pack(self) -> None:
        self.assertIsNone(load_example_pack("No-Such-Pack.md"))

    def test_list_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(list_example_packs(Path(tmp)), [])


class OpsPacksApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        self.client = create_app().test_client()

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_list_packs(self) -> None:
        res = self.client.get("/api/ops/packs")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertIn("packs", body)
        names = [p["filename"] for p in body["packs"]]
        self.assertIn("Pivotal-Kanban-Tracker.md", names)

    def test_get_tracker_pack(self) -> None:
        res = self.client.get("/api/ops/packs/Pivotal-Kanban-Tracker.md")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["filename"], "Pivotal-Kanban-Tracker.md")
        self.assertEqual(len(body["steps"]), 4)
        self.assertTrue(body["steps"][3]["optional"])
        self.assertIn("intent", body["steps"][0])

    def test_get_by_stem(self) -> None:
        res = self.client.get("/api/ops/packs/Pivotal-Kanban-Tracker")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.get_json()["steps"]), 4)

    def test_get_missing(self) -> None:
        res = self.client.get("/api/ops/packs/No-Such-Pack.md")
        self.assertEqual(res.status_code, 404)

    def test_get_path_traversal(self) -> None:
        res = self.client.get("/api/ops/packs/../README.md")
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
