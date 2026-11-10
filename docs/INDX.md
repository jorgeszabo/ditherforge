# INDX implementation and improvement targets

This is an adaptation of Tim Newsome's MIT-licensed DitherForge, not iDither's
proprietary source. The existing converter stays a separate maintained AGPL
application, invoked through its CLI. Generated profile data comes from Prusa
presets resolved by PrusaSlicer, with its source/version/hash recorded.

## What is implemented

- CORE One INDX 8T registry entry for eight 0.4 mm HF tools. Actual alpha13
  geometry defaults determine voxel width and first-layer/layer heights.
- Native alpha13 3MF delivery through the maintained converter, with fresh
  final reopen/slice and per-tool G-code filament-use verification.
- Reordered palette mapping, sparse physical tool numbers, eight-colour
  capability, and exclusion of reserved/unknown spools.
- Local CLI callable from chat, a source/tool snapshot, hashes, previews,
  protected current outputs and the parent project's folder convention.
- Draco-compressed GLB support and native geometry dependencies. The setup
  pins Manifold 3.4.1 used by upstream release CI instead of Homebrew's newer
  library. Full-suite results and actual output tests are in Validation.json.

## What differentiates the colour engines

[iDither](https://idither.com/wiki.php) describes calibrated, ordered thin-layer
and inner/outer-wall recipes. Its calibration descriptions on the
[shared fish job](https://idither.com/job?U3ZpXAMBx&row=0) include photographed
patches at a specific wall stack and layer height, with other combinations
explicitly unvalidated. These measurements are a concrete advantage for its
supported filament/process combinations. A predicted preview is not a
guarantee for our Prusament spools and INDX process.

[DitherForge](https://github.com/rtwfroody/ditherforge) samples textured 3D
surfaces into printable cells, applies perceptual colour selection/error
diffusion, clips the mesh, and paints physical filament assignments. It has
TD/translucency models and swatch generators already. It is not equivalent
to a measured optical layer-recipe library. Matching a hex swatch or entering
an approximate TD does not establish colour accuracy.

The first goal is better integration for this printer. Better physical colour
than another program remains unproven. AI-assisted development does not
establish either program's print quality.

## Next improvements, with measurable acceptance criteria

The full local Go suite currently retains one failing upstream regression:
`TestSampledMatchesInput/cube_dither` reports top/bottom depth-hole coverage
of approximately 0.20% / 0.11%, against its 0.10% limit. The same measurements
reproduce in pristine upstream commit `4d3552a`; no thresholds were loosened.
All internal packages and the targeted INDX/mapping tests pass. This is an
experimental engine with an inherited surface-coverage issue, not a fully
green upstream suite. Alpha13 also logs Voronoi diagnostics on fine painted
regions in our test; native reopen/slicing and per-tool material use pass.
Inspect previews and use a small physical test before a long textured print.

1. Print measured swatches using our exact PLA spools, wall stack and layer
   heights. Photograph under controlled lighting with a reference target;
   fit profiles and assess held-out patches instead of reusing training swatches
   as proof. Galaxy/glitter filaments need particular care in the measurements.
2. Compare the same licensed textured model, size, palette and process through
   both tools. Compare physical photos and colour error, tool changes, grams
   and sliced/observed time. Different gamut or layer height invalidates a
   simple accuracy/speed comparison.
3. Add a colour-versus-time candidate search. First use existing cell size,
   colour-snap and palette selection controls, preserving geometry and stating
   any loss of colour detail. Use actual INDX slice times, not a generic
   multiplier or a promise that extra tools always save time.
4. Add measured wall/layer recipes only after the simple spatial baseline is
   physically characterized. Respect minimum printable regions and exact
   layer schedules; validate surface coverage and watertightness after export.

Support interfaces remain an independent, model-specific print setting. PETG
should not be blended into PLA colour pixels. The default inventory reserves
tool 8, but supports must be reviewed before adding them to a textured object.
