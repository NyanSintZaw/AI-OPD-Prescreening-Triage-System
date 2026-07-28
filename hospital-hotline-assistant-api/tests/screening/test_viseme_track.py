"""Unit tests for the text → viseme timeline builder."""

from app.services.screening.viseme_track import build_viseme_track


def _shapes(track: list[dict]) -> list[str]:
    return [e["v"] for e in track if e["v"] != "sil"]


def test_hello_produces_ee_then_oh() -> None:
    track = build_viseme_track("Hello", 1.0, "en")
    assert _shapes(track) == ["ee", "oh"]
    # Sorted times, ends closed.
    times = [e["t"] for e in track]
    assert times == sorted(times)
    assert track[-1]["v"] == "sil"
    assert track[-1]["t"] <= 1.0


def test_multi_word_english_has_word_gaps() -> None:
    track = build_viseme_track("How are you today", 2.0, "en")
    sils = [e for e in track if e["v"] == "sil"]
    assert len(sils) >= 4  # one gap per word incl. the final close
    assert all(0 <= e["t"] <= 2.0 for e in track)


def test_thai_greeting_maps_vowels() -> None:
    # สวัสดีค่ะ → ั(aa) ี(ih) + ค่ะ ะ(aa)
    track = build_viseme_track("สวัสดีค่ะ", 1.2, "th")
    shapes = _shapes(track)
    assert "aa" in shapes and "ih" in shapes
    assert track[-1]["v"] == "sil"


def test_empty_and_vowelless_text_returns_rest() -> None:
    assert build_viseme_track("", 1.0, "en") == [{"t": 0.0, "v": "sil"}]
    assert build_viseme_track("!!! ???", 1.0, "en") == [{"t": 0.0, "v": "sil"}]


def test_zero_duration_returns_rest() -> None:
    assert build_viseme_track("Hello", 0.0, "en") == [{"t": 0.0, "v": "sil"}]


def test_long_text_is_thinned_not_truncated() -> None:
    text = "hello " * 500  # 1000 vowels unthinned
    track = build_viseme_track(text, 30.0, "en")
    non_sil = _shapes(track)
    assert len(non_sil) <= 400
    # Coverage should still span (almost) the whole duration, proving the
    # tail wasn't chopped off.
    assert track[-1]["t"] >= 29.0


def test_mixed_thai_english() -> None:
    track = build_viseme_track("OPD อยู่ชั้น 2 ค่ะ", 1.5, "th")
    shapes = _shapes(track)
    assert len(shapes) >= 3
    assert set(shapes) <= {"aa", "ih", "ou", "ee", "oh"}
