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
official Prusa alpha13, an isolated data directory, CGAL, pinned Manifold 3.4.1,
and pinned Draco-C. Downloads, native libraries, logs and models are ignored
under `.local/`; compiler/tool dependencies use Homebrew's ordinary locations.

Re-query installed alpha13 presets using `node scripts/refresh-indx.cjs`, then
rebuild using `scripts/build-indx.sh --test`. The checked-in printer registry
contains only geometry/process data. Full resolved native configuration stays
in `.local/indx-profiles.json`. Never reuse alpha14 presets in alpha13's data
directory. The isolated launcher prevents forced preset downgrades from touching
the user's current PrusaSlicer installation.

## Inventory

`chat/inventory.json` records the last confirmed spools, not a live printer
query: tools 1 white PLA, 2 black PLA, 3 orange PLA, 4 blue PLA; 5–7 unknown;
8 Urban Gray PETG reserved for supports. These are approximate sRGB swatches,
not calibrated measurements. TD is null, so the chat workflow disables
translucency compensation and uses opaque spatial dithering initially.

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
