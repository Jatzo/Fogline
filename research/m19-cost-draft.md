# M19 cost draft (numbers only)

Seed 1, 150 ticks, Verdance and Saltreach as live rulers on `claude-haiku-5-5` through `claude -p --safe-mode`, the other three civs scripted traders. Costs are the notional `total_cost_usd` reported per call, run on the plan login, not billed. Raw outputs stay in `runs/` (gitignored). Both runs replay exactly to their tick-148 snapshots.

## Per run

| Run | Placement | LLM calls | Failed calls | Notional cost | Cost per call | Output tokens per call | Reply characters per call |
|---|---|---|---|---|---|---|---|
| live-slice-s1 | slice (meet at tick 0) | 266 | 0 | $46.28 | $0.174 | 6,204 | 1,311 |
| live-baseline-s1 | normal | 237 | 0 | $35.55 | $0.150 | 4,878 | 1,058 |

## Per LLM civ, split at first contact

| Run | Civ | First contact (tick) | Phase | Ticks | Calls | Cost | Input tokens | Output tokens | Calls per 100 ticks | Cost per 100 ticks |
|---|---|---|---|---|---|---|---|---|---|---|
| live-slice-s1 | Saltreach | 0 | after | 150 | 132 | $23.68 | 1,289,643 | 861,958 | 88.0 | $15.78 |
| live-slice-s1 | Verdance | 0 | after | 150 | 134 | $22.60 | 1,345,809 | 788,202 | 89.3 | $15.07 |
| live-baseline-s1 | Saltreach | 29 | before | 29 | 15 | $1.18 | 113,111 | 31,132 | 51.7 | $4.07 |
| live-baseline-s1 | Saltreach | 29 | after | 121 | 111 | $20.53 | 1,170,575 | 721,426 | 91.7 | $16.97 |
| live-baseline-s1 | Verdance | 33 | before | 33 | 18 | $1.20 | 138,108 | 25,869 | 54.5 | $3.65 |
| live-baseline-s1 | Verdance | 33 | after | 117 | 93 | $12.63 | 977,620 | 377,640 | 79.5 | $10.80 |

Input tokens are cache creation plus cache reads plus uncached input. The before-contact rows rest on 15 and 18 calls.

## Budget in force for these runs
1 decide call per civ per tick at most, a reflection every 8 ticks, 5 calls at a time, no extra diplomatic turns.
