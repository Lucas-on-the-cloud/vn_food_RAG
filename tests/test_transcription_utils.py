from scripts.transcribe_tiktok_sources import (
    choose_subtitle_track,
    clean_subtitle_text,
    language_rank,
    parse_json_subtitle,
)


def test_clean_vtt_text():
    raw = """WEBVTT

00:00:00.000 --> 00:00:02.000
Hôm nay mình nấu cơm.

00:00:02.000 --> 00:00:04.000
Cho trứng vào chảo.
"""

    assert clean_subtitle_text(raw) == (
        "Hôm nay mình nấu cơm. Cho trứng vào chảo."
    )


def test_choose_vietnamese_subtitle():
    info = {
        "subtitles": {
            "en": [{"ext": "vtt", "data": "English"}],
            "vi-VN": [{"ext": "vtt", "data": "Tiếng Việt"}],
        }
    }

    language, track = choose_subtitle_track(info)

    assert language == "vi-VN"
    assert track["data"] == "Tiếng Việt"


def test_language_rank_prefers_vi():
    assert language_rank("vi-VN") > language_rank("en")


def test_parse_json_caption():
    raw = """{
      "utterances": [
        {"start_time": 0, "end_time": 1500, "text": "Xin chào"},
        {"start_time": 1500, "end_time": 3000, "text": "Hôm nay mình nấu ăn"}
      ]
    }"""

    text, segments = parse_json_subtitle(raw)

    assert text == "Xin chào Hôm nay mình nấu ăn"
    assert len(segments) == 2
    assert segments[1]["start"] == 1.5
