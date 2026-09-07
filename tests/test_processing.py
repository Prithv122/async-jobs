from asyncjobs.processing import analyze_content


def test_analyze_text_content() -> None:
    content = b"the quick brown fox\njumps over\nthe lazy dog"
    result = analyze_content(content)

    assert result["is_text"] is True
    assert result["byte_size"] == len(content)
    assert result["word_count"] == 9
    assert result["line_count"] == 3
    assert result["char_count"] == len(content.decode())
    assert len(result["sha256"]) == 64


def test_analyze_content_is_deterministic() -> None:
    content = b"same input, same hash"
    assert analyze_content(content)["sha256"] == analyze_content(content)["sha256"]


def test_analyze_binary_content_skips_text_stats() -> None:
    content = bytes(range(256))  # not valid UTF-8
    result = analyze_content(content)

    assert result["is_text"] is False
    assert result["byte_size"] == 256
    assert "word_count" not in result


def test_analyze_empty_content() -> None:
    result = analyze_content(b"")
    assert result["is_text"] is True
    assert result["word_count"] == 0
    assert result["line_count"] == 0
