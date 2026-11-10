#!/usr/bin/env python3
"""Local INDX orchestration. DitherForge and the maintained 3MF converter run as CLIs."""
import argparse
from collections import Counter
import copy
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
    path.write_text(json.dumps(data, indent=2) + "\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(args, log=None, json_output=False):
    p = subprocess.run([str(x) for x in args], capture_output=True, text=True)
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
    if version != "3.0.0-alpha13":
        raise ValueError(f"Expected alpha13, got {version}. Do not silently change slicing versions.")
    if not (ROOT / "build/bin/ditherforge-cli").is_file():
        raise ValueError("Build the engine with scripts/build-indx.sh first.")
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
        mapping["materials"][str(t["tool"])] = MATERIAL
        mapping["colors"][str(t["tool"])] = t["color"].upper()
    return mapping


def gcode_tools(text):
    selections = sorted({int(t) + 1 for t in re.findall(r"^[ \t]*T(\d+)\b", text, re.M)})
    amounts = re.findall(r"^; filament used \[mm\] = (.+)$", text, re.M)
    if not amounts:
        raise ValueError("G-code has no per-tool filament-use summary.")
    used = [i + 1 for i, amount in enumerate(amounts[-1].split(",")) if float(amount) > 0]
    return selections, used


def checked_settings(file):
    doc = read(file)
    s, meta = doc["settings"], doc["_indx"]
    tools = color_tools({"tools": meta["tools"]})
    if s["printer"] != PRINTER or float(s["nozzleDiameter"]) != 0.4:
        raise ValueError("Expected the INDX 8T 0.4 HF configuration.")
    profiles = read(ROOT / ".local/indx-profiles.json")
    process = next((p for p in profiles["processes"].values() if abs(p["layerHeight"] - float(s["layerHeight"])) < 1e-6), None)
    if process is None:
        raise ValueError("Layer height needs an exact installed INDX process; nearest-profile substitution is disabled.")
    expected = {t["color"].upper() for t in tools}
    if len(s["colorSlots"]) != len(tools) or {c["hex"].upper() for c in s["colorSlots"] if c} != expected:
        raise ValueError("Palette changed independently of physical tool inventory; update the inventory and re-init.")
    source = (Path(file).parent / s["inputFile"]).resolve()
    if sha(source) != meta["sourceSha256"]:
        raise ValueError("Source changed since init; re-init the project deliberately.")
    return doc, source, tools, process


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


def patch_native(source, dest, process, bed_model, infill_tool):
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
        asset = Path(bed_model).resolve()
        if not asset.is_file():
            raise ValueError(f"Missing installed bed display model: {asset}")
        c["printer_settings"]["bed_custom_model"] = str(asset)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as out:
            for name in z.namelist():
                out.writestr(name, json.dumps(p).encode() if name == "Metadata/PrusaSlicer3_project.json" else z.read(name))


def build(args):
    r = runtime()
    settings = Path(args.settings).resolve()
    doc, source, tools, process = checked_settings(settings)
    project = settings.parent.parent
    if settings.parent.name != "Source":
        raise ValueError("Keep the settings in the project's Source folder.")
    output = project / "Print Files" / f"{project.name} - INDX8T - PLA.3mf"
    if output.exists():
        raise ValueError("Current print file exists. Archive it deliberately before rebuilding.")
    work = Path(tempfile.mkdtemp(prefix="run-", dir=ROOT / ".local/runs"))
    print(f"Dithering {source.name}; work: {work}", file=sys.stderr, flush=True)
    previews = work / "previews"
    intermediate = work / "dithered.3mf"
    run([ROOT / "build/bin/ditherforge-cli", settings, "--output", intermediate, "--cache-dir", ROOT / ".local/cache/manifold-3.4.1", "--debug-render", previews, "--debug-render-res", "640"], work / "dither.log")
    info = converter(r, "inspect", intermediate)
    mapping = palette_mapping(info["filaments"], tools)
    write(work / "mapping.json", mapping)
    plan = converter(r, "plan", intermediate, "--bed", "1", "--config", work / "mapping.json")
    if plan["target"]["vendorVersion"] != read(ROOT / "chat/processes.json")["vendorVersion"]:
        raise ValueError("Converter and DitherForge profile versions differ. Refresh both using isolated alpha13 before proceeding.")
    write(work / "conversion-plan.json", plan)
    stage = work / "converted.3mf"
    print("Converting and validating the native INDX project…", file=sys.stderr, flush=True)
    converter(r, "convert", intermediate, "--bed", "1", "--config", work / "mapping.json", "--slicer", r["slicer"], "--output", stage, "--accept-settings-changes", log=work / "convert.log")
    native = work / "native.3mf"
    patch_native(stage, native, process, r["bedModel"], mapping["map"]["1"])
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
    if not set(expected).issubset(used) or not set(selected).issubset({t["tool"] for t in tools}):
        raise ValueError(f"G-code selections {selected} / filament-use tools {used} disagree with painted tools {expected} / inventory.")
    report = {"passed": True, "physicalPrintTested": False, "printer": "CORE One INDX 8T / 8 x 0.4 HF", "slicer": "3.0.0-alpha13",
              "layerHeight": process["layerHeight"], "sourceSha256": sha(source), "outputSha256": sha(native),
              "output": str(output), "paletteMapping": mapping, "gcodeToolSelections": selected, "gcodeFilamentTools": used, "paintedTriangles": native_info["paintedTriangles"],
              "calibrated": doc["_indx"]["calibrated"], "validation": validation, "workDirectory": str(work),
              "printTime": re.findall(r"^; estimated printing time.*$", text, re.M), "toolChanges": re.findall(r"^; total toolchanges.*$", text, re.M)}
    report["estimatedPrintTime"] = re.search(r"^; estimated printing time \(normal mode\) = (.+)$", text, re.M).group(1)
    report["filamentGrams"] = float(re.search(r"^; total filament used \[g\] = (.+)$", text, re.M).group(1))
    report["toolChangeCount"] = int(re.search(r"^; total toolchanges = (\d+)$", text, re.M).group(1))
    output.parent.mkdir(parents=True, exist_ok=True)
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
    colour_status = "TD-informed and uncalibrated" if doc["settings"].get("honorTD") else "approximate and uncalibrated; opaque dithering is used"
    (project / "README.md").write_text(f"# {project.name}\n\n[Current print project](Print%20Files/{output.name.replace(' ', '%20')})\n\nCORE One INDX 8T, eight 0.4 mm HF tools; PrusaSlicer alpha13, {process['layerHeight']} mm layers. Prusament PLA; colour tools {selected}.\n\nNative reopen and fresh slice passed. **Not physically tested.** Colour swatches are {colour_status}.\n\n[Dither settings](Source/Dither.json) · [Validation and SHA-256](Source/Validation.json) · [Original model](Reference/{source.name.replace(' ', '%20')}) · [Previews](Reference/Previews/)\n\nSlice diagnostics are retained in Validation.json; inspect geometry/colour coverage before printing. This is an experimental dithered surface, not a calibrated optical recipe.\n\nTool 8 is reserved for PETG in the default inventory. This project does not automatically add supports or PETG interfaces. Review model-specific supports before printing.\n")
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
    for cmd in ("plan", "build"):
        p = subs.add_parser(cmd)
        p.add_argument("settings")
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
