from __future__ import annotations

import json
from pathlib import Path

from .ingredient_match import ingredient_coverage


def load_recipes(path: str | Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def recommend(
    available_ingredients: list[str],
    recipes: list[dict],
    max_cooking_time: int | None = None,
    max_budget_twd: float | None = None,
    top_k: int = 5,
) -> list[dict]:
    """Return recipes ranked by required-ingredient coverage."""

    results = []

    for recipe in recipes:
        if (
            max_cooking_time is not None
            and recipe.get("cooking_time_minutes") is not None
            and recipe["cooking_time_minutes"] > max_cooking_time
        ):
            continue

        if (
            max_budget_twd is not None
            and recipe.get("estimated_cost_twd") is not None
            and recipe["estimated_cost_twd"] > max_budget_twd
        ):
            continue

        match = ingredient_coverage(
            available_ingredients,
            recipe.get("ingredients", []),
        )

        result = {
            **recipe,
            "ingredient_coverage": round(match["coverage"], 4),
            "matched_ingredients": match["matched"],
            "missing_ingredients": match["missing"],
        }
        results.append(result)

    results.sort(
        key=lambda item: (
            item["ingredient_coverage"],
            -len(item["missing_ingredients"]),
        ),
        reverse=True,
    )

    return results[:top_k]
