"""``python -m deciwaves.gui`` entry (used by launch_gui.bat)."""
import sys

from deciwaves.gui import launch

if __name__ == "__main__":
    sys.exit(launch(sys.argv[1:]))
