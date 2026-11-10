# 0001: Integer state, one ledger, and a civ-wide stockpile

## Decision
- All world state is integers. Rates are per mille, and every division goes through `fogline/intmath.py`, which rounds down unless a rule says up.
- Every change to a conserved stock (resources, population, node stock) goes through `fogline/ledger.py` with a named rule.
- Each civ has one stockpile shared by all its settlements.

## Why
Replays have to reproduce the same state hash on any machine (PLAN section 11). Floats make that fragile: summation order, text formatting and maths library differences all leak into the hash. With integers the only rounding is the rounding I wrote, and it's in one module with tests.

The ledger exists because conservation is a test, not a hope. If every stock change carries a rule name, the test can check that start plus the sum of changes equals the end for every stock, and a stock that moves without a rule is a bug the test catches.

The civ-wide stockpile is a v1 simplification. Per-settlement stocks would need internal caravans, transfer orders and a second layer of shortage, before the interesting part (contact between civs) even exists. Raids still bite, because a raid reaches the target settlement's share of the stock (its population share).

## Not chosen
- **Floats with rounding at the end of each tick.** Easier to write, but a single forgotten rounding breaks replay, and the failure shows up hundreds of ticks later.
- **`fractions.Fraction`.** Exact, but slow over 1,000 ticks and awkward to serialise.
- **Per-settlement stockpiles.** More realistic, but it adds a transfer system that no Phase 1 to 3 test needs.

## What I'd watch
Per-mille rates lose precision on small numbers: 15 per mille of a 5-person outpost is 0 a tick. Growth uses an accumulator for that reason. Any new rate applied to small values needs the same treatment.
