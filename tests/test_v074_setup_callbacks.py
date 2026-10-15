from zeroreels.v074_setup_fix import _invoke_setup_action


def test_setup_action_accepts_two_callbacks():
    calls = []

    def action(progress, log):
        calls.append((progress, log))
        return "ok"

    progress = object()
    log = object()
    assert _invoke_setup_action(action, progress, log) == "ok"
    assert calls == [(progress, log)]


def test_setup_action_accepts_progress_only():
    calls = []

    def action(progress):
        calls.append(progress)
        return "ok"

    progress = object()
    assert _invoke_setup_action(action, progress, object()) == "ok"
    assert calls == [progress]


def test_setup_action_accepts_no_callbacks():
    calls = []

    def action():
        calls.append(True)
        return "ok"

    assert _invoke_setup_action(action, object(), object()) == "ok"
    assert calls == [True]


def test_setup_action_supports_varargs():
    calls = []

    def action(*args):
        calls.append(args)

    progress = object()
    log = object()
    _invoke_setup_action(action, progress, log)
    assert calls == [(progress, log)]


def test_internal_typeerror_is_not_misclassified_as_callback_mismatch():
    def action(progress):
        raise TypeError("installer-internal-error")

    try:
        _invoke_setup_action(action, object(), object())
    except TypeError as exc:
        assert str(exc) == "installer-internal-error"
    else:
        raise AssertionError("internal TypeError should propagate")
