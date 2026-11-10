#!/usr/bin/env python3
"""Seed isolated alpha14 presets without overwriting existing local files."""
from pathlib import Path
import shutil
root = Path(__file__).resolve().parents[1]
dest = root / '.local/prusa-alpha14-data/presets'
installed = Path.home() / 'Library/Application Support/PrusaSlicer3-dev/presets'
if not dest.exists() and installed.is_dir():
    shutil.copytree(installed, dest)
source = root.parent.parent / 'ColorMix/Source/Filament Presets'
user = dest / 'user/prusa-research-fff/PrusaResearch'
if source.is_dir():
    user.mkdir(parents=True, exist_ok=True)
    for preset in source.glob('*.yaml'):
        target = user / preset.name
        if not target.exists():
            shutil.copy2(preset, target)
