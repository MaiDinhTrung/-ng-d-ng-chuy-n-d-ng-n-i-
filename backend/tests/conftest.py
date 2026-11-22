import os
import sys
import tempfile
from pathlib import Path

# Dữ liệu test tách khỏi data thật.
os.environ.setdefault("VOICESTUDIO_DATA", tempfile.mkdtemp(prefix="voicestudio_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
