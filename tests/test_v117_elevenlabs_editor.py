from zeroreels import v117_elevenlabs_editor as v117


def test_accepts_rendered_performance_tag_chips():
    expected = "[serious] Area 51 was secret. [pause] Then the story changed. [long pause]"
    actual = "serious Area 51 was secret. pause Then the story changed. long pause"
    assert v117._eleven_script_complete_v117(expected, actual)


def test_rejects_stale_previous_scene_before_full_script():
    expected = "[serious] Area 51 was secret. Then the story changed completely."
    stale = "Area 51 was secret."
    actual = stale + " serious Area 51 was secret. Then the story changed completely."
    assert not v117._eleven_script_complete_v117(expected, actual)


def test_rejects_arbitrary_extra_prose():
    expected = "[whispers] The gate stayed closed. [pause] Nobody entered."
    actual = "whispers The gate stayed closed. unrelated old words pause Nobody entered."
    assert not v117._eleven_script_complete_v117(expected, actual)


def test_rejects_missing_narration_even_when_tags_match():
    expected = "[shocked] One two three four five. [pause] Six seven eight nine."
    actual = "shocked One two three four pause Six seven eight nine"
    assert not v117._eleven_script_complete_v117(expected, actual)


def test_exact_plain_script_still_passes():
    expected = "One two three four."
    assert v117._eleven_script_complete_v117(expected, expected)
