from __future__ import annotations

from . import quality_services, services


def install() -> None:
    """Use the quality script planner directly; v0.5.2 no longer asks Ollama to reuse exact images."""
    services.ScriptService.generate = quality_services._human_script_generate
