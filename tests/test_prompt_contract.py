import copy
import unittest

from app.config import EMPTY_SCHEMA
from app.schema_validate import ALLOWED_DIFF_KEYS, validate_diff
from app.system_prompt import FINAL_SYSTEM_PROMPT, PROMPT_DIFF_KEYS


class PromptContractTests(unittest.TestCase):
    def test_prompt_keys_subset_of_validator(self) -> None:
        self.assertTrue(PROMPT_DIFF_KEYS <= ALLOWED_DIFF_KEYS)

    def test_validator_keys_documented_in_prompt(self) -> None:
        missing = ALLOWED_DIFF_KEYS - PROMPT_DIFF_KEYS
        self.assertEqual(
            missing,
            set(),
            f"ALLOWED_DIFF_KEYS not in prompt output object: {sorted(missing)}",
        )

    def test_prompt_lists_each_allowed_key(self) -> None:
        for key in sorted(ALLOWED_DIFF_KEYS):
            self.assertIn(f'"{key}"', FINAL_SYSTEM_PROMPT)

    def test_golden_add_columns_nested_shape(self) -> None:
        schema = copy.deepcopy(EMPTY_SCHEMA)
        validate_diff(
            schema,
            {
                "summary": "Add phone.",
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
                            }
                        ],
                    }
                ],
                "add_columns": [
                    {
                        "table": "contacts",
                        "column": {
                            "name": "phone",
                            "type": "TEXT",
                            "label": "Phone",
                            "nullable": True,
                            "widget": "text",
                        },
                    }
                ],
            },
        )

    def test_golden_layout_screen_and_layout(self) -> None:
        schema = copy.deepcopy(EMPTY_SCHEMA)
        validate_diff(
            schema,
            {
                "summary": "Board.",
                "add_tables": [
                    {
                        "name": "tasks",
                        "label": "Tasks",
                        "columns": [
                            {
                                "name": "title",
                                "type": "TEXT",
                                "label": "Title",
                                "nullable": False,
                                "widget": "text",
                            },
                            {
                                "name": "status",
                                "type": "TEXT",
                                "label": "Status",
                                "nullable": False,
                                "widget": "select",
                                "enum": ["open", "done"],
                            },
                        ],
                    }
                ],
                "add_layouts": [
                    {
                        "id": "week_board",
                        "title": "This week",
                        "rows": [
                            {
                                "cols": [
                                    {
                                        "span": 12,
                                        "widget": "kanban",
                                        "table": "tasks",
                                        "column": "status",
                                        "title_column": "title",
                                    }
                                ]
                            }
                        ],
                    }
                ],
                "add_screens": [
                    {
                        "id": "week_board_screen",
                        "type": "layout",
                        "layout_id": "week_board",
                        "title": "This week",
                    }
                ],
            },
        )

    def test_golden_hide_and_remove_columns(self) -> None:
        schema = copy.deepcopy(EMPTY_SCHEMA)
        schema["tables"] = {
            "repos": {
                "name": "repos",
                "label": "Repos",
                "columns": [
                    {
                        "name": "name",
                        "type": "TEXT",
                        "label": "Name",
                        "nullable": False,
                        "widget": "text",
                    },
                    {
                        "name": "url",
                        "type": "TEXT",
                        "label": "URL",
                        "nullable": True,
                        "widget": "text",
                    },
                    {
                        "name": "old_note",
                        "type": "TEXT",
                        "label": "Old note",
                        "nullable": True,
                        "widget": "text",
                    },
                ],
            }
        }
        validate_diff(
            schema,
            {
                "summary": "Hide URL and remove old note.",
                "hide_columns": [{"table": "repos", "column": "url"}],
                "remove_columns": [{"table": "repos", "column": "old_note"}],
            },
        )


if __name__ == "__main__":
    unittest.main()
