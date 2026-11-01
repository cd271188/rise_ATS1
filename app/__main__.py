"""Run with: python -m app  (host/port via ATS_HOST / ATS_PORT, worker processes via ATS_WORKERS)."""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:create_app", factory=True, host=os.environ.get("ATS_HOST", "127.0.0.1"),
                port=int(os.environ.get("ATS_PORT", "8000")), workers=max(1, int(os.environ.get("ATS_WORKERS", "1"))))