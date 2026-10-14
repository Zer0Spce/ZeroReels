from zeroreels.v053_duration import _generic_hook, _word_count


def test_generic_hook_guard_flags_canned_openers():
    assert _generic_hook("Imagine this: the ocean suddenly vanishes.")
    assert _generic_hook("Did you know this island was once underwater?")
    assert not _generic_hook("If Earth stopped spinning, the ground would not stop with it.")


def test_word_count_handles_spoken_contractions():
    assert _word_count("If Earth stopped, you'd feel it immediately.") == 7
