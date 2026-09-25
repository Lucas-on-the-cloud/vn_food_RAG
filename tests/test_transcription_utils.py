from scripts.transcribe_tiktok_sources import (
    choose_media_url,
    extract_video_id,
    is_http_media_url,
    looks_like_media,
)


def test_extract_video_id():
    assert extract_video_id(
        "https://www.tiktok.com/@abc/video/1234567890"
    ) == "1234567890"


def test_http_media_detection():
    assert is_http_media_url("https://v16.tiktokcdn.com/video/test.mp4")
    assert not is_http_media_url("blob:https://www.tiktok.com/abc")


def test_looks_like_video_response():
    assert looks_like_media(
        "https://example.com/file",
        "video/mp4",
    )


def test_current_src_is_preferred():
    current = "https://v16.tiktokcdn.com/video/current.mp4"
    captured = [
        {
            "url": "https://v16.tiktokcdn.com/video/other.mp4",
            "content_type": "video/mp4",
        }
    ]

    assert choose_media_url(current, captured) == current


def test_blob_src_falls_back_to_captured_video():
    captured_url = "https://v16.tiktokcdn.com/video/stream.mp4"

    assert choose_media_url(
        "blob:https://www.tiktok.com/abc",
        [
            {
                "url": captured_url,
                "content_type": "video/mp4",
            }
        ],
    ) == captured_url
