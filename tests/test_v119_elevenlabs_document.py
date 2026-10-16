from __future__ import annotations

from zeroreels import v119_elevenlabs_document as v119


class _Editor:
    def __init__(self, views):
        self.views = views

    def evaluate(self, script, value=None):
        if "const textOf" in script:
            return self.views
        if "typeof el.value" in script:
            return self.views[0] if self.views else ""
        if "tagName" in script:
            return "div"
        raise AssertionError("unexpected evaluate")


def test_document_verifier_accepts_full_script_across_sibling_blocks():
    expected = (
        "[serious] Scene one has seventeen useful spoken words here for the first visual beat. "
        "[pause] Scene two continues with the rest of the narration and does not disappear. "
        "[whispers] Scene three lands the ending cleanly."
    )
    first_block = "[serious] Scene one has seventeen useful spoken words here for the first visual beat."
    full_document = (
        first_block
        + "\n\npause\n\nScene two continues with the rest of the narration and does not disappear."
        + "\n\nwhispers Scene three lands the ending cleanly."
    )
    editor = _Editor([first_block, full_document])

    text, matched, complete = v119._best_document_view(expected, editor)

    assert complete
    assert matched == len(v119.v116_integrity_chat._spoken_signature(expected))
    assert "Scene two" in text
    assert "Scene three" in text


def test_document_verifier_rejects_true_first_scene_only_result():
    expected = "[serious] One two three four. [pause] Five six seven eight. [whispers] Nine ten eleven twelve."
    first_only = "serious One two three four."
    editor = _Editor([first_only])

    _text, matched, complete = v119._best_document_view(expected, editor)

    assert not complete
    assert matched == 4


def test_ordered_match_count_ignores_interleaved_ui_words():
    expected = ["one", "two", "three", "four"]
    actual = ["voice", "one", "settings", "two", "three", "button", "four"]
    assert v119._ordered_match_count(expected, actual) == 4
