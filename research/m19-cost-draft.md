# M19 cost draft (numbers only)

**Corrected 2026-11-14.** The dollar figures in the tables below are `claude -p`'s `total_cost_usd`, which priced claude-haiku-5-5 at Opus 5.5 rates. At Haiku 5.5 list prices (`fogline/pricing.py`, cache writes as 1-hour):

| Run | Calls | Reported | At Haiku 5.5 list prices | Per call |
|---|---|---|---|---|
| live-slice-s1 | 266 | $46.28 | $1.16 | $0.0044 |
| live-baseline-s1 | 237 | $35.55 | $0.89 | $0.0038 |

| Run | Civ | Phase | Ticks | Calls | Cost | Cost per 100 ticks |
|---|---|---|---|---|---|---|
| live-slice-s1 | Saltreach | after | 150 | 132 | $0.59 | $0.40 |
| live-slice-s1 | Verdance | after | 150 | 134 | $0.57 | $0.38 |
| live-baseline-s1 | Saltreach | before | 30 | 15 | $0.03 | $0.10 |
| live-baseline-s1 | Saltreach | after | 120 | 111 | $0.52 | $0.43 |
| live-baseline-s1 | Verdance | before | 34 | 18 | $0.03 | $0.09 |
| live-baseline-s1 | Verdance | after | 116 | 93 | $0.32 | $0.27 |

The token counts and call counts below are unchanged.

Seed 1, 150 ticks, Verdance and Saltreach as live rulers on `claude-haiku-5-5` through `claude -p --safe-mode`, the other three civs scripted traders. Costs are the notional `total_cost_usd` reported per call, run on the plan login, not billed. Raw outputs stay in `runs/` (gitignored). Both runs replay exactly to their tick-148 snapshots.

## Per run

| Run | Placement | LLM calls | Failed calls | Notional cost | Cost per call | Output tokens per call | Reply characters per call |
|---|---|---|---|---|---|---|---|
| live-slice-s1 | slice (meet at tick 0) | 266 | 0 | $46.28 | $0.174 | 6,204 | 1,311 |
| live-baseline-s1 | normal | 237 | 0 | $35.55 | $0.150 | 4,878 | 1,058 |

## Per LLM civ, split at the first turn that could see contact

| Run | Civ | First contact (tick) | First turn after it | Phase | Ticks | Calls | Cost | Input tokens | Output tokens | Calls per 100 ticks | Cost per 100 ticks |
|---|---|---|---|---|---|---|---|---|---|---|---|
| live-slice-s1 | Saltreach | 0 (setup) | 0 | after | 150 | 132 | $23.68 | 1,289,643 | 861,958 | 88.0 | $15.78 |
| live-slice-s1 | Verdance | 0 (setup) | 0 | after | 150 | 134 | $22.60 | 1,345,809 | 788,202 | 89.3 | $15.07 |
| live-baseline-s1 | Saltreach | 29 | 30 | before | 30 | 15 | $1.18 | 113,111 | 31,132 | 50.0 | $3.93 |
| live-baseline-s1 | Saltreach | 29 | 30 | after | 120 | 111 | $20.53 | 1,170,575 | 721,426 | 92.5 | $17.11 |
| live-baseline-s1 | Verdance | 33 | 34 | before | 34 | 18 | $1.20 | 138,108 | 25,869 | 52.9 | $3.54 |
| live-baseline-s1 | Verdance | 33 | 34 | after | 116 | 93 | $12.63 | 977,620 | 377,640 | 80.2 | $10.89 |

Contact found during tick t is recorded as t but first seen by the turn at t + 1; contact at world setup is seen by turn 0. The split uses that first turn. Neither run made a call in a contact tick, so only the tick spans moved when the split was corrected after the Phase 3 review. Input tokens are cache creation plus cache reads plus uncached input. The before-contact rows rest on 15 and 18 calls.

## Budget in force for these runs
1 decide call per civ per tick at most, a reflection every 8 ticks, 5 calls at a time, no extra diplomatic turns.
