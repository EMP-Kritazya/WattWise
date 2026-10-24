"""The agents are scripts run from agents/ (`python agents/weather.py`), so their modules import each other by name."""

import sys
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent.parent
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))
