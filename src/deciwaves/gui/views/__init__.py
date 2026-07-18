"""The two shell views (issue #67) + the adaptive per-game panel (#73)."""
from deciwaves.gui.views.game_panel import GamePanel
from deciwaves.gui.views.library import LibraryView
from deciwaves.gui.views.pipeline import PipelineView

__all__ = ["GamePanel", "LibraryView", "PipelineView"]
