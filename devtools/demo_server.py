"""Run MyMeeting with stand-in models: no downloads, instant start.

Useful for working on the interface or taking screenshots. The pipeline code is
real; only the Whisper and LLM calls are replaced by scripted output.

    python devtools/demo_server.py          # http://localhost:5055
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "devtools"))

import fake_models  # noqa: E402
import engine  # noqa: E402

fake_models.install(whisper_delay=0.35, llm_delay=1.8)

from app import create_app  # noqa: E402

if __name__ == "__main__":
    data_dir = os.environ.get("DATA_DIR") or tempfile.mkdtemp(prefix="mymeeting-demo-")
    print(f"Demo data folder: {data_dir}")
    create_app(data_dir).run(host="127.0.0.1", port=int(os.environ.get("PORT", 5055)), threaded=True)
