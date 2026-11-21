import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# Tests write their runs and episodes into a throwaway database, never into out/lab.db.
import os as _os
import tempfile as _tempfile

_os.environ.setdefault("DREAM_LAB_DB", _os.path.join(_tempfile.mkdtemp(), "lab.db"))
_os.environ.setdefault("DREAM_BRAIN_DIR", _os.path.join(_tempfile.mkdtemp(), "brain"))
