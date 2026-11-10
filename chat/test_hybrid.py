from http.server import ThreadingHTTPServer
import json
from types import SimpleNamespace
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import indx
import hybrid


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch.object(indx, "ROOT", self.root)
        self.patch.start()
        engine = self.root / "build/bin/ditherforge-cli"
        engine.parent.mkdir(parents=True)
        engine.write_bytes(b"test engine placeholder")
        self.project = self.root / "projects/Fixture"
        source = self.project / "Reference/fixture.glb"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"test source")
        self.settings = self.project / "Source/Dither.json"
        self.tool = {"tool": 1, "label": "Test white", "color": "#FFFFFF", "type": "PLA", "role": "color", "td": None}
        indx.write(self.root / ".local/indx-profiles.json", {"materials": {indx.MATERIAL: {"type": "PLA"}, "Prusament PLA ColorMix White": {"type": "PLA"}}, "processes": {"detail": {"layerHeight": .15}, "draft": {"layerHeight": .2}}})
        indx.write(self.root / "chat/processes.json", {"processes": [{"layer_height": .15}]})
        indx.write(self.root / "chat/inventory.json", {"tools": [self.tool]})
        indx.write(self.settings, {"settings": {"inputFile": "../Reference/fixture.glb", "printer": indx.PRINTER, "nozzleDiameter": "0.4", "layerHeight": "0.15", "colorSlots": [{"hex": "#FFFFFF"}]}, "_indx": {"sourceSha256": indx.sha(source), "tools": [self.tool]}})

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_remote_access_requires_exact_origin_identity_and_device(self):
        remote = {"origin": "https://mini.example.ts.net:8447", "allowedLogins": ["owner@example.test"], "allowedClientIPs": ["100.64.0.2"]}
        headers = {"Host": "mini.example.ts.net:8447", "X-Forwarded-Host": "mini.example.ts.net:8447", "X-Forwarded-Proto": "https", "X-Forwarded-For": "100.64.0.2", "Tailscale-User-Login": "owner@example.test"}
        self.assertEqual(hybrid.request_origin(headers, 8874, "127.0.0.1", remote), remote["origin"])
        for changed in ({"Tailscale-User-Login": "other@example.test"}, {"X-Forwarded-For": "100.64.0.3"}, {"Host": "127.0.0.1:8874"}, {"Tailscale-Funnel-Request": "?1"}, {"X-Forwarded-For": "100.64.0.2, 100.64.0.3"}):
            with self.assertRaises(PermissionError):
                hybrid.request_origin({**headers, **changed}, 8874, "127.0.0.1", remote)
        with self.assertRaises(PermissionError):
            hybrid.request_origin(headers, 8874, "100.64.0.2", remote)

    def test_remote_access_is_disabled_without_explicit_config(self):
        self.assertEqual(hybrid.request_origin({"Host": "127.0.0.1:8874"}, 8874, "127.0.0.1", {}), "http://127.0.0.1:8874")
        with self.assertRaises(PermissionError):
            hybrid.request_origin({"Host": "remote.example"}, 8874, "127.0.0.1", {})

    def test_shared_settings_update_and_conflict_detection(self):
        before = indx.sha(self.settings)
        result = indx.configure(self.settings, {"brightness": 15}, before)
        self.assertEqual(indx.read(self.settings)["settings"]["brightness"], 15)
        self.assertEqual(result["settingsSha256"], indx.sha(self.settings))
        with self.assertRaisesRegex(ValueError, "another session"):
            indx.configure(self.settings, {"brightness": 20}, before)

    def test_invalid_material_or_layer_preserves_saved_file(self):
        before = indx.sha(self.settings)
        bad = {**self.tool, "type": "PETG"}
        for change in ({"tools": [bad]}, {"layerHeight": .12}, {"inputFile": "/unrelated/file"}):
            with self.assertRaises(ValueError):
                indx.configure(self.settings, change, before)
            self.assertEqual(indx.sha(self.settings), before)

    def test_colormix_profile_and_layer_limit_are_checked_before_save(self):
        before = indx.sha(self.settings)
        unknown = {**self.tool, "materialPreset": "Unknown PLA"}
        with self.assertRaisesRegex(ValueError, "installed"):
            indx.configure(self.settings, {"tools": [unknown]}, before)
        self.assertEqual(indx.sha(self.settings), before)
        cm = {**self.tool, "materialPreset": "Prusament PLA ColorMix White"}
        indx.configure(self.settings, {"tools": [cm]}, before)
        before = indx.sha(self.settings)
        indx.write(self.root / "chat/processes.json", {"processes": [{"layer_height": .15}, {"layer_height": .2}]})
        with self.assertRaisesRegex(ValueError, "0.15 mm"):
            indx.configure(self.settings, {"layerHeight": .2}, before)
        self.assertEqual(indx.sha(self.settings), before)

    def test_project_busy_in_chat_prevents_browser_save(self):
        with indx.project_lock(self.settings):
            with self.assertRaisesRegex(ValueError, "busy"):
                indx.configure(self.settings, {"brightness": 5}, indx.sha(self.settings))

    def test_failed_generation_preserves_current_print_without_archiving(self):
        output = self.project / "Print Files/Fixture - INDX8T - PLA.3mf"
        output.parent.mkdir()
        output.write_bytes(b"previous validated print")
        (self.root / ".local/runs").mkdir()
        with patch.object(indx, "runtime", return_value={}), patch.object(indx, "run", side_effect=ValueError("simulated generation failure")):
            with self.assertRaisesRegex(ValueError, "simulated generation failure"):
                indx.build(SimpleNamespace(settings=str(self.settings), replace=True))
        self.assertEqual(output.read_bytes(), b"previous validated print")
        self.assertFalse((self.project / "Archive").exists())

    def test_project_paths_cannot_escape_print_folder(self):
        with patch.object(hybrid, "PROJECTS", self.root / "projects"):
            for name in ("../escape", "/tmp/escape", "Tools", ".."):
                with self.assertRaises(ValueError):
                    hybrid.project_path(name)

    def test_loopback_api_rejects_cross_origin_mutation(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), hybrid.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            payload = json.dumps({"project": "Fixture", "expectedHash": indx.sha(self.settings), "patch": {"brightness": 9}}).encode()
            headers = {"Content-Type": "application/json", "X-DitherForge": "local", "Origin": "https://another.example"}
            with self.assertRaises(HTTPError) as raised:
                urlopen(Request(base + "/api/configure", payload, headers))
            raised.exception.close()
            with patch.object(hybrid, "PROJECTS", self.root / "projects"):
                headers["Origin"] = base
                with urlopen(Request(base + "/api/configure", payload, headers)) as response:
                    self.assertEqual(response.status, 200)
            self.assertEqual(indx.read(self.settings)["settings"]["brightness"], 9)
            with patch.object(hybrid, "PROJECTS", self.root / "projects"), patch.object(indx, "runtime", return_value={}):
                upload_headers = {"Origin": base, "X-DitherForge": "local", "X-Filename": "Original.glb", "Content-Type": "application/octet-stream"}
                with urlopen(Request(base + "/api/import?name=Imported", b"original model bytes", upload_headers)) as response:
                    self.assertEqual(response.status, 200)
                self.assertEqual((self.root / "projects/Imported/Reference/Original.glb").read_bytes(), b"original model bytes")
        finally:
            server.shutdown(); server.server_close(); thread.join()
