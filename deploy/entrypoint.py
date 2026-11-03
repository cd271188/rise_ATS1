"""Verify persistent storage as the application user, then run the application."""
import os
import sys
import tempfile
from pathlib import Path

os.umask(0o002)
for directory in ("/data", "/data/models_cache", "/data/cv_files"):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    # A mounted volume has storage-managed ownership; do not chown it.
    # SQLite also needs directory access for journal/WAL/SHM files.
    with tempfile.TemporaryFile(dir=path) as probe:
        probe.write(b"ats-storage-check")
        probe.seek(0)
        if probe.read() != b"ats-storage-check":
            raise RuntimeError(f"storage verification failed: {path}")
    stat = path.stat()
    print(f"storage ready: {path} owner={stat.st_uid}:{stat.st_gid} "
          f"mode={stat.st_mode & 0o7777:o} uid={os.getuid()} gid={os.getgid()}", flush=True)
os.execvp(sys.argv[1], sys.argv[1:])
