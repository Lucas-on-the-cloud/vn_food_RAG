from src.recommendation.ingredient_match import ingredient_coverage
from src.recommendation.recommender import recommend


def test_ingredient_coverage_ignores_optional_items():
    ingredients = [
        {"canonical_name_en": "egg", "optional": False},
        {"canonical_name_en": "pork_belly", "optional": False},
        {"canonical_name_en": "green_onion", "optional": True},
    ]

    result = ingredient_coverage(["egg"], ingredients)

    assert result["coverage"] == 0.5
    assert result["matched"] == ["egg"]
    assert result["missing"] == ["pork_belly"]


def test_recommend_filters_budget():
    recipes = [
        {
            "recipe_id": "1",
            "ingredients": [
                {"canonical_name_en": "egg", "optional": False}
            ],
            "estimated_cost_twd": 60,
            "cooking_time_minutes": 10,
        },
        {
            "recipe_id": "2",
            "ingredients": [
                {"canonical_name_en": "egg", "optional": False}
            ],
            "estimated_cost_twd": 150,
            "cooking_time_minutes": 10,
        },
    ]

    results = recommend(["egg"], recipes, max_budget_twd=100)

    assert [item["recipe_id"] for item in results] == ["1"]
