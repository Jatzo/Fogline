# Phase 4 cost estimate draft (numbers only)

Rewritten 2026-11-14. The first version used `claude -p`'s cost figure, which priced claude-haiku-5-5 at Opus 5.5 rates. These figures are list prices (`fogline/pricing.py`, read 2026-11-14), applied to the token counts measured in M19.

## Per call, at the M19 token counts (503 calls)

| Model | Per call |
|---|---|
| claude-haiku-5-5 | $0.0041 |
| claude-sonnet-5-5 | $0.0813 |
| claude-opus-5-5 | $0.1627 |

The token counts were measured on Haiku. Sonnet and Opus may think for more or fewer tokens on the same observation.

## One run: seed 1-3, 400 ticks, five live rulers

Calls per civ over 400 ticks, from the M19 rates per 100 ticks and contact at about tick 50: about 326 (1,519 to 1,738 for five civs).

| Roster | Haiku / Sonnet / Opus civs | Notional cost |
|---|---|---|
| All Haiku (`--models claude-haiku-5-5`) | 5 / 0 / 0 | about $6 to $7 |
| Seed 1 rotation | 1 / 2 / 2 | about $160 |
| Seed 2 rotation | 2 / 1 / 2 | about $135 |
| Seed 3 rotation | 2 / 2 / 1 | about $109 |

## The stopped all-Haiku run
`runs/p4-live-s1` (gitignored), stopped at tick 40: 124 calls with usage. Reported $9.40; at Haiku list prices $0.23 (all cache writes 5-minute) to $0.27 (all 1-hour). Its rows don't record the split, and they don't reproduce the reported figure at Opus rates with 1-hour writes ($10.70), so some of its writes were 5-minute.

## Mock run for comparison
`runs/p4-mock-s1`, seed 1, 400 ticks, five mock rulers: 1,334 calls (1,089 decide, 245 reflect), no cost.
