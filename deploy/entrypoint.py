"""Prepare persistent directories, then run the application as the ats user."""
import os
import pwd
import sys
from pathlib import Path

if os.getuid() == 0:
    user = pwd.getpwnam("ats")
    for directory in ("/data", "/data/models_cache", "/data/cv_files"):
        Path(directory).mkdir(parents=True, exist_ok=True)
        os.chown(directory, user.pw_uid, user.pw_gid)
    os.initgroups(user.pw_name, user.pw_gid)
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)
os.execvp(sys.argv[1], sys.argv[1:])
