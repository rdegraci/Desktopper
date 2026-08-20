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


if __name__ == "__main__":
    unittest.main()
