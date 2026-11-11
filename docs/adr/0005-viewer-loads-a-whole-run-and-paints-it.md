# 0005: The viewer loads a whole run at once and paints it

## Decision
The Phase 1 viewer is a local FastAPI app that reads run folders written by `fogline.run`. One request, `GET /api/runs/{name}`, loads every snapshot in the folder, turns each into a frame with `fogline/view.py`, and sends the manifest, the fixed map and all frames together. The page then scrubs and plays through them with no more requests.

The map is painted, not drawn as a tile grid. The page paints the terrain once per run at 24 pixels a tile: each pixel finds its biome through a warped position so coasts and biome edges wander, with beaches, shallows, trees, peaks, dunes and waves drawn over it. Every frame then draws territory as a soft wash with frontiers smoothed by marching squares, the towns as houses, fields and lanes in each culture's style, the seats growing a tower and spire by stage, and the names.

## Why
A 400-tick run has 101 snapshots. Loading them all takes 0.9 seconds on this machine and sends 4.8 MB, which is fine for a local tool. With every frame in the browser, the time-lapse can't stall on the network and scrubbing is instant. The server stays three short routes with no cache to get wrong.

The painted map was the operator's call. The first version drew each tile as a coloured square with small sprites, which showed the data but read as a spreadsheet. PLAN section 12 says watching real places grow is the main attraction.

## Not chosen
- **One route per tick, with a cache and prefetch.** What a live run will need in Phase 6, but for a finished run it is more code for a slower scrubber.
- **A frames file baked by the runner.** No server at all, but every run folder would carry a second copy of its history, and the frame format would be frozen into old runs.
- **Isometric drawing or detailed pixel art.** Both offered to the operator. Isometric makes clicking a tile and placing labels harder; pixel art keeps the grid the operator wanted gone.

## What it cost
The terrain paint takes about 1.3 seconds once per run, so the page shows "Painting the map." while it runs. Each frame then draws in about 6 ms. The canvas is 1,536 pixels square, so the stylesheet has to stop it setting the height of its frame.

## What I'd not trust
- A 1,000-tick run would be about 12 MB in one response. Fine locally; not something to serve over a network.
- The painting is decoration over the data. A warped coast can put a few pixels of sea on a land tile, and a town's buildings can sit on painted mountains. The hover readout and the town card give the true tile and the true numbers.
- The frames are built from snapshots, one a year. Anything that happens between two snapshots does not appear.
