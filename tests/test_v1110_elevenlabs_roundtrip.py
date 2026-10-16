from zeroreels import v1110_elevenlabs_roundtrip as v1110


def test_sequence_complete_tolerates_tag_and_ui_tokens():
    expected = "[serious] Area 51 was built for secrets. [pause] The real story starts with spy planes."
    actual = "serious Settings Model Eleven v4 Area 51 was built for secrets pause Generate speech The real story starts with spy planes"
    assert v1110._sequence_complete(expected, actual)


def test_sequence_complete_rejects_first_scene_only():
    expected = "[serious] First scene has the hook. [pause] Second scene adds context. Third scene lands the ending."
    actual = "serious First scene has the hook pause"
    assert not v1110._sequence_complete(expected, actual)


def test_ordered_match_count_handles_noise_without_reordering():
    expected = ["alpha", "beta", "gamma", "delta"]
    actual = ["ui", "alpha", "tag", "beta", "button", "gamma", "footer", "delta"]
    assert v1110._ordered_match_count(expected, actual) == 4
    assert v1110._ordered_match_count(expected, ["alpha", "gamma", "beta", "delta"]) == 2
