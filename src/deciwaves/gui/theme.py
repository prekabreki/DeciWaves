"""Single source of truth for GUI status colours. Imported by all views that render
status/severity markers; derive from QPalette or add dark-variant overrides here.

Green  (ok / done)       -- matches the global bar's ``#167f3b``.
Red    (error)           -- matches the global bar's ``#b00020``.
Amber  (warn)            -- ``#b06f00``.
Neutral (pending / idle) -- ``#666666``.
Blue   (running)         -- ``#1b6ec2``."""
from __future__ import annotations

OK = "#167f3b"
ERR = "#b00020"
WARN = "#b06f00"
NEUTRAL = "#666666"
RUNNING = "#1b6ec2"
