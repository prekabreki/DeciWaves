"""Theme constants shared across the GUI (issue #133, L1). Every view imports its status
colours from here rather than duplicating hex strings, so a dark-theme variant can be added
in one place.

Semantic value names (OK, ERROR, WARN, NEUTRAL, RUNNING) follow QPalette roles convention;
the specific hex values match the prior four-file originals.
"""

OK = "#167f3b"
ERROR = "#b00020"
WARN = "#b06f00"
NEUTRAL = "#666666"
RUNNING = "#1b6ec2"
