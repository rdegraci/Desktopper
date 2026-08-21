import unittest
from pathlib import Path


class Slice7AppJsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.src = Path("static/js/app.js").read_text(encoding="utf-8")
        self.html = Path("static/index.html").read_text(encoding="utf-8")

    def test_no_intent_or_eval(self) -> None:
        self.assertNotIn("/api/intent", self.src)
        self.assertNotIn("eval(", self.src)
        self.assertNotIn("innerHTML", self.src)
        self.assertNotIn("window.open", self.src)
        self.assertNotIn("alert(", self.src)

    def test_hash_routes_and_search(self) -> None:
        self.assertIn("#list/", self.src)
        self.assertIn("#form/", self.src)
        self.assertIn("nav !== false", self.src)
        self.assertIn("related", self.src)
        self.assertIn("app.home", self.src)
        self.assertIn("related-inline-form", self.src)
        self.assertIn("data-inline-related", self.src)
        self.assertIn("scope=", self.src)
        self.assertIn("screen.scopes", self.src)
        self.assertIn("field-group", self.src)
        self.assertIn("screen.groups", self.src)
        self.assertIn("empty-state", self.src)
        self.assertIn("listEmptyMessage", self.src)
        self.assertIn("relatedEmptyMessage", self.src)
        self.assertIn("/api/search", self.src)
        self.assertIn("300", self.src)
        self.assertIn("/api/tables/", self.src)
        self.assertIn("confirm-modal", self.src)

    def test_inline_related_create_stays_on_parent(self) -> None:
        self.assertIn("related-inline-form", self.src)
        self.assertIn("rel-", self.src)
        # Add must not navigate away to child form for create.
        self.assertNotIn(
            'go("#form/" + rel.table + "?" + encodeURIComponent(rel.fk)',
            self.src,
        )

    def test_belongs_to_parent_link(self) -> None:
        self.assertIn("belongs-to-link", self.src)
        self.assertIn("belongs-to-box", self.src)
        self.assertIn("drawBelongsTo", self.src)
        self.assertIn("belongsToEntries", self.src)

    def test_ops_is_html_link(self) -> None:
        self.assertIn('href="/ops"', self.html)
        self.assertIn('target="_blank"', self.html)
        self.assertNotIn("window.open", self.html)


if __name__ == "__main__":
    unittest.main()
