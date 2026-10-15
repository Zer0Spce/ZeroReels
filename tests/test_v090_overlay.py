from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from zeroreels.models import GenerationOptions, Project, Scene
from zeroreels import v090_overlay


def test_overlay_enabled_by_default_and_metadata_fields_exist():
    assert GenerationOptions().web_video_overlay is True
    scene = Scene(index=1, narration="test", image_prompt="test")
    assert scene.overlay_video_path == ""
    assert scene.overlay_source_url == ""


def test_overlay_targets_selected_real_image_scenes():
    project = Project(topic="Test", web_video_overlay=True)
    scene = Scene(
        index=2,
        narration="A real scene changes.",
        image_prompt="test",
        source_type="Wikimedia Commons",
        media_type="image",
        shot_role="Establishing",
    )
    assert v090_overlay._should_overlay(project, scene)
    scene.source_type = "AI Generated"
    assert not v090_overlay._should_overlay(project, scene)


def test_overlay_geometry_keeps_caption_area_clear():
    ow, oh, ox, oy = v090_overlay._overlay_filter(1080, 1920)
    assert ow < 1080
    assert oh < 1920 // 2
    assert ox > 0
    assert oy + oh < int(1920 * 0.75)


def test_overlay_renderer_uses_image_and_video_inputs(tmp_path, monkeypatch):
    image = tmp_path / "still.jpg"
    video = tmp_path / "overlay.webm"
    image.write_bytes(b"still")
    video.write_bytes(b"video")
    project = Project(topic="Test", format="9:16")
    project.scenes = [
        Scene(
            index=1,
            narration="Test",
            image_prompt="test",
            duration=2.0,
            image_path=str(image),
            source_type="Wikimedia Commons",
            media_type="image",
            overlay_video_path=str(video),
        )
    ]
    commands = []

    monkeypatch.setattr(v090_overlay.services, "dimensions_for", lambda fmt: (1080, 1920))
    monkeypatch.setattr(v090_overlay.v060_render, "_story_transition_plan", lambda self, project, transitions: [])
    monkeypatch.setattr(
        v090_overlay.v080_render,
        "_full_frame_real_filter",
        lambda width, height, frames, motion, index: "scale=1080:1920,setsar=1,fps=30,format=yuv420p",
    )

    class Proc:
        returncode = 0
        stderr = b""

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"rendered")
        return Proc()

    monkeypatch.setattr(v090_overlay, "run_hidden", fake_run)
    renderer = SimpleNamespace(_ffmpeg=lambda: "ffmpeg", _zr_progress=None)
    clips = v090_overlay.render_overlay_scene_clips(renderer, project, tmp_path, motion=True, transitions=False)
    assert len(clips) == 1
    cmd = commands[0]
    assert cmd.count("-i") == 2
    assert "-stream_loop" in cmd
    assert "-filter_complex" in cmd
    complex_filter = cmd[cmd.index("-filter_complex") + 1]
    assert "overlay=" in complex_filter
    assert "[outv]" in complex_filter
