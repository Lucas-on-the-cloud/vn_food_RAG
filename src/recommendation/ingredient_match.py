from __future__ import annotations


def ingredient_coverage(
    available_ingredients: list[str],
    recipe_ingredients: list[dict],
) -> dict:
    """Calculate ingredient coverage for a recipe.

    Optional ingredients do not reduce the coverage score.
    """

    available = {item.strip().lower() for item in available_ingredients}

    required = {
        item["canonical_name_en"].strip().lower()
        for item in recipe_ingredients
        if not item.get("optional", False)
    }

    if not required:
        return {
            "coverage": 1.0,
            "matched": [],
            "missing": [],
        }

    matched = sorted(required & available)
    missing = sorted(required - available)

    return {
        "coverage": len(matched) / len(required),
        "matched": matched,
        "missing": missing,
    }
