#!/usr/bin/env python3
"""Local INDX orchestration. DitherForge and the maintained 3MF converter run as CLIs."""
import argparse
from collections import Counter
from contextlib import contextmanager
import copy
from datetime import datetime
import fcntl
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PRINTER = "prusa_coreone_indx_8t"
MATERIAL = "Prusament PLA @COREONEINDX HF0.4@COREONEINDX 0.4"


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        f.write(json.dumps(data, indent=2) + "\n")
    Path(f.name).replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextmanager
def project_lock(settings):
    folder = ROOT / ".local/locks"
    folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(str(Path(settings).resolve()).encode()).hexdigest()
    with (folder / key).open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("This project is busy in chat or the browser. Wait for that job to finish.")
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def locked(fn):
    @wraps(fn)
    def call(args):
        with project_lock(args.settings):
            return fn(args)
    return call


def run(args, log=None, json_output=False, progress=False):
    command = [str(x) for x in args]
    if progress:
        lines = []
        with Path(log).open("w") as trace:
            p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in p.stdout:
                trace.write(line); trace.flush()
                print(line, end="", file=sys.stderr, flush=True)
                lines.append(line)
            p.wait()
        p = subprocess.CompletedProcess(command, p.returncode, "".join(lines), "")
    else:
        p = subprocess.run(command, capture_output=True, text=True)
        if log:
            Path(log).write_text(p.stdout + p.stderr)
    if p.returncode:
        raise ValueError(f"Command failed ({p.returncode}): {args[0]}\n{p.stderr[-2500:]}\nSee {log or 'command output'}")
    return json.loads(p.stdout) if json_output else (p.stdout + p.stderr).strip()


def runtime():
    r = read(ROOT / ".local/runtime.json")
    r["slicer"] = os.environ.get("PRUSA_SLICER", r["slicer"])
    r["converter"] = os.environ.get("THREEMF_CONVERTER", r["converter"])
    version = run([r["slicer"], "--version"])
    if version != read(ROOT / "chat/processes.json")["slicerVersion"]:
        raise ValueError(f"Expected the configured slicer version, got {version}. Do not silently change slicing versions.")
    if not (ROOT / "build/bin/ditherforge-cli").is_file():
        raise ValueError("Build the engine with scripts/build-indx.sh first.")
    r["slicerVersion"] = version
    return r


def converter(r, *args, log=None):
    return run(["node", Path(r["converter"]) / "cli.cjs", *args], log, True)


def color_tools(inventory, selected=None):
    tools = inventory["tools"]
    ids = [t["tool"] for t in tools]
    if any(type(t) is not int or t < 1 or t > 8 for t in ids) or len(ids) != len(set(ids)):
        raise ValueError("Inventory tool numbers must be unique integers 1–8.")
    chosen = [t for t in tools if t.get("role") == "color" and (selected is None or t["tool"] in selected)]
    if selected is not None and set(selected) != {t["tool"] for t in chosen}:
        raise ValueError("Requested tools include an unknown, unassigned or reserved support tool.")
    if not chosen or len(chosen) > 8:
        raise ValueError("Choose 1–8 known colour tools.")
    for t in chosen:
        if not isinstance(t.get("label"), str) or not t["label"].strip():
            raise ValueError("Give every selected spool a name before using it.")
        if t.get("type") != "PLA" or not re.fullmatch(r"#[0-9a-fA-F]{6}", t.get("color", "")):
            raise ValueError("The initial workflow requires known PLA swatches; keep PETG out of the colour mix.")
        if t.get("td") is not None and (not isinstance(t["td"], (float, int)) or t["td"] <= 0):
            raise ValueError("Measured TD must be positive, or null when unknown.")
    if len({t["color"].upper() for t in chosen}) != len(chosen):
        raise ValueError("Duplicate swatches make tool mapping ambiguous; choose one tool for that colour.")
    return chosen


def palette_mapping(filaments, tools):
    by_color = {t["color"].upper(): t for t in tools}
    mapping = {"map": {}, "materials": {}, "colors": {}}
    for source, f in enumerate(filaments, 1):
        t = by_color.get(f["color"].upper())
        if t is None:
            raise ValueError(f"Engine exported unexpected palette colour {f['color']}; refusing guessed tool mapping.")
        mapping["map"][str(source)] = t["tool"]
        mapping["materials"][str(t["tool"])] = t.get("materialPreset", MATERIAL)
        mapping["colors"][str(t["tool"])] = t["color"].upper()
    return mapping


def gcode_tools(text):
    selections = sorted({int(t) + 1 for t in re.findall(r"^[ \t]*T(\d+)\b", text, re.M)})
    amounts = re.findall(r"^; filament used \[mm\] = (.+)$", text, re.M)
    if not amounts:
        raise ValueError("G-code has no per-tool filament-use summary.")
    used = [i + 1 for i, amount in enumerate(amounts[-1].split(",")) if float(amount) > 0]
    return selections, used


def check_support_gcode(text, body_tool, interface_tool):
    """Check emitted relative-extrusion feature paths, including the PLA raft."""
    tool, kind, z = None, "Custom", None
    body, interface, first_layer = set(), set(), set()
    interface_z = []
    for line in text.splitlines():
        match = re.match(r"\s*T(\d+)\b", line)
        if match:
            tool = int(match[1]) + 1
        if line.startswith(";TYPE:"):
            kind = line[6:]
        if line.startswith(";Z:"):
            z = float(line[3:])
        if not re.match(r"G[0123]\s", line) or z is None or kind == "Custom":
            continue
        words = dict(re.findall(r"\b([XYE])(-?(?:\d+(?:\.\d*)?|\.\d+))", line))
        if float(words.get("E", 0)) <= 0 or not ({"X", "Y"} & words.keys()):
            continue
        if z <= 0.20001:
            first_layer.add(tool)
        if "interface" in kind.lower():
            interface.add(tool)
            interface_z.append(z)
        elif kind == "Support material":
            body.add(tool)
        elif tool == interface_tool and kind != "Skirt/Brim":
            raise ValueError("PETG interface tool extrudes a model feature.")
    if body != {body_tool} or interface != {interface_tool}:
        raise ValueError("Support body/interface tools disagree with the requested materials.")
    if first_layer != {body_tool} or not interface_z or min(interface_z) <= 0.20001:
        raise ValueError("PETG interface needs a PLA first-layer foundation.")
    return {"firstPETGInterfaceZ": min(interface_z), "firstLayerTools": sorted(first_layer),
            "supportBodyTools": sorted(body), "supportInterfaceTools": sorted(interface)}


def support_interface(doc, profiles):
    tool = doc["_indx"].get("supportInterfaceTool")
    if tool is None:
        return None
    entry = next((t for t in doc["_indx"]["tools"] if t["tool"] == tool), None)
    if type(tool) is not int or not 1 <= tool <= 8 or not entry or entry.get("role") != "support" or entry.get("type") != "PETG":
        raise ValueError("A support interface needs an explicitly reserved PETG tool.")
    preset = profiles["materials"].get(entry.get("materialPreset"))
    if not preset or preset["type"] != "PETG":
        raise ValueError("Choose an installed INDX PETG preset for the support interface.")
    return entry


def checked_settings(file, document=None):
    doc = read(file) if document is None else document
    s, meta = doc["settings"], doc["_indx"]
    tools = color_tools({"tools": meta["tools"]})
    if s["printer"] != PRINTER or float(s["nozzleDiameter"]) != 0.4:
        raise ValueError("Expected the INDX 8T 0.4 HF configuration.")
    profiles = read(ROOT / ".local/indx-profiles.json")
    support_interface(doc, profiles)
    for t in tools:
        preset = t.get("materialPreset", MATERIAL)
        if preset not in profiles["materials"] or profiles["materials"][preset]["type"] != "PLA":
            raise ValueError(f"Tool {t['tool']} needs an installed INDX PLA material preset: {preset}")
    process = next((p for p in profiles["processes"].values() if abs(p["layerHeight"] - float(s["layerHeight"])) < 1e-6), None)
    if process is None:
        raise ValueError("Layer height needs an exact installed INDX process; nearest-profile substitution is disabled.")
    if any("ColorMix" in t.get("materialPreset", "") for t in tools) and float(s["layerHeight"]) > 0.15:
        raise ValueError("Prusament ColorMix needs a layer height of 0.15 mm or finer.")
    expected = {t["color"].upper() for t in tools}
    if len(s["colorSlots"]) != len(tools) or {c["hex"].upper() for c in s["colorSlots"] if c} != expected:
        raise ValueError("Palette changed independently of physical tool inventory; update the inventory and re-init.")
    if s.get("infillFilament") and s["infillFilament"].upper() not in expected:
        raise ValueError("The infill filament must be one of the selected colour tools.")
    source = (Path(file).parent / s["inputFile"]).resolve()
    if sha(source) != meta["sourceSha256"]:
        raise ValueError("Source changed since init; re-init the project deliberately.")
    return doc, source, tools, process


def configure(settings, patch, expected_hash):
    """Validate a browser/chat edit and atomically update the shared project file."""
    with project_lock(settings):
        if sha(settings) != expected_hash:
            raise ValueError("Settings changed in another session. Reload the project before saving.")
        doc, _, _, _ = checked_settings(settings)
        ranges = {"sizeValue": (1, 300), "layerHeight": (0.1, 0.25), "brightness": (-100, 100),
                  "contrast": (-100, 100), "saturation": (-100, 100), "upperLayerXYScale": (1, 4), "colorSnap": (0, 50)}
        enums = {"dither": {"dlc-d30-p7", "floyd-steinberg", "riemersma", "bn-adapt-5", "none"}, "meshRepair": {"none", "fwn", "alphawrap"}}
        if set(patch) - (set(ranges) | set(enums) | {"tools", "warpPins"}):
            raise ValueError("Unsupported settings field.")
        for key, value in patch.items():
            if key in ranges:
                lo, hi = ranges[key]
                if not isinstance(value, (int, float)) or not lo <= value <= hi:
                    raise ValueError(f"{key} must be between {lo} and {hi}.")
                if key == "layerHeight" and not any(abs(p["layer_height"] - value) < 1e-6 for p in read(ROOT / "chat/processes.json")["processes"]):
                    raise ValueError("Choose an exact installed layer height.")
                doc["settings"][key] = str(value) if key in {"sizeValue", "layerHeight"} else value
            elif key in enums:
                if value not in enums[key]:
                    raise ValueError(f"Unsupported {key}.")
                doc["settings"][key] = value
            elif key == "warpPins":
                if not isinstance(value, list) or len(value) > 8:
                    raise ValueError("At most eight colour corrections are supported.")
                for pin in value:
                    if any(not re.fullmatch(r"#[0-9a-fA-F]{6}", pin.get(k, "")) for k in ("sourceHex", "targetHex")) or not 1 <= float(pin.get("sigma", 0)) <= 100:
                        raise ValueError("A colour correction needs two colours and a reach between 1 and 100.")
                doc["settings"][key] = value
            else:
                if not isinstance(value, list) or len(value) > 8:
                    raise ValueError("Provide up to eight physical tool entries.")
                chosen = color_tools({"tools": value})
                doc["_indx"]["tools"] = value
                doc["_indx"]["calibrated"] = False
                doc["settings"]["colorSlots"] = [{"hex": t["color"].upper(), "label": t["label"], "td": t.get("td") or 1} for t in chosen]
                doc["settings"]["honorTD"] = all(t.get("td") is not None for t in chosen)
        # Reject invalid profile/layer edits before publishing them.
        checked_settings(settings, doc)
        write(settings, doc)
        return {"settingsSha256": sha(settings)}


def preview_directory(settings):
    binary = ROOT / "build/bin/ditherforge-cli"
    key = hashlib.sha256((sha(settings) + str(binary.stat().st_mtime_ns)).encode()).hexdigest()
    return ROOT / ".local/previews" / key


@locked
def preview(args):
    runtime()
    settings = Path(args.settings).resolve()
    checked_settings(settings)
    digest = sha(settings)
    dest = preview_directory(settings)
    receipt = dest / "preview.json"
    if receipt.is_file() and all((dest / n).is_file() for n in ("input.mesh", "output.mesh")):
        return read(receipt)
    dest.mkdir(parents=True, exist_ok=True)
    print("Generating interactive source and dithered meshes…", file=sys.stderr, flush=True)
    run([ROOT / "build/bin/ditherforge-cli", settings, "--preview-dir", dest, "--preview-only", "--cache-dir", ROOT / ".local/cache/manifold-3.4.1"], dest / "preview.log", progress=True)
    if sha(settings) != digest or not all((dest / n).is_file() for n in ("input.mesh", "output.mesh")):
        raise ValueError("Settings changed during preview, or preview meshes were not produced.")
    result = {"settingsSha256": digest, "directory": str(dest), "input": str(dest / "input.mesh"), "output": str(dest / "output.mesh"), "validated": False}
    write(receipt, result)
    return result


def init(args):
    runtime()
    project = Path(args.project).resolve()
    src = Path(args.model).resolve()
    if not src.is_file():
        raise ValueError("Input model does not exist.")
    dest = project / "Reference" / src.name
    settings = project / "Source/Dither.json"
    if settings.exists():
        raise ValueError("Source/Dither.json exists; preserve it and choose another project or edit it deliberately.")
    if (project / "README.md").exists():
        raise ValueError("Project README already exists; choose a new project home to preserve its existing handoff.")
    inv = read(args.inventory)
    tools = color_tools(inv, [int(t) for t in args.tools.split(",")] if args.tools else None)
    if args.size <= 0:
        raise ValueError("Size must be positive.")
    if dest.exists() and sha(dest) != sha(src):
        raise ValueError("A different reference model already has this filename.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest != src:
        shutil.copy2(src, dest)
    td_configured = all(t.get("td") is not None for t in tools)
    doc = {"_ditherforge": {"url": "https://github.com/jorgeszabo/ditherforge", "sizeRelativeUnits": True},
           "settings": {"inputFile": os.path.relpath(dest, settings.parent), "printer": PRINTER, "nozzleDiameter": "0.4", "layerHeight": str(args.layer),
                        "sizeMode": "size", "sizeValue": str(args.size), "scaleValue": "1.0", "inventoryCollection": "",
                        "colorSlots": [{"hex": t["color"].upper(), "label": t["label"], "td": t.get("td") or 1} for t in tools],
                        "honorTD": td_configured, "dither": "dlc-d30-p7", "colorSnap": 5, "colorAwareCells": True,
                        "layer0AdhesionXYScale": 2, "upperLayerXYScale": 1.25, "meshRepair": "none"},
           "_indx": {"tools": tools, "sourceSha256": sha(src), "calibrated": False, "tdConfigured": td_configured,
                     "note": "Unmeasured swatches use opaque dithering; no optical accuracy claim. Support-role tools excluded."}}
    write(settings, doc)
    try:
        checked_settings(settings)
    except Exception:
        settings.unlink()
        raise
    if not (project / "README.md").exists():
        (project / "README.md").write_text("# " + project.name + "\n\nInitialized DitherForge INDX project. Not yet sliced or physically printed.\n\nEditable settings: [Source/Dither.json](Source/Dither.json). Untouched source: [Reference/](Reference/).\n")
    return {"settings": str(settings), "tools": [t["tool"] for t in tools], "calibrated": False, "tdConfigured": td_configured}


def patch_native(source, dest, process, bed_model, infill_tool, colormix=False, interface_tool=None):
    with zipfile.ZipFile(source) as z:
        p = json.loads(z.read("Metadata/PrusaSlicer3_project.json"))
        g = p["config_containers"][0]
        g["preset"]["print"] = process["print"]
        g["preset"]["tools"] = process["tools"]
        c = g["configuration"]
        c["print_settings"] = copy.deepcopy(process["printSettings"])
        c["toolprint_settings"] = copy.deepcopy(process["toolprintSettings"])
        # Limit paint penetration to the same 1.5 mm used by DitherForge export.
        c["print_settings"]["mmu_segmented_region_max_width"] = 1.5
        # Explicit PLA bed selection; a reserved PETG tool must never raise it.
        c["print_settings"]["bed_temperature_extruder"] = infill_tool
        # Palette slot one is the engine's designated backing/infill, which
        # can map to any physical tool after export palette reordering.
        for key in ("infill_extruder", "solid_infill_extruder", "perimeter_extruder"):
            c["print_settings"][key] = infill_tool
        if colormix:
            # Prusa recommends 5–10% gyroid for these translucent filaments.
            overrides = {"fill_density": {"value": 10, "is_percent": True}, "fill_pattern": "gyroid", "support_material_threshold": 55}
            c["print_settings"].update(copy.deepcopy(overrides))
            for key, value in overrides.items():
                c["toolprint_settings"][key] = [copy.deepcopy(value) for _ in range(8)]
        if interface_tool is not None:
            overrides = {"support_material": "everywhere", "support_material_buildplate_only": True,
                         "support_material_threshold": 55, "support_material_style": "snug",
                         "support_material_extruder": infill_tool, "support_material_interface_extruder": interface_tool,
                         "support_material_contact_distance": 0.0, "support_material_bottom_contact_distance": 0.0,
                         "support_material_interface_layers": 3, "support_material_bottom_interface_layers": 2,
                         "support_material_interface_spacing": 0.0,
                         "support_material_interface_speed": {"value": 35.0, "is_percent": False},
                         "first_layer_support_material_speed": {"value": 20.0, "is_percent": False},
                         "support_material_xy_spacing": {"value": 0.35, "is_percent": False},
                         "support_material_synchronize_layers": True, "dont_support_bridges": False,
                         "brim_width": 3.0, "brim_type": "outer_only",
                         "raft_layers": 5, "raft_contact_distance": 0.0, "raft_expansion": 3.0}
            c["print_settings"].update(copy.deepcopy(overrides))
            for key, value in overrides.items():
                if key in c["toolprint_settings"]:
                    c["toolprint_settings"][key] = [copy.deepcopy(value) for _ in range(8)]
        asset = Path(bed_model).resolve()
        if not asset.is_file():
            raise ValueError(f"Missing installed bed display model: {asset}")
        c["printer_settings"]["bed_custom_model"] = str(asset)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as out:
            for name in z.namelist():
                out.writestr(name, json.dumps(p).encode() if name == "Metadata/PrusaSlicer3_project.json" else z.read(name))


@locked
def build(args):
    r = runtime()
    settings = Path(args.settings).resolve()
    settings_hash = sha(settings)
    doc, source, tools, process = checked_settings(settings)
    project = settings.parent.parent
    if settings.parent.name != "Source":
        raise ValueError("Keep the settings in the project's Source folder.")
    output = project / "Print Files" / f"{project.name} - INDX8T - PLA.3mf"
    previous_hash = sha(output) if output.exists() else None
    if output.exists() and not getattr(args, "replace", False):
        raise ValueError("Current print file exists. Archive it deliberately before rebuilding.")
    work = Path(tempfile.mkdtemp(prefix="run-", dir=ROOT / ".local/runs"))
    print(f"Dithering {source.name}; work: {work}", file=sys.stderr, flush=True)
    previews = work / "previews"
    interactive = preview_directory(settings)
    intermediate = work / "dithered.3mf"
    run([ROOT / "build/bin/ditherforge-cli", settings, "--output", intermediate, "--cache-dir", ROOT / ".local/cache/manifold-3.4.1", "--preview-dir", interactive, "--debug-render", previews, "--debug-render-res", "640"], work / "dither.log", progress=True)
    info = converter(r, "inspect", intermediate)
    mapping = palette_mapping(info["filaments"], tools)
    # The converter's first reopen/slice must use the same geometry schedule
    # and paint penetration as the final project, not the 0.20 mm fallback.
    mapping.update(process=process["print"]["name"], segmentedRegionMaxWidth=1.5, infillTool=mapping["map"]["1"])
    interface = support_interface(doc, read(ROOT / ".local/indx-profiles.json"))
    if interface:
        mapping["materials"][str(interface["tool"])] = interface["materialPreset"]
        mapping["colors"][str(interface["tool"])] = interface.get("color", "#E5ECEF")
    write(work / "mapping.json", mapping)
    plan = converter(r, "plan", intermediate, "--bed", "1", "--config", work / "mapping.json")
    if plan["target"]["vendorVersion"] != read(ROOT / "chat/processes.json")["vendorVersion"]:
        raise ValueError("Converter and DitherForge profile versions differ. Refresh both using the selected slicer before proceeding.")
    write(work / "conversion-plan.json", plan)
    stage = work / "converted.3mf"
    print("Converting and validating the native INDX project…", file=sys.stderr, flush=True)
    converter(r, "convert", intermediate, "--bed", "1", "--config", work / "mapping.json", "--slicer", r["slicer"], "--output", stage, "--accept-settings-changes", log=work / "convert.log")
    native = work / "native.3mf"
    colormix = all("Prusament PLA ColorMix " in t.get("materialPreset", "") for t in tools)
    patch_native(stage, native, process, r["bedModel"], mapping["map"]["1"], colormix, interface["tool"] if interface else None)
    validation = converter(r, "validate", native, "--slicer", r["slicer"], log=work / "validate.log")
    if not validation.get("passed"):
        raise ValueError("Native reopen-and-slice did not pass.")
    counts = Counter(re.sub(r"^\[[^\]]+\]\s*", "", w) for w in validation.get("warnings", []))
    validation["warnings"] = list(counts)
    validation["warningCounts"] = dict(counts)
    gcode = next((work / "native.3mf.validation").rglob("*.gcode"))
    text = gcode.read_text()
    selected, used = gcode_tools(text)
    native_info = converter(r, "inspect", native)
    expected = sorted(native_info["usedColors"])
    allowed = {t["tool"] for t in tools} | ({interface["tool"]} if interface else set())
    if interface and interface["tool"] in expected:
        raise ValueError("Reserved PETG must not appear in model colour paint.")
    if not set(expected).issubset(used) or not set(selected).issubset(allowed):
        raise ValueError(f"G-code selections {selected} / filament-use tools {used} disagree with painted tools {expected} / inventory.")
    report = {"passed": True, "physicalPrintTested": False, "printer": "CORE One INDX 8T / 8 x 0.4 HF", "slicer": r["slicerVersion"],
              "layerHeight": process["layerHeight"], "settingsSha256": settings_hash, "sourceSha256": sha(source), "outputSha256": sha(native),
              "output": str(output), "paletteMapping": mapping, "gcodeToolSelections": selected, "gcodeFilamentTools": used, "paintedTriangles": native_info["paintedTriangles"],
              "calibrated": doc["_indx"]["calibrated"], "validation": validation, "workDirectory": str(work),
              "printTime": re.findall(r"^; estimated printing time.*$", text, re.M), "toolChanges": re.findall(r"^; total toolchanges.*$", text, re.M)}
    report["estimatedPrintTime"] = re.search(r"^; estimated printing time \(normal mode\) = (.+)$", text, re.M).group(1)
    report["filamentGrams"] = float(re.search(r"^; total filament used \[g\] = (.+)$", text, re.M).group(1))
    report["toolChangeCount"] = int(re.search(r"^; total toolchanges = (\d+)$", text, re.M).group(1))
    support_check = check_support_gcode(text, mapping["map"]["1"], interface["tool"]) if interface else None
    report["supportInterface"] = {"tool": interface["tool"], "materialPreset": interface["materialPreset"], "used": interface["tool"] in used, "gcodeCheck": support_check} if interface else None
    output.parent.mkdir(parents=True, exist_ok=True)
    if sha(settings) != settings_hash or (sha(output) if output.exists() else None) != previous_hash:
        raise ValueError("Settings or current print changed while slicing. Current output was preserved.")
    if previous_hash:
        archive = project / "Archive" / datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        archive.mkdir(parents=True)
        shutil.copy2(output, archive / output.name)
        if (project / "Source/Validation.json").is_file():
            shutil.copy2(project / "Source/Validation.json", archive / "Validation.json")
        report["archivedPreviousPrint"] = str(archive)
    pending = output.with_suffix(f".pending-{os.getpid()}")
    try:
        shutil.copy2(native, pending)
        pending.replace(output)
    finally:
        pending.unlink(missing_ok=True)
    preview_dest = project / "Reference/Previews"
    if previews.is_dir():
        preview_dest.mkdir(parents=True, exist_ok=True)
        for name in ("input_persp.png", "input_front.png", "dithered_persp.png", "dithered_front.png"):
            shutil.copy2(previews / name, preview_dest / name)
    write(project / "Source/Validation.json", report)
    write(interactive / "preview.json", {"settingsSha256": settings_hash, "directory": str(interactive), "input": str(interactive / "input.mesh"), "output": str(interactive / "output.mesh"), "validated": False})
    colour_status = "TD-informed and uncalibrated" if doc["settings"].get("honorTD") else "approximate and uncalibrated; opaque dithering is used"
    source_link = os.path.relpath(source, project).replace(" ", "%20")
    support_note = (f"PLA support bodies with PETG interface on tool {interface['tool']}; 55 degree threshold, 0 mm top/bottom contact gap, 3 top and 2 bottom interface layers, five-layer PLA/PETG raft. Confirm the actual PETG spool profile before printing." if interface else "Tool 8 is reserved for PETG in the default inventory. This project does not automatically add supports or PETG interfaces. Review model-specific supports before printing.")
    (project / "README.md").write_text(f"# {project.name}\n\n[Current print project](Print%20Files/{output.name.replace(' ', '%20')})\n\nCORE One INDX 8T, eight 0.4 mm HF tools; PrusaSlicer {r['slicerVersion']}, {process['layerHeight']} mm layers. Prusament PLA; colour tools {expected}.\n\nNative reopen and fresh slice passed. **Not physically tested.** Colour swatches are {colour_status}.\n\n[Dither settings](Source/Dither.json) · [Validation and SHA-256](Source/Validation.json) · [Input model]({source_link}) · [Previews](Reference/Previews/)\n\nSlice diagnostics are retained in Validation.json; inspect geometry/colour coverage before printing. This is an experimental dithered surface, not a calibrated optical recipe.\n\n{support_note}\n")
    with (project / "README.md").open("a") as f:
        f.write(f"\nNormal-mode estimate: {report['estimatedPrintTime']}, {report['filamentGrams']} g, {report['toolChangeCount']} tool changes.\n")
    return report


def main():
    parser = argparse.ArgumentParser(description="Local DitherForge → native Prusa CORE One INDX 8T workflow; no uploads or printing.")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("doctor")
    p = subs.add_parser("init")
    p.add_argument("model")
    p.add_argument("--project", required=True)
    p.add_argument("--inventory", default=str(ROOT / "chat/inventory.json"))
    p.add_argument("--tools", help="Comma-separated physical colour tool numbers; support-role tools are excluded.")
    p.add_argument("--size", type=float, default=50)
    p.add_argument("--layer", type=float, default=0.15)
    for cmd in ("plan", "build", "preview", "configure"):
        p = subs.add_parser(cmd)
        p.add_argument("settings")
        if cmd == "build":
            p.add_argument("--replace", action="store_true", help="Archive the previous print only after a new revision validates.")
        if cmd == "configure":
            p.add_argument("--patch", required=True, help="JSON file containing only supported settings changes.")
            p.add_argument("--expected-hash", required=True)
    for cmd in ("web", "launch"):
        p = subs.add_parser(cmd)
        p.add_argument("--port", type=int, default=8874)
    p = subs.add_parser("remote")
    p.add_argument("--device", required=True, help="Exact Tailscale DNS name of your travelling Mac.")
    p.add_argument("--https-port", type=int, default=8447)
    p = subs.add_parser("validate")
    p.add_argument("file")
    args = parser.parse_args()
    if args.command == "doctor":
        result = {**runtime(), "engine": run([ROOT / "build/bin/ditherforge-cli", "--version"]), "processes": read(ROOT / "chat/processes.json"), "inventory": read(ROOT / "chat/inventory.json")}
    elif args.command == "init":
        result = init(args)
    elif args.command == "plan":
        doc, source, tools, process = checked_settings(args.settings)
        result = {"source": str(source), "layerHeight": process["layerHeight"], "tools": tools, "calibrated": doc["_indx"]["calibrated"], "status": "Planning only; existing print validation is recorded separately in Source/Validation.json"}
    elif args.command == "build":
        result = build(args)
    elif args.command == "preview":
        result = preview(args)
    elif args.command == "configure":
        result = configure(args.settings, read(args.patch), args.expected_hash)
    elif args.command == "web":
        from hybrid import serve
        serve(args.port)
        return
    elif args.command == "launch":
        from hybrid import launch
        result = launch(args.port)
    elif args.command == "remote":
        from hybrid import remote_access
        result = remote_access(args.device, args.https_port)
    else:
        r = runtime()
        result = converter(r, "validate", Path(args.file).resolve(), "--slicer", r["slicer"])
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        print(f"dither-chat: {exc}", file=sys.stderr)
        sys.exit(1)
