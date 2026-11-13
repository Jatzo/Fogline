# 0010: A stopped run resumes by replaying its stored outputs from tick 0

## Decision
`python -m fogline.run --resume <folder>` carries on a stopped mock or live run. It reads the manifest, rebuilds the world from the seed, and replays every stored output before the resume tick through the same path the run used. Each replayed output is checked against the observation it first answered, and the world is checked against the last snapshot saved before the resume tick. From the resume tick on, the rulers are called afresh. The stopped session's logs, snapshots and full outputs move into `before-resume-<n>/` first, so no paid call is lost, and the logs and snapshots are written again as the replay goes. If the replay doesn't reach the saved world, everything is put back as it was before any fresh call, so a second try checks against the same snapshot. The summary counts the calls dropped to be made again, with their cost, and the manifest records each resume tick.

The resume tick is the last tick with stored outputs, which may have stopped half way, or the first of any trailing ticks where every call failed. A run that stops because the plan's usage ran out ends in those ticks, and replaying them would turn a pause into empty turns.

## Why
A 400-tick live run with five rulers is about 1,500 calls on the plan's usage limits, so it will very likely stop at least once. PLAN section 15 counts resumed sessions for Phase 4.

Replaying from tick 0 reuses what already exists and is tested: replay mode, the per-call observation check, and the runner's notes, which are built tick by tick and would otherwise be lost. It costs no calls, because the stored outputs answer, and it proves the stored run is still consistent with the code before any fresh call is spent.

## Not chosen
- **Load the last snapshot and carry on from there:** faster, but the runner's notes for the summary (run-outs, peaks, the cost meter's call counts) would start empty, and nothing would check that the stored outputs still match the code.
- **Keep the logs and append:** a half-finished tick's turn and ledger lines would be written twice.
- **Delete the stopped session's files before replaying:** my first version did. A review found that a failed resume then left a replayed snapshot behind, which the next resume would have checked against.

## What it cost
- A router adapter (`llm.Resumed`), a resume-point rule, and the run folder's logs being rewritten on resume.
- A mock ruler keeps its scratch memory on the adapter's side, which a live call doesn't have. On a mock resume the stored turns are also put to the mock again to rebuild that memory, and it must give the stored answer each time. A test resumes a mock run cut at tick 13 and reaches the same world as the run that never stopped.

## What I would not trust
- **A live resume hasn't been run for real.** The tests use the mock, which goes through the same recorder and text path. A live call keeps nothing between turns, so nothing should be missing, but that is reasoning, not a measurement.
- **The replay takes time.** Bot turns and observations are rebuilt for every replayed tick. I haven't timed it on a 400-tick run.
- **Any change to the code that moves the world refuses the resume** (a different config hash, or an observation that no longer matches). That is deliberate, but it means code can't change in the middle of a live run.
