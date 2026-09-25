from scripts.crawl_saveto_playwright import (
    extract_completed_transcript,
    response_error,
)


def test_extract_completed_transcript():
    body = {
        "code": 200,
        "data": {
            "status": 2,
            "data": [
                {"text": "Bắt cái chảo lên dầu", "start": 1.0, "dur": 1.2},
                {"text": "Cho hành vào phi thơm", "start": 2.2, "dur": 1.0},
            ],
        },
    }

    result = extract_completed_transcript(body)

    assert result is not None
    assert result["status"] == 2
    assert result["text"] == (
        "Bắt cái chảo lên dầu\nCho hành vào phi thơm"
    )


def test_pending_response_is_not_completed():
    body = {
        "code": 200,
        "data": {
            "status": 1,
            "data": [],
        },
    }

    assert extract_completed_transcript(body) is None


def test_response_error():
    assert response_error({"code": 637, "message": "quota"}) == (
        "code=637: quota"
    )
    assert response_error({"code": 200, "data": {}}) is None
