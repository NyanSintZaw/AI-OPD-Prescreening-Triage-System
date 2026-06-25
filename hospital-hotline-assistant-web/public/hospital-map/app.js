const MAP_WIDTH = 637;
const MAP_HEIGHT = 454;
const CELL_SIZE = 4;
const WALL_PADDING = 2.0;
const PIXELS_PER_METER = 8;
const WALKING_SPEED_M_PER_MIN = 55;
const TURN_PENALTY = 0.45;
const ROUTE_ANIMATION_DURATION_MS = 7200;
const ROUTE_TANGENT_SAMPLE_DISTANCE = 0.1;

// Extracted black wall segments from the uploaded floor plan.
const WALLS = [{"x1":361.0,"y1":302.0,"x2":629.0,"y2":302.0,"w":10.0},{"x1":104.0,"y1":302.0,"x2":323.0,"y2":302.0,"w":10.0},{"x1":230.0,"y1":449.0,"x2":637.0,"y2":449.0,"w":10.0},{"x1":167.0,"y1":449.0,"x2":0.0,"y2":449.0,"w":10.0},{"x1":5.0,"y1":307.0,"x2":5.0,"y2":444.0,"w":10.0},{"x1":318.0,"y1":169.0,"x2":318.0,"y2":307.0,"w":10.0},{"x1":5.0,"y1":169.0,"x2":5.00001,"y2":307.0,"w":10.0},{"x1":323.0,"y1":174.0,"x2":41.0,"y2":174.0,"w":10.0},{"x1":422.0,"y1":93.0,"x2":202.0,"y2":93.0,"w":10.0},{"x1":637.0,"y1":93.0,"x2":521.0,"y2":93.0,"w":10.0},{"x1":631.0,"y1":174.0,"x2":361.0,"y2":174.0,"w":10.0},{"x1":80.0,"y1":93.0,"x2":0.0,"y2":93.0,"w":10.0},{"x1":1085.0,"y1":5.0,"x2":4.0,"y2":5.0,"w":10.0},{"x1":211.0,"y1":93.0,"x2":123.0,"y2":93.0,"w":10.0},{"x1":207.0,"y1":0.0,"x2":207.0,"y2":88.0,"w":10.0},{"x1":5.0,"y1":0.0,"x2":5.0,"y2":88.0,"w":10.0},{"x1":474.0,"y1":2.18557e-07,"x2":474.0,"y2":97.0,"w":10.0},{"x1":366.0,"y1":252.0,"x2":366.0,"y2":307.0,"w":10.0},{"x1":366.0,"y1":169.0,"x2":366.0,"y2":224.0,"w":10.0},{"x1":60.0,"y1":174.0,"x2":-13.0,"y2":174.0,"w":10.0},{"x1":-12.0,"y1":302.0,"x2":60.0,"y2":302.0,"w":10.0},{"x1":634.0,"y1":5.0,"x2":634.0,"y2":398.0,"w":10.0},{"x1":593.5,"y1":307.0,"x2":593.5,"y2":360.0,"w":3.0},{"x1":519.5,"y1":307.0,"x2":519.5,"y2":360.0,"w":3.0},{"x1":449.5,"y1":307.0,"x2":449.5,"y2":360.0,"w":3.0},{"x1":555.5,"y1":307.0,"x2":555.5,"y2":360.0,"w":3.0},{"x1":484.5,"y1":307.0,"x2":484.5,"y2":360.0,"w":3.0},{"x1":448.0,"y1":359.5,"x2":461.0,"y2":359.5,"w":1.0},{"x1":472.0,"y1":359.5,"x2":485.0,"y2":359.5,"w":1.0},{"x1":484.0,"y1":359.5,"x2":497.0,"y2":359.5,"w":1.0},{"x1":594.0,"y1":359.5,"x2":607.0,"y2":359.5,"w":1.0},{"x1":618.0,"y1":359.5,"x2":631.0,"y2":359.5,"w":1.0},{"x1":508.0,"y1":359.5,"x2":521.0,"y2":359.5,"w":1.0},{"x1":519.0,"y1":359.5,"x2":532.0,"y2":359.5,"w":1.0},{"x1":543.0,"y1":359.5,"x2":556.0,"y2":359.5,"w":1.0},{"x1":580.0,"y1":359.5,"x2":593.0,"y2":359.5,"w":1.0},{"x1":555.0,"y1":359.5,"x2":568.0,"y2":359.5,"w":1.0},{"x1":634.0,"y1":430.0,"x2":634.0,"y2":454.0,"w":10.0}];

// Extra no-walk zones. Useful for hospital desks, counters, restricted equipment, beds, etc.
const EXTRA_BLOCKERS = [{"id":"checkInDesk","label":"Check-in counter / staff desk","x":126,"y":302,"width":154,"height":39,"padding":5}];

const DIRECTIONS = [
  { dx: 1, dy: 0, key: "right", label: "Go right", degree: 360, icon: "→" },
  { dx: -1, dy: 0, key: "left", label: "Go left", degree: 180, icon: "←" },
  { dx: 0, dy: -1, key: "up", label: "Go up", degree: 90, icon: "↑" },
  { dx: 0, dy: 1, key: "down", label: "Go down", degree: 270, icon: "↓" }
];

const BASE_LOCATIONS = {
  entrance: { label: "Entrance", group: "Access", x: 198, y: 438, type: "entry" },
  publicWaiting: { label: "Public Waiting Area", group: "Access", x: 310, y: 386, type: "hallway" },
  mainHallway: { label: "Main Hallway", group: "Access", x: 342, y: 134, type: "hallway" },
  counter: { label: "Registration Counter", group: "Service", x: 198, y: 350, type: "service" },
  emergency: { label: "Emergency & Trauma", group: "Emergency", x: 82, y: 314, type: "emergency" },
  opd: { label: "General Practice / OPD", group: "Department", x: 374, y: 238, type: "room" },
  neurology: { label: "Neurology", group: "Department", x: 106, y: 106, type: "room" },
  cardiology: { label: "Cardiology", group: "Department", x: 450, y: 106, type: "room" },
  pediatrics: { label: "Pediatrics", group: "Department", x: 502, y: 106, type: "room" },
  orthopedics: { label: "Orthopedics", group: "Clinic", x: 466, y: 366, type: "room" },
  gynecology: { label: "Gynecology & Obstetrics", group: "Clinic", x: 502, y: 366, type: "room" },
  gastroenterology: { label: "Gastroenterology", group: "Clinic", x: 538, y: 366, type: "room" },
  ent: { label: "ENT (Ear, Nose, Throat)", group: "Clinic", x: 574, y: 366, type: "room" },
  teeth: { label: "Teeth / Dental", group: "Clinic", x: 614, y: 366, type: "room" }
};

const GROUP_ORDER = ["Access", "Service", "Emergency", "Department", "Clinic", "Custom"];

const state = {
  grid: null,
  clearancePenalty: null,
  cols: Math.ceil(MAP_WIDTH / CELL_SIZE),
  rows: Math.ceil(MAP_HEIGHT / CELL_SIZE),
  customStart: null,
  customDestination: null,
  zoomPercent: 100,
  routeAnimationFrame: null
};

const els = {
  startSelect: document.getElementById("startSelect"),
  destinationSelect: document.getElementById("destinationSelect"),
  findRouteBtn: document.getElementById("findRouteBtn"),
  resetBtn: document.getElementById("resetBtn"),
  coordinateReadout: document.getElementById("coordinateReadout"),
  blockerLayer: document.getElementById("blockerLayer"),
  poiLayer: document.getElementById("poiLayer"),
  routeHalo: document.getElementById("routeHalo"),
  routeLine: document.getElementById("routeLine"),
  routeHead: document.getElementById("routeHead"),
  turnLayer: document.getElementById("turnLayer"),
  markerLayer: document.getElementById("markerLayer"),
  mapViewport: document.getElementById("mapViewport"),
  mapInner: document.getElementById("mapInner"),
  zoomInBtn: document.getElementById("zoomInBtn"),
  zoomOutBtn: document.getElementById("zoomOutBtn"),
  zoomResetBtn: document.getElementById("zoomResetBtn"),
  directionsList: document.getElementById("directionsList")
};

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function distancePointToSegment(px, py, wall) {
  const dx = wall.x2 - wall.x1;
  const dy = wall.y2 - wall.y1;
  const lengthSquared = dx * dx + dy * dy;

  if (lengthSquared === 0) {
    return Math.hypot(px - wall.x1, py - wall.y1);
  }

  let t = ((px - wall.x1) * dx + (py - wall.y1) * dy) / lengthSquared;
  t = Math.max(0, Math.min(1, t));
  const nearestX = wall.x1 + t * dx;
  const nearestY = wall.y1 + t * dy;
  return Math.hypot(px - nearestX, py - nearestY);
}

function pointInsideBlocker(x, y, blocker) {
  const padding = blocker.padding || 0;
  return x >= blocker.x - padding &&
    x <= blocker.x + blocker.width + padding &&
    y >= blocker.y - padding &&
    y <= blocker.y + blocker.height + padding;
}

function isBlockedPoint(x, y, padding = WALL_PADDING) {
  if (x < 0 || y < 0 || x > MAP_WIDTH || y > MAP_HEIGHT) {
    return true;
  }

  for (const blocker of EXTRA_BLOCKERS) {
    if (pointInsideBlocker(x, y, blocker)) {
      return true;
    }
  }

  for (const wall of WALLS) {
    const radius = wall.w / 2 + padding;
    const minX = Math.min(wall.x1, wall.x2) - radius;
    const maxX = Math.max(wall.x1, wall.x2) + radius;
    const minY = Math.min(wall.y1, wall.y2) - radius;
    const maxY = Math.max(wall.y1, wall.y2) + radius;

    if (x < minX || x > maxX || y < minY || y > maxY) {
      continue;
    }

    if (distancePointToSegment(x, y, wall) <= radius) {
      return true;
    }
  }

  return false;
}

function buildGrid() {
  const grid = Array.from({ length: state.rows }, () => Array(state.cols).fill(false));

  for (let row = 0; row < state.rows; row += 1) {
    for (let col = 0; col < state.cols; col += 1) {
      const x = (col + 0.5) * CELL_SIZE;
      const y = (row + 0.5) * CELL_SIZE;
      grid[row][col] = isBlockedPoint(x, y);
    }
  }

  state.grid = grid;
  buildClearancePenalty();
}

function buildClearancePenalty() {
  const penalty = Array.from({ length: state.rows }, () => Array(state.cols).fill(0));
  const radius = 5;

  for (let row = 0; row < state.rows; row += 1) {
    for (let col = 0; col < state.cols; col += 1) {
      if (state.grid[row][col]) {
        penalty[row][col] = 99;
        continue;
      }

      let blockedNeighbors = 0;
      for (let dr = -radius; dr <= radius; dr += 1) {
        for (let dc = -radius; dc <= radius; dc += 1) {
          if (dc === 0 && dr === 0) continue;
          if (isCellBlocked(col + dc, row + dr)) {
            blockedNeighbors += 1;
          }
        }
      }
      penalty[row][col] = Math.min(0.65, blockedNeighbors * 0.01);
    }
  }

  state.clearancePenalty = penalty;
}

function cellPenalty(col, row) {
  if (!state.clearancePenalty) return 0;
  return state.clearancePenalty[row]?.[col] || 0;
}

function pointToCell(point) {
  return {
    col: Math.max(0, Math.min(state.cols - 1, Math.floor(point.x / CELL_SIZE))),
    row: Math.max(0, Math.min(state.rows - 1, Math.floor(point.y / CELL_SIZE)))
  };
}

function cellToPoint(cell) {
  return {
    x: (cell.col + 0.5) * CELL_SIZE,
    y: (cell.row + 0.5) * CELL_SIZE
  };
}

function isCellBlocked(col, row) {
  return row < 0 || col < 0 || row >= state.rows || col >= state.cols || state.grid[row][col];
}

function cellKey(col, row, direction = "") {
  return `${col},${row},${direction}`;
}

function nearestFreeCell(cell, maxRadius = 40) {
  if (!isCellBlocked(cell.col, cell.row)) {
    return cell;
  }

  for (let radius = 1; radius <= maxRadius; radius += 1) {
    const options = [];
    for (let dr = -radius; dr <= radius; dr += 1) {
      for (let dc = -radius; dc <= radius; dc += 1) {
        if (Math.abs(dc) !== radius && Math.abs(dr) !== radius) continue;
        const col = cell.col + dc;
        const row = cell.row + dr;
        if (!isCellBlocked(col, row)) {
          options.push({ col, row, distance: Math.abs(dc) + Math.abs(dr) });
        }
      }
    }

    if (options.length > 0) {
      options.sort((a, b) => a.distance - b.distance);
      return { col: options[0].col, row: options[0].row };
    }
  }

  return null;
}

class MinHeap {
  constructor() {
    this.items = [];
  }

  get size() {
    return this.items.length;
  }

  push(item) {
    this.items.push(item);
    this.bubbleUp(this.items.length - 1);
  }

  pop() {
    if (this.items.length === 0) return null;
    const first = this.items[0];
    const last = this.items.pop();
    if (this.items.length > 0) {
      this.items[0] = last;
      this.bubbleDown(0);
    }
    return first;
  }

  bubbleUp(index) {
    let child = index;
    while (child > 0) {
      const parent = Math.floor((child - 1) / 2);
      if (this.items[parent].priority <= this.items[child].priority) break;
      [this.items[parent], this.items[child]] = [this.items[child], this.items[parent]];
      child = parent;
    }
  }

  bubbleDown(index) {
    let parent = index;
    while (true) {
      const left = parent * 2 + 1;
      const right = left + 1;
      let smallest = parent;

      if (left < this.items.length && this.items[left].priority < this.items[smallest].priority) smallest = left;
      if (right < this.items.length && this.items[right].priority < this.items[smallest].priority) smallest = right;
      if (smallest === parent) break;
      [this.items[parent], this.items[smallest]] = [this.items[smallest], this.items[parent]];
      parent = smallest;
    }
  }
}

function heuristic(a, b) {
  return Math.abs(a.col - b.col) + Math.abs(a.row - b.row);
}

function findOrthogonalPath(startPoint, endPoint) {
  const startCell = nearestFreeCell(pointToCell(startPoint));
  const endCell = nearestFreeCell(pointToCell(endPoint));

  if (!startCell || !endCell) {
    return null;
  }

  const open = new MinHeap();
  const cameFrom = new Map();
  const costSoFar = new Map();
  const startKey = cellKey(startCell.col, startCell.row, "start");
  let finalKey = null;

  open.push({ col: startCell.col, row: startCell.row, direction: "start", priority: 0, key: startKey });
  cameFrom.set(startKey, null);
  costSoFar.set(startKey, 0);

  while (open.size > 0) {
    const current = open.pop();
    const currentCost = costSoFar.get(current.key);

    if (current.col === endCell.col && current.row === endCell.row) {
      finalKey = current.key;
      break;
    }

    for (const direction of DIRECTIONS) {
      const nextCol = current.col + direction.dx;
      const nextRow = current.row + direction.dy;

      if (isCellBlocked(nextCol, nextRow)) continue;

      const nextKey = cellKey(nextCol, nextRow, direction.key);
      const turnCost = current.direction !== "start" && current.direction !== direction.key ? TURN_PENALTY : 0;
      const newCost = currentCost + 1 + turnCost + cellPenalty(nextCol, nextRow);

      if (!costSoFar.has(nextKey) || newCost < costSoFar.get(nextKey)) {
        costSoFar.set(nextKey, newCost);
        cameFrom.set(nextKey, current.key);
        const priority = newCost + heuristic({ col: nextCol, row: nextRow }, endCell);
        open.push({ col: nextCol, row: nextRow, direction: direction.key, priority, key: nextKey });
      }
    }
  }

  if (!finalKey) return null;

  const cells = [];
  let currentKey = finalKey;
  while (currentKey) {
    const [col, row] = currentKey.split(",").map((value, index) => index < 2 ? Number(value) : value);
    cells.push({ col, row });
    currentKey = cameFrom.get(currentKey);
  }
  cells.reverse();

  const points = cells.map(cellToPoint);
  return simplifyOrthogonalPath(points);
}

function simplifyOrthogonalPath(points) {
  if (!points || points.length <= 2) return points || [];

  const compressed = [points[0]];
  let previousDirection = null;

  for (let i = 1; i < points.length; i += 1) {
    const direction = getSegmentDirection(points[i - 1], points[i]);
    if (previousDirection === null) {
      previousDirection = direction.key;
      continue;
    }

    if (direction.key !== previousDirection) {
      compressed.push(points[i - 1]);
      previousDirection = direction.key;
    }
  }

  compressed.push(points[points.length - 1]);
  return compressed;
}

function getSegmentDirection(a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx >= 0 ? DIRECTIONS[0] : DIRECTIONS[1];
  }
  return dy <= 0 ? DIRECTIONS[2] : DIRECTIONS[3];
}

function routeLength(points) {
  let total = 0;
  for (let i = 1; i < points.length; i += 1) {
    total += Math.abs(points[i].x - points[i - 1].x) + Math.abs(points[i].y - points[i - 1].y);
  }
  return total;
}

function easeInOutSine(progress) {
  return -(Math.cos(Math.PI * progress) - 1) / 2;
}

function cancelRouteAnimation() {
  if (state.routeAnimationFrame !== null) {
    cancelAnimationFrame(state.routeAnimationFrame);
    state.routeAnimationFrame = null;
  }

}

function routeAngleAtLength(path, pathLength, distance) {
  const current = path.getPointAtLength(distance);
  let nextDistance = Math.min(pathLength, distance + ROUTE_TANGENT_SAMPLE_DISTANCE);
  let next = path.getPointAtLength(nextDistance);

  if (Math.hypot(next.x - current.x, next.y - current.y) < 0.001) {
    nextDistance = Math.max(0, distance - ROUTE_TANGENT_SAMPLE_DISTANCE);
    next = current;
    const previous = path.getPointAtLength(nextDistance);
    return Math.atan2(next.y - previous.y, next.x - previous.x) * 180 / Math.PI;
  }

  return Math.atan2(next.y - current.y, next.x - current.x) * 180 / Math.PI;
}

function setRouteProgress(pathLength, progress) {
  const clampedProgress = Math.max(0, Math.min(1, progress));
  const distance = pathLength * clampedProgress;
  const dashOffset = pathLength - distance;

  [els.routeHalo, els.routeLine].forEach(path => {
    path.style.strokeDasharray = `${pathLength} ${pathLength}`;
    path.style.strokeDashoffset = dashOffset;
  });

  if (!els.routeHead) return;

  const point = els.routeLine.getPointAtLength(distance);
  const angle = routeAngleAtLength(els.routeLine, pathLength, distance);
  els.routeHead.setAttribute(
    "transform",
    `translate(${point.x.toFixed(2)} ${point.y.toFixed(2)}) rotate(${angle.toFixed(2)})`
  );
}

function animateRoute(pathLength) {
  cancelRouteAnimation();
  setRouteProgress(pathLength, 0);

  if (els.routeHead) {
    els.routeHead.setAttribute("display", "block");
  }

  const animationStart = performance.now();

  function step(timestamp) {
    const rawProgress = Math.min(1, (timestamp - animationStart) / ROUTE_ANIMATION_DURATION_MS);
    const easedProgress = easeInOutSine(rawProgress);

    setRouteProgress(pathLength, easedProgress);

    if (rawProgress < 1) {
      state.routeAnimationFrame = requestAnimationFrame(step);
      return;
    }

    setRouteProgress(pathLength, 1);
    state.routeAnimationFrame = null;
  }

  state.routeAnimationFrame = requestAnimationFrame(step);
}

function countTurns(points) {
  let turns = 0;
  for (let i = 2; i < points.length; i += 1) {
    const before = getSegmentDirection(points[i - 2], points[i - 1]).key;
    const after = getSegmentDirection(points[i - 1], points[i]).key;
    if (before !== after) turns += 1;
  }
  return turns;
}

function metersFromPixels(px) {
  return Math.max(1, Math.round(px / PIXELS_PER_METER));
}

function getLocations() {
  return {
    ...BASE_LOCATIONS,
    ...(state.customStart ? { customStart: state.customStart } : {}),
    ...(state.customDestination ? { customDestination: state.customDestination } : {})
  };
}

function getLocation(id) {
  return getLocations()[id];
}

function populateSelects() {
  const startValue = els.startSelect.value || "entrance";
  const destinationValue = els.destinationSelect.value || "opd";
  const locations = getLocations();

  function buildOptions() {
    return GROUP_ORDER.map(group => {
      const entries = Object.entries(locations).filter(([, location]) => location.group === group);
      if (entries.length === 0) return "";
      const optionHtml = entries
        .sort((a, b) => a[1].label.localeCompare(b[1].label))
        .map(([id, location]) => `<option value="${id}">${escapeHtml(location.label)}</option>`)
        .join("");
      return `<optgroup label="${escapeHtml(group)}">${optionHtml}</optgroup>`;
    }).join("");
  }

  const html = buildOptions();
  els.startSelect.innerHTML = html;
  els.destinationSelect.innerHTML = html;

  els.startSelect.value = locations[startValue] ? startValue : "entrance";
  els.destinationSelect.value = locations[destinationValue] ? destinationValue : "opd";
}

function renderBlockers() {
  els.blockerLayer.innerHTML = EXTRA_BLOCKERS.map(blocker => {
    const padding = blocker.padding || 0;
    return `<rect class="service-block" x="${blocker.x - padding}" y="${blocker.y - padding}" width="${blocker.width + padding * 2}" height="${blocker.height + padding * 2}" rx="6"><title>${escapeHtml(blocker.label)}</title></rect>`;
  }).join("");
}

function renderPois() {
  els.poiLayer.innerHTML = Object.entries(BASE_LOCATIONS).map(([, location]) => {
    const cls = location.type === "entry" ? "entry" : location.type === "emergency" ? "emergency" : location.type === "service" ? "service" : location.type === "hallway" ? "hallway" : "";
    return `<circle class="poi ${cls}" cx="${location.x}" cy="${location.y}" r="4.6"><title>${escapeHtml(location.label)}</title></circle>`;
  }).join("");
}

function markerSvg(location, kind) {
  const isStart = kind === "start";
  const markerClass = isStart
    ? "marker-pin-start"
    : location.type === "emergency"
      ? "marker-pin-destination marker-pin-emergency"
      : "marker-pin-destination";
  const label = isStart ? "Start" : "Destination";
  const labelX = isStart ? 13 : 17;
  const labelY = isStart ? -14 : -16;

  return `
    <g transform="translate(${location.x}, ${location.y})">
      <circle class="${markerClass}" r="10"></circle>
      <circle fill="#fff" r="3.2" opacity="0.95"></circle>
      <text class="marker-label" x="${labelX}" y="${labelY}">${label}</text>
    </g>
  `;
}

let routeAnimationFrameId = null;

function cancelRouteAnimation() {
  if (routeAnimationFrameId) {
    cancelAnimationFrame(routeAnimationFrameId);
    routeAnimationFrameId = null;
  }
}

function animateRouteDrawing(points, durationMs) {
  cancelRouteAnimation();

  const segments = [];
  let totalLength = 0;
  for (let i = 1; i < points.length; i++) {
    const p1 = points[i - 1];
    const p2 = points[i];
    const len = Math.abs(p2.x - p1.x) + Math.abs(p2.y - p1.y);
    segments.push({ p1, p2, len, startLen: totalLength });
    totalLength += len;
  }

  const startTime = performance.now();

  function step(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / durationMs, 1);
    const currentLength = totalLength * progress;

    let d = `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;
    
    for (const seg of segments) {
      if (currentLength >= seg.startLen + seg.len) {
        d += ` L ${seg.p2.x.toFixed(1)} ${seg.p2.y.toFixed(1)}`;
      } else if (currentLength > seg.startLen) {
        const segProgress = (currentLength - seg.startLen) / seg.len;
        const currentX = seg.p1.x + (seg.p2.x - seg.p1.x) * segProgress;
        const currentY = seg.p1.y + (seg.p2.y - seg.p1.y) * segProgress;
        d += ` L ${currentX.toFixed(1)} ${currentY.toFixed(1)}`;
        break;
      }
    }

    els.routeHalo.setAttribute("d", d);
    els.routeLine.setAttribute("d", d);

    if (progress < 1) {
      routeAnimationFrameId = requestAnimationFrame(step);
    }
  }

  routeAnimationFrameId = requestAnimationFrame(step);
}

function drawRoute(points, startLocation, destinationLocation) {
  els.routeLine.style.removeProperty("stroke-dasharray");
  els.routeLine.style.removeProperty("stroke-dashoffset");

  animateRouteDrawing(points, 2000);

  const startMarker = { ...startLocation, x: points[0].x, y: points[0].y };
  const destinationMarker = { ...destinationLocation, x: points[points.length - 1].x, y: points[points.length - 1].y };
  els.markerLayer.innerHTML = markerSvg(startMarker, "start") + markerSvg(destinationMarker, "destination");
}

function clearRoute() {
  cancelRouteAnimation();
  
  [els.routeHalo, els.routeLine].forEach(path => {
    path.style.removeProperty("stroke-dasharray");
    path.style.removeProperty("stroke-dashoffset");
  });
  els.routeHalo.setAttribute("d", "");
  els.routeLine.setAttribute("d", "");
  els.markerLayer.innerHTML = "";
}

function renderDirections(points, startLocation, destinationLocation) {
  const steps = [];
  steps.push({ badgeClass: "start", badge: "S", text: `Start at ${startLocation.label}.`, distance: "0 m" });

  for (let i = 1; i < points.length; i += 1) {
    const direction = getSegmentDirection(points[i - 1], points[i]);
    const segmentPixels = Math.abs(points[i].x - points[i - 1].x) + Math.abs(points[i].y - points[i - 1].y);
    const meters = metersFromPixels(segmentPixels);
    if (meters < 1) continue;
    steps.push({
      badgeClass: "",
      badge: `${direction.degree}°`,
      text: `${direction.label} only (${direction.icon}).`,
      distance: `${meters} m`
    });
  }

  steps.push({ badgeClass: "arrive", badge: "A", text: `Arrive at ${destinationLocation.label}.`, distance: "0 m" });

  els.directionsList.innerHTML = steps.map(step => `
    <li>
      <span class="step-badge ${step.badgeClass}">${escapeHtml(step.badge)}</span>
      <span>${escapeHtml(step.text)}</span>
      <span class="step-distance">${escapeHtml(step.distance)}</span>
    </li>
  `).join("");
}

function setStatus(text, warning = false) {
  // Removed routeStatus UI element
}

function runRoute() {
  const startLocation = getLocation(els.startSelect.value);
  const destinationLocation = getLocation(els.destinationSelect.value);

  if (!startLocation || !destinationLocation) {
    return;
  }

  const points = findOrthogonalPath(startLocation, destinationLocation);

  if (!points || points.length < 2) {
    clearRoute();
    els.directionsList.innerHTML = `<li><span class="step-badge">!</span><span>No safe 90 degree route found. Move the start or destination into an open walking area.</span></li>`;
    return;
  }

  drawRoute(points, startLocation, destinationLocation);

  renderDirections(points, startLocation, destinationLocation);
}

function mapPointFromEvent(event) {
  const rect = els.mapInner.getBoundingClientRect();
  const x = ((event.clientX - rect.left) / rect.width) * MAP_WIDTH;
  const y = ((event.clientY - rect.top) / rect.height) * MAP_HEIGHT;
  if (x < 0 || y < 0 || x > MAP_WIDTH || y > MAP_HEIGHT) return null;
  return { x, y };
}

function snapToWalkable(point) {
  const cell = nearestFreeCell(pointToCell(point), 45);
  if (!cell) return null;
  const snapped = cellToPoint(cell);
  return {
    ...snapped,
    snapped: Math.abs(snapped.x - point.x) > 1 || Math.abs(snapped.y - point.y) > 1
  };
}

function setCustomPoint(point, isDestination) {
  const snapped = snapToWalkable(point);
  if (!snapped) return;

  if (isDestination) {
    state.customDestination = { label: "Custom Destination", group: "Custom", x: snapped.x, y: snapped.y, type: "room" };
  } else {
    state.customStart = { label: "Custom Start / You are here", group: "Custom", x: snapped.x, y: snapped.y, type: "entry" };
  }

  populateSelects();
  if (isDestination) {
    els.destinationSelect.value = "customDestination";
  } else {
    els.startSelect.value = "customStart";
  }

  runRoute();
}

function setZoom(percent) {
  state.zoomPercent = Math.max(80, Math.min(260, percent));
  els.mapInner.style.width = `${state.zoomPercent}%`;
  els.zoomResetBtn.innerText = `${state.zoomPercent}%`;
}

function resetCustomPoints() {
  state.customStart = null;
  state.customDestination = null;
  populateSelects();
  els.startSelect.value = "entrance";
  els.destinationSelect.value = "opd";
  runRoute();
}

function init() {
  buildGrid();
  populateSelects();
  renderBlockers();
  renderPois();

  // Read URL parameters
  const params = new URLSearchParams(window.location.search);
  const destParam = params.get("destination");
  if (destParam && getLocation(destParam)) {
    els.destinationSelect.value = destParam;
  }
  
  const embeddedParam = params.get("embedded");
  if (embeddedParam === "true") {
    document.body.classList.add("embedded-mode");
  }

  runRoute();

  els.findRouteBtn.addEventListener("click", runRoute);
  els.startSelect.addEventListener("change", runRoute);
  els.destinationSelect.addEventListener("change", runRoute);
  els.resetBtn.addEventListener("click", resetCustomPoints);

  document.querySelectorAll("[data-destination]").forEach(button => {
    button.addEventListener("click", () => {
      els.destinationSelect.value = button.dataset.destination;
      runRoute();
    });
  });

  els.mapInner.addEventListener("click", event => {
    if (document.body.classList.contains("embedded-mode")) return;
    const point = mapPointFromEvent(event);
    if (!point) return;
    setCustomPoint(point, event.shiftKey);
  });

  els.mapInner.addEventListener("mousemove", event => {
    const point = mapPointFromEvent(event);
    if (!point) return;
  });

  els.zoomInBtn.addEventListener("click", () => setZoom(state.zoomPercent + 20));
  els.zoomOutBtn.addEventListener("click", () => setZoom(state.zoomPercent - 20));
  els.zoomResetBtn.addEventListener("click", () => setZoom(100));
}

init();
