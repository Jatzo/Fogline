# 0011: The viewer draws the world as a 3D block on a table

## Decision
The map is drawn in three.js as a carved block of earth on a walnut table: a low-poly height field with flat-shaded faces, cut sides banded in strata, the sea as a slab of clear water whose edge shows its depth, instanced trees and rocks, procedural houses and keeps in each culture's colours, civ-coloured territory and borders, and town name cards. Nothing sits over the land: everything you read (run and time, the civs, the selected town, the ruler's turn) is in one strip along the bottom, the table's front edge. The camera orbits, slides and zooms within limits.

three.js 0.170.0 (MIT) is vendored into `fogline/viewer/static/vendor/` and pinned by SHA-256 in a test. It is the last release built as a single module file. `OrbitControls.js` has one edited line: its bare `import ... from 'three'` points at the vendored file, because a bare name needs an import map and the viewer's CSP (`default-src 'self'`) blocks the inline one.

The flat 2D map stays as a fallback. It is drawn when WebGL is missing, when the 3D module fails to load, or when the address carries `?flat`.

## Why
The 2D map read as generated: a flat painted square with dots. A block on a table is an object you can turn and look into, and every part of it comes from the run's own data, so nothing is decoration. Keeping all text off the land means the world is never hidden behind a panel.

Vendoring keeps the viewer local and offline, and the CSP strict: no CDN, no import map, no `blob:` URLs.

## Not chosen
- **A 2.5D isometric canvas:** lighter, with no new library, but no orbit or real depth, and it would still be a picture of a map.
- **A CDN or an import map:** either would loosen the CSP for one library.
- **Two vertices per tile:** smoother, but four times the triangles; at one vertex per tile plus a centre point the mountains still peak.
- **Seasonal light as the signature:** snapshots are saved every 4 ticks, so every frame falls in the same season.

## What it cost
- 692 KB of vendored JavaScript, and a test that pins it.
- The side panel became a bottom strip, so the page layout changed as well as the map.
- The viewer now sends `Cache-Control: no-cache` and registers `.js` as JavaScript: during the work the browser kept stale copies of edited files, and Windows can serve `.js` as plain text, which a browser refuses for a module.

## What I would not trust
- **Frame rate:** I measured the rebuild for one step (11 ms median, 14 ms worst, 400-tick five-civ mock run) but not the render itself, because the browser pane was hidden and throttled. CI has no GPU or JS runner, so none of the scene is tested there; the checks are by hand in the browser.
- **Picking:** a click meets a flat plane just above the land, not the land itself, so on high ground it can land a tile off. The nearest town within two tiles is chosen, which hides most of that.
- **Small screens:** below 640 px the strip stacks under the block and the page scrolls; I haven't tried a phone.
