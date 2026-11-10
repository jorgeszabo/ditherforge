# Local INDX fork

Read `docs/CHAT_WORKFLOW.md` before printing/converting. Use `chat/dither-chat`
for chat work. This fork lives only in `3D-Printing/Tools/ditherforge`.

The browser workspace starts with `dither-chat launch` (loopback only). It uses
the same `configure`, `preview` and `build` functions as chat. Preserve shared
settings hashes and project locks: never overwrite another session's edits.
`build --replace` archives the previous print only after the new revision
validates. Rebuild the browser using `cd frontend && npm run build:hybrid`.

- Default hardware: CORE One INDX 8T, eight 0.4 mm HF tools; alpha13.
- Run `chat/dither-chat doctor` first. Rebuild with `scripts/build-indx.sh` after
  Go/profile changes; refresh profiles with `scripts/refresh-indx.cjs` after
  installed presets change. Do not silently switch slicer versions.
- Keep upstream MIT attribution. The independent chat integration uses the
  existing converter via its CLI; do not copy its AGPL implementation here.
- Palette entries must correspond to explicitly configured real spools. Never
  invent loaded colours, TD measurements, or physical print success. Exclude
  reserved support tools from the optical colour palette.
- Preserve palette-to-physical-tool mappings after infill/palette reordering.
  Native colour paint is deliberate. Single-colour volumes inherit object tools.
- Match voxel width and layer schedule to the native print process. Reopen and
  slice final native files; check actual G-code and tool use, not exit code alone.
- Sources and generated user models never go into git. Trial output, dependencies,
  logs and caches belong in ignored `.local/`. Project outputs use the parent
  AGENTS.md layout: README, Print Files, Source and Reference as needed.
- Push checked improvements to this user's fork; no upstream PR without request.
- Better colour than another tool requires comparative physical calibration.
