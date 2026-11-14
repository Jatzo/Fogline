# 0012: Rulers come from a roster of models, rotated by seed

## Decision
A live run's rulers are drawn from a roster, by default claude-haiku-5-5, claude-sonnet-5-5 and claude-opus-5-5. The i-th live civ in sorted order gets `models[(i + seed) % 3]`, so each seed has two of two models and one of the third, and over three seeds every civ is played by every model once. The roster is worked out when a run starts and written to its manifest as `models: {civ: model}`; resume and replay read it from there and never work it out again. `--models` sets the list, and one model rules every civ. The viewer labels each civ with its model.

## Why
The operator wanted to see different models play against each other, and it makes the run more interesting to watch. But with one model per civ in a single run, a model's effect and a culture's effect are tangled: if the Opus civ does well, it could be Opus or it could be Ironhold. Rotating the roster with the seed means each model plays each culture across seeds, so the two can be told apart, at the price of needing three seeds for a fair comparison.

The roster lives in the manifest, not in the config, because the config hash guards resume: a new config field would have changed the hash of every existing run and refused to resume any of them, the stopped all-Haiku run included. A manifest from before the roster reads as one model for every ruler.

## Not chosen
- **One fixed model per civ** (say Ironhold always Opus): simpler and easy to follow, but model and culture can never be separated.
- **One model for all,** the old PLAN decision: the cleanest test of culture, but no comparison between models. It stays available with `--models claude-haiku-5-5`.
- **Fable 5.2 in the roster:** twice Opus's price; left out until a run shows the roster is worth it.

## What it cost
- A seed-1 rotated run is about $160 notional at list prices, against about $6 to $7 all-Haiku (`research/phase4-cost-estimate-draft.md`). On the Max plan this is usage limits, and Opus and Sonnet use them up far faster than Haiku.
- The research question changes: findings about kindness or raiding now need the model named, and three seeds per comparison.

## What I would not trust
- **The estimate:** Sonnet's and Opus's token use is assumed equal to Haiku's measured counts; they may think for longer. The first 20 ticks of the first mixed run should be checked against it.
- **Two out of five:** each seed has unequal numbers of each model, so a model's average over one seed rests on one or two civs.
