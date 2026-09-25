from scripts.filter_transcripts import classify


def test_real_recipe_is_accepted():
    text = (
        "Hôm nay mình nấu món thịt kho trứng. "
        "Cho thịt vào chảo xào thơm rồi cho trứng vào. "
        "Nêm nước mắm, nước tương và gia vị. "
        "Tiếp tục kho đến khi thịt chín mềm. "
    ) * 8

    status, reason, _ = classify(text)

    assert status == "accepted"
    assert reason == "recipe_candidate"


def test_music_subscription_is_rejected():
    text = (
        "Hãy subscribe cho kênh để không bỏ lỡ video. "
        "Tình yêu trong giấc mơ, em đi qua mùa đông. "
        "Bài hát này có vài từ như canh, hấp, chiên nhưng không phải công thức. "
    ) * 5

    status, reason, _ = classify(text)

    assert status == "rejected"
    assert reason == "junk_or_subscription"


def test_long_text_with_only_three_recipe_signals_is_reviewed():
    filler = "đây là một đoạn nội dung nói chuyện không mô tả cách nấu " * 25
    text = filler + " canh hấp chiên"

    status, reason, _ = classify(text)

    assert status == "review"
    assert reason == "weak_recipe_signal"
