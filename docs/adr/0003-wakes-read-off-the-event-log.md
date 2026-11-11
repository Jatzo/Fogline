# 0003: Wakes are read off the event log

## Decision
A civ's wakes are worked out in step 1 by reading `state["events"]` from a cursor kept per civ, through one table (`turns.EVENT_TRIGGERS`) that maps an event kind to a trigger. Construction, research, movement and sight only record events, as they already did; none of them wakes anyone. The cursor moves when the civ's decider is called, so anything recorded after that, including during a long Phase 2 call, waits for the next wake. A skipped turn leaves the cursor where it is.

## Why
The wake list has a dozen triggers raised by five modules today and more in Phases 3 and 5. If each source had to call a `wake.fire()`, the list would live in five places, and a new source that forgot the call would fail silently: the civ would just never wake. With the table, adding a trigger is one row, and a test checks that every row names a real trigger.

The rule "a trigger that fires during an in-flight call is queued for the next wake" (PLAN section 10) comes free: the cursor is set before the call, so later events are after it. A separate pending queue would need its own rule for that.

## Not chosen
- **A push model** (`wake.fire()` at each source writing to a pending list per civ). Easy to read at each call site, but five writers to one queue, and the pending list grows forever for a civ with no decider unless something clears it.
- **Polling state** (step 1 compares stocks, units and buildings with last turn's copy). No contract on event names, but every trigger needs its own diff, and the copy doubles the state.

## What I'd watch
Event kinds are now a contract. Renaming `"built"` would silently stop `build_done` wakes, and trimming `state["events"]` would break every cursor. If the event list ever gets trimmed for size, cursors need an offset, and the trim has to keep everything past the lowest cursor.
