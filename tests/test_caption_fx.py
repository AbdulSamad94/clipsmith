from app import captions_fx as fx
from app import render
from app.source import Word


def _caps(ass: str) -> list[str]:
    return [ln.split(",Cap,,0,0,0,,", 1)[1] for ln in ass.splitlines() if ln.startswith("Dialogue: 0,")]


# ---------- keyword picking (pure, no AI) ----------

def test_numbers_are_keywords():
    assert fx.pick_keywords(["I", "made", "$10,000"]) == [2]
    assert fx.pick_keywords(["only", "3", "steps"]) == [1]


def test_emphasis_words_beat_plain_words():
    assert fx.pick_keywords(["this", "is", "insane"]) == [2]


def test_long_rare_words_count_but_stopwords_never_do():
    assert fx.pick_keywords(["the", "algorithm", "is"]) == [1]
    assert fx.pick_keywords(["and", "the", "of"]) == []
    assert fx.pick_keywords(["because", "something", "everyone"]) == []


def test_short_plain_words_are_not_highlighted():
    assert fx.pick_keywords(["go", "now", "ok"]) == []


def test_at_most_max_n_and_in_reading_order():
    assert fx.pick_keywords(["never", "spend", "$500", "on", "furniture"], max_n=2) == [0, 2]
    assert fx.pick_keywords(["never", "$5", "insane"], max_n=1) == [1]


def test_punctuation_is_ignored_when_scoring():
    assert fx.pick_keywords(["really?", "SECRET!", "is"]) == [1]


def test_emoji_lookup_is_local_and_case_insensitive():
    assert fx.emoji_for("Money!") == fx.EMOJI["money"]
    assert fx.emoji_for("table") is None


def test_key_colour_differs_from_active_colour():
    for st in render.STYLES.values():
        assert fx.key_colour(st["active"]) != st["active"]


# ---------- build_ass integration ----------

WORDS = [Word("this", 0, 0.3), Word("is", 0.3, 0.6), Word("insane", 0.6, 0.9)]


def test_default_output_has_no_keyword_effects():
    caps = _caps(render.build_ass(WORDS, 0, 5, "yellow", None))
    key = fx.key_colour(render.STYLES["yellow"]["active"])
    assert not any(key in c for c in caps)
    assert caps[0].startswith("{\\fscx86\\fscy86\\t(0,90,\\fscx100\\fscy100)}")
    assert "\\t(" not in caps[1] and "\\t(" not in caps[2]


def test_highlight_colours_keyword_on_every_line_of_its_group():
    key = fx.key_colour(render.STYLES["yellow"]["active"])
    caps = _caps(render.build_ass(WORDS, 0, 5, "yellow", None, highlight=True))
    assert len(caps) == 3
    assert all(f"\\c{key}" in c and "INSANE" in c for c in caps[:2])


def test_highlight_pops_each_word_in():
    caps = _caps(render.build_ass(WORDS, 0, 5, "yellow", None, highlight=True))
    assert all("\\t(0," in c for c in caps)


def test_emoji_added_only_when_enabled():
    words = [Word("make", 0, 0.3), Word("money", 0.3, 0.6)]
    e = fx.EMOJI["money"]
    assert not any(e in c for c in _caps(render.build_ass(words, 0, 5, "yellow", None, highlight=True)))
    assert any(e in c for c in _caps(render.build_ass(words, 0, 5, "yellow", None, highlight=True, emoji=True)))


def test_job_request_options_are_off_by_default():
    from app.main import JobRequest
    req = JobRequest(url="x")
    assert req.highlight_keywords is False and req.emoji is False


def test_render_clip_passes_options_to_build_ass(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(render, "_probe_size", lambda v: (1080, 1920))
    monkeypatch.setattr(render, "build_ass", lambda *a, **k: seen.update(k) or "")
    monkeypatch.setattr(render.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop")))
    try:
        render.render_clip(tmp_path / "v.mp4", WORDS, 0, 1, tmp_path, "c", highlight=True, emoji=True)
    except RuntimeError:
        pass
    assert seen["highlight"] is True and seen["emoji"] is True


def test_reveal_style_still_hides_unspoken_words_with_highlight():
    caps = _caps(render.build_ass(WORDS, 0, 5, "reveal", None, highlight=True))
    assert "insane" not in caps[0]
