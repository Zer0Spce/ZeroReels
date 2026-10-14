from __future__ import annotations

from . import services, ui


def install() -> None:
    original_create_page = ui.MainWindow._create_page
    original_transition_config = services.FFmpegRenderer._transition_config
    original_render_scene_clips = services.FFmpegRenderer._render_scene_clips
    original_combine_filter = services.FFmpegRenderer._combine_filter
    original_render = services.FFmpegRenderer.render

    def create_page(self):
        page = original_create_page(self)
        if hasattr(self, "transition_style_box"):
            items = [self.transition_style_box.itemText(i) for i in range(self.transition_style_box.count())]
            if "Story Rhythm" not in items:
                self.transition_style_box.insertItem(0, "Story Rhythm")
            self.transition_style_box.setCurrentText("Story Rhythm")
            self.transition_style_box.setToolTip(
                "Story Rhythm adapts transition speed to the selected storytelling style: faster for TikTok/social, softer for mystery/documentary."
            )
        return page

    def transition_config(self, transitions: bool):
        if not transitions:
            return False, "fade", 0.0
        style = getattr(self, "_zr_transition_style", "Natural Crossfade")
        if style != "Story Rhythm":
            return original_transition_config(self, transitions)
        project_style = getattr(self, "_zr_project_style", "TikTok Story")
        if project_style in {"TikTok Story", "Viral Explainer", "Fast Social"}:
            return True, "fade", 0.14
        if project_style in {"Dark Curiosity", "Dark Mystery"}:
            return True, "dissolve", 0.24
        if project_style in {"Mini Documentary", "Cinematic Documentary"}:
            return True, "fade", 0.20
        return True, "fade", 0.18

    def render_scene_clips(self, project, out_dir, motion: bool, transitions: bool):
        callback = getattr(self, "_zr_progress", None)
        if callback:
            callback(85, f"Rendering motion for {len(project.scenes)} scenes")
        result = original_render_scene_clips(self, project, out_dir, motion, transitions)
        if callback:
            callback(91, "Motion clips ready • building transitions")
        return result

    def combine_filter(self, project, transitions: bool, burn_captions: bool):
        callback = getattr(self, "_zr_progress", None)
        if callback:
            style = getattr(self, "_zr_transition_style", "Natural Crossfade")
            callback(93, f"Compositing {style} transitions" if transitions else "Compositing clean cuts")
        return original_combine_filter(self, project, transitions, burn_captions)

    def render(
        self,
        project,
        audio,
        captions,
        out_dir,
        motion=True,
        transitions=True,
        caption_position="Bottom",
        caption_size="Small",
        transition_style="Natural Crossfade",
    ):
        self._zr_project_style = project.style
        callback = getattr(self, "_zr_progress", None)
        if callback:
            callback(84, "Starting final edit")
        result = original_render(
            self,
            project,
            audio,
            captions,
            out_dir,
            motion=motion,
            transitions=transitions,
            caption_position=caption_position,
            caption_size=caption_size,
            transition_style=transition_style,
        )
        if callback:
            callback(97, "Video encode complete")
        return result

    ui.MainWindow._create_page = create_page
    services.FFmpegRenderer._transition_config = transition_config
    services.FFmpegRenderer._render_scene_clips = render_scene_clips
    services.FFmpegRenderer._combine_filter = combine_filter
    services.FFmpegRenderer.render = render
