from __future__ import annotations

from . import v071_pipeline


_ORIGINAL_RUNTIME_REWRITE = v071_pipeline.rewrite_for_measured_duration_v2


def _runtime_rewrite_with_custom_guard(settings, project, actual_seconds: float, progress=None, pass_index: int = 1):
    if getattr(project, "script_mode", "AI Script") == "Custom Script":
        if progress:
            progress(
                31,
                f"Custom Script lock • preserving your wording • {actual_seconds:.1f}s measured",
            )
        return False
    return _ORIGINAL_RUNTIME_REWRITE(
        settings,
        project,
        actual_seconds,
        progress=progress,
        pass_index=pass_index,
    )


def install() -> None:
    # v071_pipeline.reality_mix_run resolves this module-global at runtime, so replacing it here
    # keeps Custom Script truly verbatim even when Measured Runtime Lock is enabled.
    v071_pipeline.rewrite_for_measured_duration_v2 = _runtime_rewrite_with_custom_guard
