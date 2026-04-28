# Scheduling and Energy Rules

Clutch can enforce conversion windows with manual rules, electricity-price rules, or both.

## Manual schedule rules

Option:

- `--schedule RULE`

Examples:

- `mon-fri 22:00-08:00`
- `00:00-06:00`

Interpretation is controlled by:

- `--schedule-mode allow` (convert only during listed windows)
- `--schedule-mode block` (block during listed windows)

## Price-based schedule

Options:

- `--price-provider energy_charts|entsoe`
- `--price-country <zone>`
- `--price-limit <eur_per_mwh>`
- `--price-cheapest-hours <N>`
- `--entsoe-api-key <key>` (when provider requires it)

Strategies:

- Threshold mode (with `--price-limit`)
- Cheapest-N-hours mode (with `--price-cheapest-hours`)

## Combining manual + price rules

Set both manual and price options, then choose arbitration with:

- `--schedule-priority manual_first`
- `--schedule-priority price_first`
- `--schedule-priority both_must_allow`

## What happens when blocked

`--schedule-pause-behavior` controls runtime behavior:

- `block_new`: do not start new jobs
- `pause_running`: pause active jobs when entering blocked window

## Example

```bash
clutch --serve \
  --schedule "mon-fri 00:00-07:00" \
  --schedule-mode allow \
  --price-provider energy_charts \
  --price-country ES \
  --price-cheapest-hours 6 \
  --schedule-priority both_must_allow \
  --schedule-pause-behavior block_new
```
