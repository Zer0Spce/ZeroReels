from __future__ import annotations

from . import services


def _combine_filter_cfr(self, project, transitions: bool, burn_captions: bool):
    filters: list[str] = []
    n = len(project.scenes)

    # The scene clips are already rendered as CFR 30fps, start at timestamp zero, and share
    # resolution/pixel format. On FFmpeg 7.1, fps/setpts here clears link frame_rate to 0/0,
    # which makes xfade reject otherwise-valid CFR inputs. Keep the stream metadata intact.
    for i in range(n):
        filters.append(f"[{i}:v]format=yuv420p[v{i}]")

    use_xfade, transition_name, transition = self._transition_config(transitions)
    if use_xfade and n > 1:
        current = "[v0]"
        offset = 0.0
        for i in range(1, n):
            offset += max(0.25, project.scenes[i - 1].duration)
            out = f"[x{i}]"
            filters.append(
                f"{current}[v{i}]xfade=transition={transition_name}:duration={transition:.3f}:offset={offset:.3f}{out}"
            )
            current = out
    else:
        labels = "".join(f"[v{i}]" for i in range(n))
        current = "[joined]"
        filters.append(f"{labels}concat=n={n}:v=1:a=0{current}")

    if burn_captions:
        filters.append(f"{current}{self._caption_filter()}[vout]")
        current = "[vout]"
    return ";".join(filters), current


def install() -> None:
    services.FFmpegRenderer._combine_filter = _combine_filter_cfr
