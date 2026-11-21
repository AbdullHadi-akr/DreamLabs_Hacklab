"""Starts the dashboard from anywhere:  python dream-tool/start.py  (same as  python -m dashboard)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
