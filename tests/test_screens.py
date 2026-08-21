import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_config, read_or_create_schema
from app.engine import apply_diff
from app.log import setup_logging
from app.schema_validate import ValidationError
from app.server import create_app


RECIPES = {
    "summary": "Recipes and ingredients.",
    "app": {"title": "Wok Recipes", "home": "recipes_list"},
    "add_tables": [
        {
            "name": "recipes",
            "label": "Recipes",
            "columns": [
                {
                    "name": "title",
                    "type": "TEXT",
                    "label": "Title",
                    "nullable": False,
                    "widget": "text",
                }
            ],
        },
        {
            "name": "ingredients",
            "label": "Ingredients",
            "columns": [
                {
                    "name": "name",
                    "type": "TEXT",
                    "label": "Name",
                    "nullable": False,
                    "widget": "text",
                }
            ],
        },
        {
            "name": "recipe_ingredients",
            "label": "Recipe ingredients",
            "columns": [
                {
                    "name": "recipe_id",
                    "type": "INTEGER",
                    "label": "Recipe",
                    "nullable": False,
                    "widget": "fk",
                    "fk": {"table": "recipes", "column": "id", "display": "title"},
                },
                {
                    "name": "ingredient_id",
                    "type": "INTEGER",
                    "label": "Ingredient",
                    "nullable": False,
                    "widget": "fk",
                    "fk": {
                        "table": "ingredients",
                        "column": "id",
                        "display": "name",
                    },
                },
                {
                    "name": "quantity",
                    "type": "TEXT",
                    "label": "Quantity",
                    "nullable": True,
                    "widget": "text",
                },
            ],
        },
    ],
    "add_screens": [
        {
            "id": "recipes_list",
            "type": "list",
            "table": "recipes",
            "title": "Recipes",
            "columns": ["title"],
        },
        {
            "id": "recipes_form",
            "type": "form",
            "table": "recipes",
            "title": "Recipe",
            "related": [
                {
                    "table": "recipe_ingredients",
                    "fk": "recipe_id",
                    "title": "Ingredients",
                    "columns": ["ingredient_id", "quantity"],
                }
            ],
        },
        {
            "id": "ingredients_list",
            "type": "list",
            "table": "ingredients",
            "title": "Ingredients",
            "columns": ["name"],
        },
        {
            "id": "ingredients_form",
            "type": "form",
            "table": "ingredients",
            "title": "Ingredient",
        },
        {
            "id": "recipe_ingredients_list",
            "type": "list",
            "table": "recipe_ingredients",
            "title": "Recipe ingredients",
            "columns": ["recipe_id", "ingredient_id", "quantity"],
            "nav": False,
        },
        {
            "id": "recipe_ingredients_form",
            "type": "form",
            "table": "recipe_ingredients",
            "title": "Recipe ingredient",
        },
    ],
}


class ScreenLanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        self.cfg = load_config(self.appdir)
        setup_logging(self.cfg)

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_related_and_nav_and_home(self) -> None:
        schema = apply_diff(self.cfg, RECIPES)
        self.assertEqual(schema["app"]["home"], "recipes_list")
        form = [s for s in schema["screens"] if s["id"] == "recipes_form"][0]
        self.assertEqual(form["related"][0]["fk"], "recipe_id")
        join_list = [s for s in schema["screens"] if s["id"] == "recipe_ingredients_list"][0]
        self.assertIs(join_list["nav"], False)

    def test_update_screens_attaches_related(self) -> None:
        slim = {
            "summary": "Recipes only.",
            "add_tables": [RECIPES["add_tables"][0]],
            "add_screens": [
                {
                    "id": "recipes_list",
                    "type": "list",
                    "table": "recipes",
                    "title": "Recipes",
                    "columns": ["title"],
                },
                {
                    "id": "recipes_form",
                    "type": "form",
                    "table": "recipes",
                    "title": "Recipe",
                },
            ],
        }
        apply_diff(self.cfg, slim)
        apply_diff(
            self.cfg,
            {
                "summary": "Add ingredients catalog and lines.",
                "add_tables": RECIPES["add_tables"][1:],
                "add_screens": [
                    s
                    for s in RECIPES["add_screens"]
                    if s["id"] not in ("recipes_list", "recipes_form")
                ],
                "update_screens": [
                    {
                        "id": "recipes_form",
                        "related": RECIPES["add_screens"][1]["related"],
                    },
                    {"id": "recipe_ingredients_list", "nav": False},
                ],
            },
        )
        schema = read_or_create_schema(self.appdir)
        form = [s for s in schema["screens"] if s["id"] == "recipes_form"][0]
        self.assertEqual(form["related"][0]["table"], "recipe_ingredients")

    def test_related_must_point_at_form_table(self) -> None:
        apply_diff(self.cfg, RECIPES)
        with self.assertRaises(ValidationError) as ctx:
            apply_diff(
                self.cfg,
                {
                    "summary": "Bad related.",
                    "update_screens": [
                        {
                            "id": "ingredients_form",
                            "related": [
                                {
                                    "table": "recipe_ingredients",
                                    "fk": "recipe_id",
                                    "title": "Nope",
                                    "columns": ["quantity"],
                                }
                            ],
                        }
                    ],
                },
            )
        self.assertEqual(ctx.exception.error_code, "bad_name")

    def test_list_filters_by_fk(self) -> None:
        apply_diff(self.cfg, RECIPES)
        client = create_app().test_client()
        recipe = client.post("/api/tables/recipes", json={"title": "Fried rice"}).get_json()
        other = client.post("/api/tables/recipes", json={"title": "Soup"}).get_json()
        ing = client.post("/api/tables/ingredients", json={"name": "Rice"}).get_json()
        client.post(
            "/api/tables/recipe_ingredients",
            json={
                "recipe_id": recipe["id"],
                "ingredient_id": ing["id"],
                "quantity": "1 cup",
            },
        )
        client.post(
            "/api/tables/recipe_ingredients",
            json={
                "recipe_id": other["id"],
                "ingredient_id": ing["id"],
                "quantity": "2 cups",
            },
        )
        listed = client.get(
            "/api/tables/recipe_ingredients?recipe_id=" + str(recipe["id"])
        )
        self.assertEqual(listed.status_code, 200)
        rows = listed.get_json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["quantity"], "1 cup")
        bad = client.get("/api/tables/recipe_ingredients?title=nope")
        self.assertEqual(bad.status_code, 400)

    def test_list_scopes_filter_select(self) -> None:
        apply_diff(
            self.cfg,
            {
                "summary": "Tasks with status scopes.",
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
                "add_screens": [
                    {
                        "id": "tasks_list",
                        "type": "list",
                        "table": "tasks",
                        "title": "Tasks",
                        "columns": ["title", "status"],
                        "scopes": [
                            {
                                "id": "open",
                                "label": "Open",
                                "column": "status",
                                "value": "open",
                            },
                            {
                                "id": "done",
                                "label": "Done",
                                "column": "status",
                                "value": "done",
                            },
                        ],
                    },
                    {
                        "id": "tasks_form",
                        "type": "form",
                        "table": "tasks",
                        "title": "Task",
                    },
                ],
            },
        )
        schema = read_or_create_schema(self.appdir)
        scopes = [s for s in schema["screens"] if s["id"] == "tasks_list"][0]["scopes"]
        self.assertEqual(len(scopes), 2)
        client = create_app().test_client()
        client.post("/api/tables/tasks", json={"title": "Cook", "status": "open"})
        client.post("/api/tables/tasks", json={"title": "Clean", "status": "done"})
        open_rows = client.get("/api/tables/tasks?status=open").get_json()
        self.assertEqual(len(open_rows), 1)
        self.assertEqual(open_rows[0]["title"], "Cook")
        done_rows = client.get("/api/tables/tasks?status=done").get_json()
        self.assertEqual(len(done_rows), 1)
        self.assertEqual(done_rows[0]["title"], "Clean")

    def test_scopes_rejected_on_form(self) -> None:
        apply_diff(self.cfg, RECIPES)
        with self.assertRaises(ValidationError) as ctx:
            apply_diff(
                self.cfg,
                {
                    "summary": "Bad scopes.",
                    "update_screens": [
                        {
                            "id": "recipes_form",
                            "scopes": [
                                {
                                    "id": "all",
                                    "label": "All",
                                }
                            ],
                        }
                    ],
                },
            )
        self.assertEqual(ctx.exception.error_code, "bad_name")

    def test_form_groups(self) -> None:
        apply_diff(
            self.cfg,
            {
                "summary": "Contacts with grouped form.",
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
                        "columns": ["name"],
                    },
                    {
                        "id": "contacts_form",
                        "type": "form",
                        "table": "contacts",
                        "title": "Contact",
                        "groups": [
                            {
                                "id": "basics",
                                "label": "Basics",
                                "columns": ["name", "email"],
                            },
                            {
                                "id": "notes",
                                "label": "Notes",
                                "columns": ["notes"],
                            },
                        ],
                    },
                ],
            },
        )
        schema = read_or_create_schema(self.appdir)
        form = [s for s in schema["screens"] if s["id"] == "contacts_form"][0]
        self.assertEqual(len(form["groups"]), 2)
        self.assertEqual(form["groups"][0]["columns"], ["name", "email"])

    def test_groups_rejected_on_list(self) -> None:
        apply_diff(self.cfg, RECIPES)
        with self.assertRaises(ValidationError) as ctx:
            apply_diff(
                self.cfg,
                {
                    "summary": "Bad groups.",
                    "update_screens": [
                        {
                            "id": "recipes_list",
                            "groups": [
                                {
                                    "id": "basics",
                                    "label": "Basics",
                                    "columns": ["title"],
                                }
                            ],
                        }
                    ],
                },
            )
        self.assertEqual(ctx.exception.error_code, "bad_name")


if __name__ == "__main__":
    unittest.main()
