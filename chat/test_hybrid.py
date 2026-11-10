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
        indx.write(self.root / ".local/indx-profiles.json", {"processes": {"detail": {"layerHeight": .15}}})
        indx.write(self.root / "chat/processes.json", {"processes": [{"layer_height": .15}]})
        indx.write(self.root / "chat/inventory.json", {"tools": [self.tool]})
        indx.write(self.settings, {"settings": {"inputFile": "../Reference/fixture.glb", "printer": indx.PRINTER, "nozzleDiameter": "0.4", "layerHeight": "0.15", "colorSlots": [{"hex": "#FFFFFF"}]}, "_indx": {"sourceSha256": indx.sha(source), "tools": [self.tool]}})

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

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
