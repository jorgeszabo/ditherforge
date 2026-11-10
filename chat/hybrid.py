"""Loopback-only browser front end for the same dither-chat project workflow."""
import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import ipaddress
import mimetypes
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import parse_qs, quote, unquote, urlsplit
import uuid
from urllib.request import urlopen

import indx

PROJECTS = indx.ROOT.parents[1]
STATIC = indx.ROOT / "frontend/hybrid-dist"
JOBS = {}
JOB_LOCK = threading.Lock()


def request_origin(headers, port, peer, remote):
    """Trust Serve identity only via the loopback proxy and an exact configured origin."""
    if not ipaddress.ip_address(peer).is_loopback:
        raise PermissionError("The app accepts direct connections only from its local proxy.")
    local_host = f"127.0.0.1:{port}"
    forwarded = any(headers.get(k) for k in ("X-Forwarded-For", "X-Forwarded-Host", "Tailscale-User-Login", "Tailscale-Funnel-Request"))
    if headers.get("Host") == local_host and not forwarded:
        return "http://" + local_host
    origin = remote.get("origin", "")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or parsed.netloc != headers.get("Host") or headers.get("X-Forwarded-Host") != parsed.netloc or headers.get("X-Forwarded-Proto") != "https":
        raise PermissionError("This remote address is not configured for the studio.")
    if headers.get("Tailscale-Funnel-Request") or headers.get("Tailscale-User-Login", "").casefold() not in {s.casefold() for s in remote.get("allowedLogins", [])}:
        raise PermissionError("Access requires an approved Tailscale identity.")
    try:
        address = str(ipaddress.ip_address(headers.get("X-Forwarded-For", "")))
    except ValueError:
        raise PermissionError("Missing trusted Tailscale device address.")
    if address not in remote.get("allowedClientIPs", []):
        raise PermissionError("This device is not approved for the studio.")
    return origin


def project_path(name):
    if not isinstance(name, str) or not name.strip() or name in {".", "..", "Tools"} or any(c in name for c in '/\\\0'):
        raise ValueError("Choose a project name without path separators.")
    path = (PROJECTS / name).resolve()
    if path.parent != PROJECTS.resolve():
        raise ValueError("Project must stay in the 3D-Printing folder.")
    return path


def settings_path(name):
    file = project_path(name) / "Source/Dither.json"
    if not file.is_file():
        raise ValueError("This project has no DitherForge settings.")
    return file


def project_state(name):
    settings = settings_path(name)
    doc = indx.read(settings)
    digest = indx.sha(settings)
    defaults = {t["tool"]: t for t in indx.read(indx.ROOT / "chat/inventory.json")["tools"]}
    defaults.update({t["tool"]: t for t in doc["_indx"]["tools"]})
    preview = indx.preview_directory(settings)
    preview_ready = (preview / "preview.json").is_file() and all((preview / n).is_file() for n in ("input.mesh", "output.mesh"))
    validation_path = settings.parent / "Validation.json"
    report = indx.read(validation_path) if validation_path.is_file() else None
    output = project_path(name) / "Print Files" / f"{name} - INDX8T - PLA.3mf"
    intact = bool(report and output.is_file() and indx.sha(output) == report.get("outputSha256"))
    return {"name": name, "settings": doc["settings"], "settingsSha256": digest,
            "tools": [defaults.get(i, {"tool": i, "role": "unassigned"}) for i in range(1, 9)],
            "previewReady": preview_ready, "previewKey": preview.name if preview_ready else None,
            "validation": report if intact else None, "printCurrent": intact and report.get("settingsSha256") == digest,
            "sourceName": Path(doc["settings"]["inputFile"]).name}


def start_job(kind, name):
    file = settings_path(name)
    with JOB_LOCK:
        if any(j["status"] == "running" for j in JOBS.values()):
            raise ValueError("Another browser job is running. Wait for it to finish.")
        job_id = uuid.uuid4().hex
        folder = indx.ROOT / ".local/web-jobs" / job_id
        folder.mkdir(parents=True)
        job = {"id": job_id, "kind": kind, "project": name, "status": "running", "started": time.time(), "log": str(folder / "progress.log")}
        JOBS[job_id] = job

    def worker():
        try:
            command = [str(indx.ROOT / "chat/dither-chat"), kind, str(file)]
            if kind == "build":
                command.append("--replace")
            with (folder / "result.json").open("w") as result, (folder / "progress.log").open("w") as log:
                proc = subprocess.run(command, stdout=result, stderr=log)
            if proc.returncode:
                raise ValueError((folder / "progress.log").read_text()[-4000:])
            data = indx.read(folder / "result.json")
            with JOB_LOCK:
                job.update(status="done", finished=time.time(), result=data)
        except Exception as exc:
            with JOB_LOCK:
                job.update(status="error", finished=time.time(), error=str(exc))
    threading.Thread(target=worker, daemon=True).start()
    return {"id": job_id}


class Handler(BaseHTTPRequestHandler):
    server_version = "DitherForgeLocal/1"

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def local_request(self, mutation=False):
        config = indx.ROOT / ".local/remote-access.json"
        remote = indx.read(config) if config.is_file() else {}
        expected = request_origin(self.headers, self.server.server_port, self.client_address[0], remote)
        if mutation and (self.headers.get("Origin") != expected or self.headers.get("X-DitherForge") != "local"):
            raise PermissionError("Settings changes must originate from this studio page.")

    def send_file(self, file, attachment=False):
        if not file.is_file():
            raise ValueError("File is not available yet.")
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream" if file.suffix == ".mesh" else (mimetypes.guess_type(file.name)[0] or "application/octet-stream"))
        self.send_header("Content-Length", str(file.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if attachment:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(file.name))
        self.end_headers()
        with file.open("rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def do_GET(self):
        try:
            self.local_request()
            url = urlsplit(self.path)
            params = parse_qs(url.query)
            if url.path == "/api/state":
                names = sorted(p.name for p in PROJECTS.iterdir() if p.is_dir() and (p / "Source/Dither.json").is_file() and p.resolve().parent == PROJECTS.resolve())
                profiles = indx.read(indx.ROOT / "chat/processes.json")
                self.send_json({"app": "DitherForge INDX Hybrid", "projects": names, "processes": profiles["processes"], "slicerVersion": profiles.get("slicerVersion", "")})
            elif url.path == "/api/project":
                self.send_json(project_state(params["name"][0]))
            elif url.path == "/api/job":
                with JOB_LOCK:
                    job = dict(JOBS[params["id"][0]])
                log = Path(job.pop("log"))
                if log.is_file():
                    with log.open("rb") as f:
                        f.seek(max(0, log.stat().st_size - 3000))
                        job["progress"] = f.read().decode(errors="replace")
                self.send_json(job)
            elif url.path == "/api/mesh":
                name, view = params["name"][0], params["view"][0]
                if view not in {"input", "output"}:
                    raise ValueError("Unknown preview view.")
                directory = indx.preview_directory(settings_path(name))
                if not (directory / "preview.json").is_file():
                    raise ValueError("Generate a preview first.")
                self.send_file(directory / (view + ".mesh"))
            elif url.path == "/api/download":
                name = params["name"][0]
                state = project_state(name)
                if not state["validation"] or not state["validation"].get("passed"):
                    raise ValueError("There is no validated print file to download.")
                self.send_file(project_path(name) / "Print Files" / f"{name} - INDX8T - PLA.3mf", True)
            else:
                path = unquote(url.path).lstrip("/") or "hybrid.html"
                file = (STATIC / path).resolve()
                if not file.is_relative_to(STATIC.resolve()):
                    raise ValueError("Unknown app asset.")
                self.send_file(file)
        except PermissionError as exc:
            self.send_json({"error": str(exc)}, 403)
        except (ValueError, KeyError, OSError, TypeError) as exc:
            self.send_json({"error": str(exc)}, 400)

    def do_POST(self):
        try:
            self.local_request(True)
            length = int(self.headers.get("Content-Length", "0"))
            url = urlsplit(self.path)
            if url.path == "/api/import":
                params = parse_qs(url.query)
                name = params["name"][0].strip()
                project = project_path(name)
                if project.exists():
                    raise ValueError("That project already exists. Open it or choose a new name.")
                filename = Path(unquote(self.headers.get("X-Filename", ""))).name
                if Path(filename).suffix.lower() not in {".glb", ".3mf", ".stl", ".obj", ".dae", ".zip"}:
                    raise ValueError("Choose a GLB, 3MF, STL, OBJ, COLLADA, or zipped model.")
                if not 0 < length <= 512 * 1024 * 1024:
                    raise ValueError("Choose a model between 1 byte and 512 MiB.")
                folder = indx.ROOT / ".local/uploads" / uuid.uuid4().hex
                folder.mkdir(parents=True)
                upload = folder / filename
                with upload.open("wb") as f:
                    remaining = length
                    while remaining:
                        data = self.rfile.read(min(1024 * 1024, remaining))
                        if not data:
                            raise ValueError("The model transfer was interrupted.")
                        f.write(data)
                        remaining -= len(data)
                result = indx.init(argparse.Namespace(project=str(project), model=str(upload), inventory=str(indx.ROOT / "chat/inventory.json"), tools=None, size=50, layer=0.15))
                self.send_json({"project": name, **result})
            else:
                if not self.headers.get("Content-Type", "").startswith("application/json") or not 0 < length <= 1024 * 1024:
                    raise ValueError("Expected a small JSON settings request.")
                body = json.loads(self.rfile.read(length))
                name = body["project"]
                if url.path == "/api/configure":
                    self.send_json(indx.configure(settings_path(name), body["patch"], body["expectedHash"]))
                elif url.path in {"/api/preview", "/api/build"}:
                    if body.get("expectedHash") != indx.sha(settings_path(name)):
                        raise ValueError("Settings changed in another session. Reload before running.")
                    self.send_json(start_job(url.path.split("/")[-1], name))
                else:
                    raise ValueError("Unknown action.")
        except PermissionError as exc:
            self.send_json({"error": str(exc)}, 403)
        except (ValueError, KeyError, OSError, TypeError, AttributeError) as exc:
            self.send_json({"error": str(exc)}, 400)

    def log_message(self, fmt, *args):
        print(datetime.now().isoformat(timespec="seconds"), fmt % args, flush=True)


def serve(port=8874):
    indx.runtime()
    if not (STATIC / "hybrid.html").is_file():
        raise ValueError("Build the browser UI first: cd frontend && npm run build:hybrid")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"DitherForge INDX Hybrid: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def launch(port=8874):
    """Start the local app independently of the invoking chat/terminal session."""
    url = f"http://127.0.0.1:{port}"
    try:
        with urlopen(url + "/api/state", timeout=1) as response:
            if json.load(response).get("app") != "DitherForge INDX Hybrid":
                raise ValueError("That port belongs to another app; choose a different --port.")
        return {"url": url, "alreadyRunning": True}
    except OSError:
        pass
    log = indx.ROOT / ".local/web.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as stream:
        proc = subprocess.Popen([str(indx.ROOT / "chat/dither-chat"), "web", "--port", str(port)], stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    (indx.ROOT / ".local/web.pid").write_text(str(proc.pid))
    for _ in range(40):
        if proc.poll() is not None:
            raise ValueError(f"The local app could not start. See {log}.")
        try:
            with urlopen(url + "/api/state", timeout=.3) as response:
                if json.load(response).get("app") == "DitherForge INDX Hybrid":
                    return {"url": url, "pid": proc.pid, "alreadyRunning": False}
        except OSError:
            time.sleep(.1)
    raise ValueError(f"The local app is still starting; check {log}.")


def remote_access(device, https_port=8447):
    """Add a dedicated private Serve route without replacing any existing routes."""
    state = json.loads(indx.run(["tailscale", "status", "--json"]))
    host = state["Self"]
    peer = next((p for p in state.get("Peer", {}).values() if p.get("DNSName", "").rstrip(".") == device.rstrip(".")), None)
    if not peer or peer.get("UserID") != host.get("UserID"):
        raise ValueError("Choose an existing Tailscale device owned by the same account.")
    login = state.get("User", {}).get(str(host["UserID"]), {}).get("LoginName")
    if not login:
        raise ValueError("The Tailscale owner identity is unavailable.")
    dns = host["DNSName"].rstrip(".")
    before = json.loads(indx.run(["tailscale", "serve", "status", "--json"]))
    web_key = f"{dns}:{https_port}"
    proxy = {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8874"}}}
    if str(https_port) in before.get("TCP", {}) and before.get("Web", {}).get(web_key) != proxy:
        raise ValueError("That Tailscale port already serves another app. Choose another port.")
    config = {"origin": f"https://{web_key}", "allowedLogins": [login], "allowedClientIPs": host["TailscaleIPs"] + peer["TailscaleIPs"]}
    indx.write(indx.ROOT / ".local/remote-access.json", config)
    indx.write(indx.ROOT / ".local/serve-before.json", before)
    indx.run(["tailscale", "serve", "--bg", f"--https={https_port}", "http://127.0.0.1:8874"])
    after = json.loads(indx.run(["tailscale", "serve", "status", "--json"]))
    for section in ("TCP", "Web"):
        for key, value in before.get(section, {}).items():
            if after.get(section, {}).get(key) != value:
                raise ValueError("An existing Serve route changed; inspect .local/serve-before.json before continuing.")
    return {"url": config["origin"], "devices": [host["HostName"], peer["HostName"]], "private": True, "existingRoutesPreserved": True}
