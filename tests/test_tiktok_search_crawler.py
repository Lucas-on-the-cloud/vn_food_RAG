from scripts.crawl_tiktok_search import canonical_video_url, creator_from_url


def test_canonical_video_url_removes_query_and_fragment():
    url = (
        "https://www.tiktok.com/@food.creator/video/1234567890"
        "?is_from_webapp=1#abc"
    )

    assert canonical_video_url(url) == (
        "https://www.tiktok.com/@food.creator/video/1234567890"
    )


def test_canonical_video_url_accepts_relative_video_path():
    assert canonical_video_url("/@abc/video/987654321") == (
        "https://www.tiktok.com/@abc/video/987654321"
    )


def test_non_video_url_returns_none():
    assert canonical_video_url("https://www.tiktok.com/search?q=food") is None


def test_creator_from_url():
    assert creator_from_url(
        "https://www.tiktok.com/@student_food/video/123"
    ) == "student_food"
