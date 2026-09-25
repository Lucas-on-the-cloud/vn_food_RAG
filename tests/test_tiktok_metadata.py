from scripts.enrich_tiktok_metadata import (
    extract_video_id,
    score_relevance,
    strip_accents,
)


def test_strip_accents_vietnamese():
    assert strip_accents("Món ăn sinh viên dễ làm") == "mon an sinh vien de lam"


def test_extract_video_id():
    assert extract_video_id(
        "https://www.tiktok.com/@abc/video/1234567890"
    ) == "1234567890"


def test_recipe_relevance_high_for_student_recipe():
    score, label = score_relevance(
        "Cơm sinh viên: món trứng dễ làm trong 15 phút",
        "món ăn sinh viên",
    )

    assert score >= 4
    assert label == "high"


def test_recipe_relevance_penalizes_food_tour():
    _, label = score_relevance(
        "Food tour review quán buffet hot nhất tuần",
        "",
    )

    assert label == "low"
