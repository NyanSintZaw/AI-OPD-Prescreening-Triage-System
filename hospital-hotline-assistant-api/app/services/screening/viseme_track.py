"""Text → vowel (viseme) timeline for avatar lip sync.

Google Cloud TTS exposes no phoneme timings, so the kiosk avatar's mouth
is driven karaoke-style instead: the reply TEXT is scanned for vowels
(best-effort grapheme mapping, Thai + English), the resulting sequence is
spread proportionally across the synthesized audio's duration, and the
timeline ships to the browser with the audio (``viseme_track`` WS frame).
The avatar snaps its mouth shape to the scheduled vowel while playback
loudness keeps controlling how far the mouth opens — approximate, but a
dramatic improvement over guessing vowels from the audio spectrum, and
with zero extra latency or API cost.

Viseme names follow VRM expression presets: aa / ih / ou / ee / oh, plus
``sil`` for the closed-mouth rest between words.
"""

from __future__ import annotations

import re

__all__ = ["build_viseme_track"]

# Fraction of each word's time slice reserved as a closed-mouth gap
# before the next word.
_WORD_GAP_FRAC = 0.15
# Guard against pathological outputs on very long replies — beyond this
# many entries the mouth flickers faster than anyone can perceive anyway.
_MAX_ENTRIES = 400

# English digraphs checked before single letters (first match wins).
_EN_DIGRAPHS: list[tuple[str, str]] = [
    ("oo", "ou"),
    ("ou", "ou"),
    ("ow", "ou"),
    ("ee", "ee"),
    ("ea", "ee"),
    ("ai", "ee"),
    ("ay", "ee"),
    ("ei", "ee"),
    ("ey", "ee"),
    ("oa", "oh"),
    ("au", "oh"),
    ("aw", "oh"),
    ("oi", "oh"),
    ("oy", "oh"),
]
_EN_SINGLES = {
    "a": "aa",
    "e": "ee",
    "i": "ih",
    "o": "oh",
    "u": "ou",
    "y": "ih",
}

# Thai vowel characters → viseme (position in the syllable is ignored —
# the mouth only needs the right shape roughly at the right time).
_TH_VOWELS = {
    "ะ": "aa",  # ะ
    "ั": "aa",  # ั
    "า": "aa",  # า
    "ำ": "aa",  # ำ
    "ิ": "ih",  # ิ
    "ี": "ih",  # ี
    "ึ": "ou",  # ึ
    "ื": "ou",  # ื
    "ุ": "ou",  # ุ
    "ู": "ou",  # ู
    "เ": "ee",  # เ
    "แ": "ee",  # แ
    "โ": "oh",  # โ
    "ไ": "aa",  # ไ
    "ใ": "aa",  # ใ
}


def _word_vowels(word: str) -> list[str]:
    """Best-effort vowel viseme sequence for one word (mixed script ok)."""
    out: list[str] = []
    lowered = word.lower()
    i = 0
    n = len(lowered)
    while i < n:
        ch = lowered[i]
        # Thai vowel marks (combining or leading).
        v = _TH_VOWELS.get(ch)
        if v is not None:
            out.append(v)
            i += 1
            continue
        if "a" <= ch <= "z":
            matched = False
            for digraph, dv in _EN_DIGRAPHS:
                if lowered.startswith(digraph, i):
                    out.append(dv)
                    i += len(digraph)
                    matched = True
                    break
            if matched:
                continue
            sv = _EN_SINGLES.get(ch)
            # Leading "y" is a consonant ("you"); elsewhere it's a vowel.
            if sv is not None and not (ch == "y" and i == 0):
                out.append(sv)
        i += 1
    return out


def build_viseme_track(
    text: str, duration_s: float, language: str = "th"
) -> list[dict]:
    """Spread the text's vowel sequence across ``duration_s`` seconds.

    Returns ``[{"t": seconds_from_audio_start, "v": viseme}, ...]`` sorted
    by time, always ending with a ``sil`` entry. ``language`` is accepted
    for future refinement but the scanner handles mixed Thai/English text
    regardless.
    """
    del language  # mixed-script scanning needs no language switch today
    duration_s = max(0.0, float(duration_s))
    words = [w for w in re.split(r"[\s​,.!?;:()\"'…ๆฯ]+", text or "") if w]
    per_word = [(w, _word_vowels(w)) for w in words]
    per_word = [(w, vs) for w, vs in per_word if vs]
    total_vowels = sum(len(vs) for _, vs in per_word)
    if total_vowels == 0 or duration_s <= 0:
        return [{"t": 0.0, "v": "sil"}]

    # Thin very long sequences evenly rather than truncating the tail.
    if total_vowels > _MAX_ENTRIES:
        keep_every = total_vowels / _MAX_ENTRIES
        thinned: list[tuple[str, list[str]]] = []
        counter = 0.0
        for w, vs in per_word:
            kept: list[str] = []
            for v in vs:
                counter += 1
                if counter >= keep_every:
                    counter -= keep_every
                    kept.append(v)
            if kept:
                thinned.append((w, kept))
        per_word = thinned
        total_vowels = sum(len(vs) for _, vs in per_word)

    track: list[dict] = []
    cursor = 0.0
    for _, vowels in per_word:
        word_span = duration_s * (len(vowels) / total_vowels)
        speak_span = word_span * (1 - _WORD_GAP_FRAC)
        step = speak_span / len(vowels)
        for j, v in enumerate(vowels):
            track.append({"t": round(cursor + j * step, 3), "v": v})
        # Closed-mouth beat in the gap before the next word.
        track.append({"t": round(cursor + speak_span, 3), "v": "sil"})
        cursor += word_span
    # Ensure the track closes the mouth exactly at the end.
    if track[-1]["t"] < duration_s:
        track.append({"t": round(duration_s, 3), "v": "sil"})
    return track
