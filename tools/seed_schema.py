"""Apply a demo contacts schema if the appdir schema is empty.

Run: python3 tools/seed_schema.py
Then refresh Safari on http://127.0.0.1:8000/
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_config, read_or_create_schema
from app.engine import apply_diff
from app.log import setup_logging

DIFF = {
    "summary": "Demo contacts list.",
    "app": {"title": "Rolodex"},
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
                    "name": "email",
                    "type": "TEXT",
                    "label": "Email",
                    "nullable": True,
                    "widget": "text",
                },
                {
                    "name": "notes",
                    "type": "TEXT",
                    "label": "Notes",
                    "nullable": True,
                    "widget": "textarea",
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
            "columns": ["name", "email"],
        },
        {
            "id": "contacts_form",
            "type": "form",
            "table": "contacts",
            "title": "Contact",
        },
    ],
}


def main() -> int:
    cfg = load_config()
    setup_logging(cfg)
    schema = read_or_create_schema(cfg.appdir)
    if schema.get("tables"):
        print("Schema already has tables. Refresh Safari.")
        return 0
    apply_diff(cfg, DIFF)
    print("Seeded contacts. Open http://127.0.0.1:8000/ and refresh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
