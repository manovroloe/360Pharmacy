from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from dotenv import load_dotenv
load_dotenv(SERVER / ".env")

import uvicorn

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    print(f"[360 Pharmacy] Open http://127.0.0.1:{port}")
    uvicorn.run("server.main:app", host=host, port=port, reload=False)
