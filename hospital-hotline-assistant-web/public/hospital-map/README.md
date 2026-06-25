# CareNav Hospital Wayfinder

This is a static 2D hospital route finder made from your floor map.

## Main improvement

The route now uses only four directions:

- Up: 90 degrees
- Left: 180 degrees
- Down: 270 degrees
- Right: 360 degrees

No diagonal movement is allowed. The route line is drawn with clean 90-degree corners only.

## What is included

```text
hospital-orthogonal-route-finder/
├── index.html
├── style.css
├── app.js
├── README.md
└── assets/
    ├── floor-map.svg
    ├── floor-map.png
    ├── wall-mask.svg
    ├── wall-mask.png
    ├── walls.json
    └── route-blockers.json
```

## Hospital features

- Professional hospital-style UI
- Emergency, OPD, department, clinic, and reception destinations
- Route avoids black wall lines
- Extra no-walk zones for service counters or restricted areas
- Start and destination dropdowns
- Quick buttons for Emergency, Reception, and OPD
- Custom start point: click on the map
- Custom destination: Shift + click on the map
- Zoom controls
- Distance, time, and turn count
- Step-by-step directions using only up, down, left, and right

## How to test

Open `index.html` in your browser. Choose a start location and destination, then click **Find hospital route**.

## Editing locations

Open `app.js` and edit `BASE_LOCATIONS`:

```js
const BASE_LOCATIONS = {
  entrance: { label: "Entrance", group: "Access", x: 198, y: 438, type: "entry" },
  opd: { label: "OPD Department", group: "Department", x: 374, y: 238, type: "room" }
};
```

Use the coordinate helper in the sidebar to find new x/y points.

## Adding no-walk zones

Open `assets/route-blockers.json` and add desks, beds, staff-only spaces, equipment, or restricted areas.

```json
{
  "id": "checkInDesk",
  "label": "Check-in counter / staff desk",
  "x": 126,
  "y": 302,
  "width": 154,
  "height": 39,
  "padding": 5
}
```

The current app also embeds this blocker data in `app.js`, so after editing the JSON file, copy the same values into `EXTRA_BLOCKERS` in `app.js` or connect the app to load the JSON dynamically.

## Note

This is a strong starter version. For real hospital use, verify every route with staff, accessibility needs, emergency exits, fire doors, restricted rooms, and updated floor plans.
