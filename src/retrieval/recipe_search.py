from __future__ import annotations


def lexical_search(query: str, recipes: list[dict], top_k: int = 5) -> list[dict]:
    """Simple dependency-free retrieval baseline.

    This intentionally comes before vector search so the project has
    a measurable baseline for later RAG experiments.
    """

    terms = {term.lower() for term in query.split() if term.strip()}
    scored = []

    for recipe in recipes:
        searchable = " ".join(
            [
                recipe.get("dish_name_vi", ""),
                recipe.get("dish_name_en", ""),
                " ".join(recipe.get("tags", [])),
                " ".join(
                    ingredient.get("name_vi", "")
                    for ingredient in recipe.get("ingredients", [])
                ),
                " ".join(
                    ingredient.get("canonical_name_en", "")
                    for ingredient in recipe.get("ingredients", [])
                ),
            ]
        ).lower()

        score = sum(1 for term in terms if term in searchable)
        if score:
            scored.append((score, recipe))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [recipe for _, recipe in scored[:top_k]]
