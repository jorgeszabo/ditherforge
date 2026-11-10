# Local browser + chat workspace

Run **`dither-chat launch`**, then open http://127.0.0.1:8874/.
The server runs in the background on the host Mac. `dither-chat web` runs it
in the foreground. For automatic start after login and crash recovery, run
`python3 scripts/install-web-service.py`; this installs the user LaunchAgent
`com.ditherforge.indx-studio`. Without that service, use `launch` after reboot.
Logs/PID are in `.local/web.log` and `.local/web.pid`. Rebuild browser assets
with `cd frontend && npm run build:hybrid`; reload the browser after changes.
The setup script installs/builds the browser and CLI together.

All assets and processing are local, with no external model upload or account.
The server binds to `127.0.0.1` and accepts same-origin changes only. It serves
only its app assets, generated
preview meshes and validated project downloads, not arbitrary local files.

## Access from either Mac, including while travelling

The Mac mini can host the studio behind the existing Tailscale connection.
Both Macs need Tailscale connected; the mini must be awake, logged in and
online. The same private HTTPS address then works at home or away. All slicing
and file storage remain on the mini. This does not require public hosting or
router port forwarding.

Configure an existing travelling Mac owned by the same Tailscale account:

```sh
dither-chat remote --device YOUR-MACBOOK-DNS-NAME --https-port 8447
```

The command prints the HTTPS address. It uses a dedicated Tailscale Serve port,
checks that the port is unused by another app, and verifies existing routes
remain unchanged. It stores the approved origin, owner identity and the two
Macs' Tailscale addresses in ignored `.local/remote-access.json`. The backend
requires the authenticated Serve identity and an approved device address;
other tailnet devices are denied. Funnel/public requests are rejected. Host,
forwarding and same-origin checks remain enforced. No Tailscale-wide policy or
sharing changes are made. Re-run the command after replacing/re-registering a
Mac so its addresses can be deliberately updated.

[Tailscale Serve documentation](https://tailscale.com/docs/features/tailscale-serve)
describes private access and authenticated identity headers. The app remains
loopback-bound so those headers can be trusted only from the local proxy.

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
   in alpha14 and checks per-tool G-code filament use. Only a passing candidate
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

The inherited geometry regression and alpha14 fine-region diagnostics described
in [INDX.md](INDX.md) are unchanged. Physical calibration and a small test print
are still needed to assess colour accuracy. Adding a browser does not create
measured optical recipes or regional painting capabilities.

## Studio appearance

The browser workspace has warm light controls around dark linked 3D canvases.
Use **Compare**, **Source** or **Result** to change the preview layout. Individual
colour-correction chips can be removed without clearing the other corrections.
The eight physical tool assignments remain editable; the palette strip lists only
selected colour tools. Print estimates/downloads are marked as previous when edits
are unsaved. The visual system and reference capture are in [DESIGN.md](DESIGN.md).

## Vercel hosting

The current service is hosted on the Mac mini, with private Tailscale HTTPS travel
access. No Vercel deployment has been made. A normal Vercel website can host this
Svelte interface, but the current relative API endpoints require the Python/native
pipeline and project filesystem. A frontend-only deployment would not be functional.

Recommended cloud extension: an authenticated Vercel site and durable job state,
private model/result storage, and an outbound worker on the mini that claims jobs,
runs the same locked/validated pipeline, and returns results. This allows travel
access without Tailscale on the browsing device; offline jobs wait for the worker.
It requires deliberate authentication, scoped worker credentials, upload limits,
retry/idempotency and shared-settings conflict handling. Preserve the current local
workflow until that complete path has been implemented and tested. Migrating the
native dependencies and slicer to a Linux/container worker is a separate option.

[Vercel container runtime](https://vercel.com/docs/functions/runtimes/container)
and [direct uploads](https://vercel.com/docs/vercel-blob/client-upload) cover
platform options; a cloud migration should confirm actual job resource needs.
