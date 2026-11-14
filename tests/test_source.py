import json

from app.source import parse_json3


def _write(tmp_path, events):
    p = tmp_path / "subs.json3"
    p.write_text(json.dumps({"events": events}), encoding="utf-8")
    return p


def test_auto_captions_use_per_word_offsets(tmp_path):
    p = _write(tmp_path, [
        {"tStartMs": 1000, "dDurationMs": 2000,
         "segs": [{"utf8": "hello"}, {"utf8": " big", "tOffsetMs": 400}, {"utf8": " world", "tOffsetMs": 900}]},
    ])
    words = parse_json3(p)
    assert [w.text for w in words] == ["hello", "big", "world"]
    assert [round(w.start, 2) for w in words] == [1.0, 1.4, 1.9]


def test_manual_caption_line_is_spread_evenly(tmp_path):
    p = _write(tmp_path, [{"tStartMs": 0, "dDurationMs": 3000, "segs": [{"utf8": "one two three"}]}])
    words = parse_json3(p)
    assert [w.text for w in words] == ["one", "two", "three"]
    assert [round(w.start, 2) for w in words] == [0.0, 1.0, 2.0]


def test_noise_tags_and_speaker_arrows_are_dropped(tmp_path):
    p = _write(tmp_path, [
        {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "[Music]"}]},
        {"tStartMs": 1000, "dDurationMs": 1000, "segs": [{"utf8": ">> hi"}, {"utf8": " there", "tOffsetMs": 300}]},
    ])
    assert [w.text for w in parse_json3(p)] == ["hi", "there"]


def test_word_ends_are_capped_and_ordered(tmp_path):
    p = _write(tmp_path, [
        {"tStartMs": 0, "dDurationMs": 10000, "segs": [{"utf8": "a"}, {"utf8": " b", "tOffsetMs": 5000}]},
    ])
    a, b = parse_json3(p)
    assert a.end <= a.start + 0.9  # a word before a long pause doesn't linger
    assert a.end <= b.start


def test_events_without_text_are_ignored(tmp_path):
    p = _write(tmp_path, [{"tStartMs": 0, "dDurationMs": 500}, {"tStartMs": 500, "segs": [{"utf8": "\n"}]}])
    assert parse_json3(p) == []
