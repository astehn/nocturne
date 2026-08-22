# Seestar training-pair generator

Nocturne can generate model-training data from Seestar subframes without manually creating noisy and clean stacks.

The generator reuses Nocturne’s FITS loading, demosaic, registration, robust per-frame normalisation, warping, and integration code. It creates:

- a noisy shallow stack;
- a clean deeper stack;
- a shared coverage map;
- a reproducible manifest listing every source frame;
- optional overlapping `.npz` training tiles.

The noisy and clean frame lists are disjoint. One additional reference frame is used for registration only and is excluded from both stacks.

## Prototype command

Start with one sensor, one filter, one exposure length, and a small number of groups:

```text
python scripts/generate_training_pairs.py \
  --input /Volumes/Work2/Images/Astro/Training \
  --output /Volumes/Work2/Images/Astro/TrainingPairs \
  --sensor s30 \
  --filter LP \
  --exposure 10 \
  --input-counts 8,16,32 \
  --target-count 128 \
  --pairs-per-group 4 \
  --tiles \
  --max-groups 2 \
  --workers 4
```

For S50, repeat with `--sensor s50`. The default grouping separates targets by capture night, filter, exposure, and sensor. Mosaic-like groups are skipped unless `--include-mosaics` is supplied.

The first run should use `--max-groups 1` or `2` so the generated output and model-input convention can be inspected before processing the whole archive.

## Output layout

```text
TrainingPairs/
  s30_M16_2026-08-09_LP_10s/
    pair_0000_in8_target128/
      input.fits
      target.fits
      coverage.fits
      manifest.json
      tiles/
        tile_000000.npz
        ...
```

`input.fits` and `target.fits` are float32 RGB images with the same geometry and shared scale. `coverage.fits` contains the minimum fractional coverage of the two stacks. A tile archive contains `input`, `target`, `coverage`, and the tile `origin`.

The manifest records the source frame lists, reference frame, stack method, kappa, scaling factor, rejected registrations, random seed, sensor, target, filter, exposure, and shape. It is the provenance boundary for later model training.

## Important conventions

- The default output is **linear**. Use `--stretch 0.5` only when deliberately training a post-stretch denoiser.
- The default integrator is `average` for a fast prototype. `--method sigma_clip` uses the same two-pass sigma clipping as the normal stacker but is substantially more expensive.
- Auto-cropping is intentionally disabled so both pair members share the reference canvas. Use the coverage map to exclude the low-coverage border during training.
- The clean stack’s peak establishes the shared pair scale. The manifest reports any input or target clipping caused by that scale.
- Pair generation is deterministic for a fixed seed and group metadata.
- The M31 Mosaic group should remain excluded for the first prototype because it contains multiple pointings. Split it into panels before using it for training.

## Suggested first experiments

### S30 denoiser

Use 10-second LP groups such as M16, M17, M8, M45, NGC 6888, and NGC 6992. Hold out at least one entire target for evaluation.

### S50 denoiser

Use M42, SH2-142, NGC 7023, NGC 6995, and M101. Keep exposure lengths homogeneous for the first run.

### Background model

Use the generated deep stacks as clean bases, add synthetic low-frequency gradients, and train a model to predict the background field rather than directly rewrite the corrected image.
