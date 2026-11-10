#!/usr/bin/env python3
"""Install/reload this checkout's studio as a macOS user LaunchAgent."""
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
label = "com.ditherforge.indx-studio"
agent = Path.home() / "Library/LaunchAgents" / (label + ".plist")
spec = {"Label": label, "ProgramArguments": [sys.executable, str(root / "chat/indx.py"), "web"],
        "WorkingDirectory": str(root), "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "StandardOutPath": str(root / ".local/web-service.log"), "StandardErrorPath": str(root / ".local/web-service.log")}
if agent.exists() and plistlib.loads(agent.read_bytes()).get("ProgramArguments") != spec["ProgramArguments"]:
    raise SystemExit("An existing service points elsewhere; preserved it unchanged.")
domain = f"gui/{os.getuid()}"
loaded = subprocess.run(["launchctl", "print", domain + "/" + label], capture_output=True).returncode == 0
if loaded:
    subprocess.run(["launchctl", "bootout", domain + "/" + label], check=True)
else:
    pidfile = root / ".local/web.pid"
    if pidfile.is_file():
        pid = int(pidfile.read_text())
        command = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
        if str(root / "chat/indx.py") in command and "web" in command:
            os.kill(pid, signal.SIGTERM)
agent.parent.mkdir(parents=True, exist_ok=True)
agent.write_bytes(plistlib.dumps(spec))
subprocess.run(["launchctl", "bootstrap", domain, str(agent)], check=True)
print(f"Installed {label}; starts after login and restarts on failure.")
