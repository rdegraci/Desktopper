import json
import tempfile
import unittest
from pathlib import Path

from app.config import read_or_create_schema, schema_path


class SchemaDedupeTests(unittest.TestCase):
    def test_duplicate_columns_deduped_on_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            appdir = Path(tmp)
            path = schema_path(appdir)
            col = {
                "name": "lives_online",
                "type": "INTEGER",
                "label": "Lives online",
                "nullable": True,
                "widget": "checkbox",
            }
            payload = {
                "version": 1,
                "app": {"title": "Test"},
                "tables": {
                    "repos": {
                        "name": "repos",
                        "label": "Repos",
                        "columns": [col, dict(col)],
                    }
                },
                "screens": [],
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            loaded = read_or_create_schema(appdir)
            names = [c["name"] for c in loaded["tables"]["repos"]["columns"]]
            self.assertEqual(names.count("lives_online"), 1)

            on_disk = json.loads(path.read_text(encoding="utf-8"))
            disk_names = [c["name"] for c in on_disk["tables"]["repos"]["columns"]]
            self.assertEqual(disk_names.count("lives_online"), 1)


if __name__ == "__main__":
    unittest.main()
