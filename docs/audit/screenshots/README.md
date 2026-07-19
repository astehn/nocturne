# Pipeline-audit screenshots

Reference artifacts for the [pipeline audit](../PIPELINE_AUDIT.md). One
subfolder per step, numbered to match the roadmap.

## Convention

```
docs/audit/screenshots/
  01-import/        02-crop/        03-background/   ...
```

Inside each step folder, name files by what they show:

- `panel.png`        — the step's right-hand panel (controls)
- `image.png`        — the canvas / preview at that step
- `<thing>.png`      — anything specific worth capturing (e.g. `metadata.png`,
                       `before-after.png`, `slider-extremes.png`)

Add a trailing note if you have variants: `panel-strong.png`, `image-lp.png`.

These are committed as part of the audit record so findings can be traced back
to exactly what the UI looked like at the time. If the repo ever feels heavy
with binaries, we can move this tree to `.gitignore` instead — say the word.
