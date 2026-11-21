"""Startet das Dashboard von ueberall:  python dream-tool/start.py  (gleich wie  python -m dashboard)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
