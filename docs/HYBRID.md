# Local browser + chat workspace

Run **`dither-chat launch`**, then open http://127.0.0.1:8874/.
The server runs in the background on this Mac. It is not a login item; use
`launch` again after reboot. `dither-chat web` runs it in the foreground.
Logs/PID are in `.local/web.log` and `.local/web.pid`. Rebuild browser assets
with `cd frontend && npm run build:hybrid`; reload the browser after changes.
The setup script installs/builds the browser and CLI together.

All assets and processing are local, with no external model upload or account.
The server binds to `127.0.0.1` and accepts same-origin changes only. Other
devices cannot open it directly. It serves only its app assets, generated
preview meshes and validated project downloads, not arbitrary local files.

## Workflow

1. Open an existing DitherForge project, or import a new model into a new project
   home under `3D-Printing`. The original is copied into `Reference/`. GLB is
   convenient for a textured single-file model; OBJ/DAE with external textures
   should be packaged in ZIP. Browser transfers are limited to 512 MiB.
2. Rotate, pan and zoom the linked source/dithered views. Choose the intended
   colour spools, size and exact INDX layer height. All eight slots are editable;
   unknown slots remain unavailable until assigned. PETG stays out of the PLA
   colour palette. These are project assignments, not live printer inventory.
3. Adjust the dither pattern, cell size, colour snap, brightness/contrast/
   saturation or mesh repair. Use the eyedropper to sample a source colour and
   add a colour correction. Corrections remap similar colours throughout the
   model; they are not a spatial paint mask. Up to eight are supported.
4. **Save settings** updates `Source/Dither.json`, which chat reads too.
   **Update preview** saves and generates an interactive mesh without slicing.
   Unsaved/changed output is labelled as needing an update. Appearance is
   uncalibrated; a preview does not establish print readiness.
5. **Save print revision** generates the actual native 3MF, reopens and slices
   in alpha13 and checks per-tool G-code filament use. Only a passing candidate
   replaces the current print. The prior 3MF and validation record are retained
   in a dated `Archive/` folder. Failed generation preserves the current print.
   Download the current validated 3MF, or the clearly labelled previous result.

Print times/grams/tool changes are actual slicer estimates. Old estimates are
labelled as previous results when settings change. Slice warnings remain
available in the interface. Supports and PETG interfaces are reviewed separately;
the app never submits a print automatically.

## The same operations in chat

```sh
dither-chat preview '/absolute/Project/Source/Dither.json'
dither-chat configure '/absolute/Project/Source/Dither.json' \
  --patch options.json --expected-hash CURRENT_SETTINGS_SHA256
dither-chat build '/absolute/Project/Source/Dither.json' --replace
```

`configure` accepts supported numeric/colour/tool controls. Browser and chat
use the same validator, exact settings hash and project lock. A stale browser
cannot silently overwrite a newer chat edit; reload the project to fetch it.
Build/preview jobs reject concurrent changes. `build --replace` explicitly
enables validated archiving/replacement; ordinary `build` still protects an
existing current file. Interactive caches and job logs remain in ignored
`.local/`. Current deliverables follow the parent project's folder convention.

The inherited geometry regression and alpha13 fine-region diagnostics described
in [INDX.md](INDX.md) are unchanged. Physical calibration and a small test print
are still needed to assess colour accuracy. Adding a browser does not create
measured optical recipes or regional painting capabilities.
