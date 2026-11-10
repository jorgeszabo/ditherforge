# DitherForge through chat

Home: `3D-Printing/Tools/ditherforge`. Fork:
https://github.com/jorgeszabo/ditherforge. Upstream remains the `upstream`
remote. The user chooses material, colour, size, supports and physical-print
decisions in chat; this tool handles repeatable geometry, mapping and validation.

For the browser + chat workspace, run `dither-chat launch` and read
[HYBRID.md](HYBRID.md). Both interfaces use the same project settings and
native validation. The local URL is http://127.0.0.1:8874/.

## Setup and health

On this Mac, run `chat/dither-chat doctor`. Reproduce the local installation
with `scripts/setup-indx.sh` (Apple silicon macOS, Homebrew, Python 3, Node 24+).
The maintained sibling `../3mf-colour-converter` is required. Setup uses
official Prusa alpha14, an isolated data directory, CGAL, pinned Manifold 3.4.1,
and pinned Draco-C. Downloads, native libraries, logs and models are ignored
under `.local/`; compiler/tool dependencies use Homebrew's ordinary locations.

Re-query installed alpha14 presets using `node scripts/refresh-indx.cjs`, then
rebuild using `scripts/build-indx.sh --test`. The checked-in printer registry
contains only geometry/process data. Full resolved native configuration stays
in `.local/indx-profiles.json`. Never reuse alpha14 presets in alpha14's data
directory. The isolated launcher prevents forced preset downgrades from touching
the user's current PrusaSlicer installation.

## Inventory

`chat/inventory.json` records the prepared Prusament ColorMix loadout in Prusa's
recommended order: T1 Cyan, T2 Magenta, T3 Yellow, T4 White, T5 Black,
T6 Gold Glitter, T7 Silver Glitter. T8 is reserved for clear PETG (brand not
specified), excluded from the colour palette. This is not a live printer query.
The swatches come from official ColorMix presets, not measured print patches.
TD remains null, so this workflow uses uncalibrated spatial dithering rather
than Prusa's calibrated native ColorMix layer recipes.

Update this inventory or pass a separate `--inventory FILE` when the user
confirms new spools. There may be 1–8 colour tools, with non-contiguous tool
numbers. Only PLA colour entries are currently accepted. Reserve a tool by
setting `role: "support"`; it will not enter the colour palette. Do not assume
eight installed tools mean eight loaded colours. The build does not
automatically configure PETG interfaces or supports.

## A project

From this tool folder:

```sh
chat/dither-chat init /absolute/model.glb \
  --project '../../Project Name' --size 50 --layer 0.15
chat/dither-chat plan '../../Project Name/Source/Dither.json'
chat/dither-chat build '../../Project Name/Source/Dither.json'
```

`--size` is the longest dimension in mm. `--tools 1,3,4` selects a subset of
known colour tools. Available layer heights must exactly match the resolved
INDX processes (currently 0.10, 0.15, 0.20, 0.25 mm); nearest-height substitution
is rejected. The first layer is 0.20 mm and uses a 0.50 mm base line width;
normal colour cells use the process's 0.45 mm width. User cell multipliers are
stored in the settings (initially 2x on the first layer, 1.25x above it).

`init` preserves a reference copy and writes editable DitherForge settings plus
a physical-tool snapshot in `Source/Dither.json`. This is compatible with the
upstream JSON format; the extra `_indx` metadata is for the chat wrapper.
Changing the locked palette without updating the tool snapshot is rejected.
Do not overwrite unrelated project README files: initialize a new project home.

`build` generates a painted mesh, reads its actual exported palette, maps
colours back to tools after any infill reordering, and uses the maintained
converter's `inspect`, `plan`, `convert` and `validate` CLI. It applies the exact
native INDX print/tool-print process before the final fresh validation. The
1.5 mm paint-depth limit matches DitherForge's export. PLA bed selection is
explicit, so a reserved high-temperature spool cannot select the bed target.
It rejects output when painted tools are missing from actual G-code filament
use, or G-code selects tools outside the configured colour inventory.

On success:

```text
Project Name/
  README.md
  Print Files/Project Name - INDX8T - PLA.3mf
  Source/Dither.json
  Source/Validation.json
  Reference/model.glb
  Reference/Previews/
```

The project contains eight physical HF tools and only the intended active
colours. Single-material child volumes inherit their object's selection;
multi-material surface paint is deliberate. Existing current print files are
protected: archive a useful superseded revision deliberately before rebuilding,
or use `build --replace` to archive it after a new candidate validates.
Native reopen/slice and G-code generation are mandatory. Slicing is not a
physical colour/adhesion test. No model upload, print submission or automatic
account activity occurs.

Revalidate a relocated file with `chat/dither-chat validate /absolute/file.3mf`.
This explicit diagnostic command writes a `.validation` directory beside its
input; run it on a temporary copy under `.local/` when keeping project roots
clean. The ordinary build already keeps all such debris in `.local/runs/`.

## Verification

`scripts/build-indx.sh --test` checks the engine's registry/settings/pipeline
plus chat mapping regressions. `--test-all` additionally builds/checks the
frontend and runs the full Go suite. Inspect the compact validation record and
retained slice warnings. Use actual sliced times and tool changes when
comparing candidates; dithering may be expensive even for a small object.

## Prusament ColorMix and exact first-slice settings

An inventory entry may include `materialPreset` naming an installed INDX PLA
preset. It is preserved through palette reordering and browser saves. ColorMix
jobs require 0.15 mm or finer layers and use 10% gyroid throughout the print and
all tools. The UI offers only compatible layer heights. Native material settings
come from the resolved preset, including 215 C / 50 C / 4 mm3/s for the installed
ColorMix profiles. Do not substitute ordinary PLA cooling or flow settings.

The first converter validation now uses the exact selected native process,
1.5 mm segmented-region width and the designated physical infill/default tool.
It no longer slices a default 0.20 mm intermediate before applying those values.
The current default and validation runtime is alpha14, vendor 1.0.23; explicit
legacy alpha13 validation remains supported by the converter. Existing projects
retain their own recorded validation version until rebuilt.

A selected backing/infill tool does not establish a completely white interior:
painted regions can extend into infill. Inspect actual per-feature G-code before
claiming an optical backing or calibrated colour. The turtle test exercises all
seven tools and has no support extrusion; it remains physically untested.
