# Wayfinding map (vanilla JS, no build)

- Standalone hospital floor-map viewer: `index.html` + `app.js` + `map-data.js` + `style.css`. No framework, no bundler — open the file or serve statically.
- `map-data.js` holds ALL map content: `FLOORS` (SVG floor images in `assets/`, wall segments, 637×454 coordinate space), destinations, and routing constants (`PIXELS_PER_METER`, walking speed, turn penalty). Routing is a grid A* over the wall data; route animates as an SVG overlay.
- Deployed by COPYING this folder to `hospital-hotline-assistant-web/public/hospital-map/`, where `RecommendationCard.tsx` embeds it in an iframe (department passed via query param). This is the source; edit here, then sync the copy.
- `style.css` is cache-busted by a `?v=N` query in `index.html` — bump it when changing CSS.
