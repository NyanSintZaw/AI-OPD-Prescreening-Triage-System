const DIRECTIONS = [
  { dx: 1, dy: 0, key: "right", label: "Go right", degree: 360, icon: "→" },
  { dx: -1, dy: 0, key: "left", label: "Go left", degree: 180, icon: "←" },
  { dx: 0, dy: -1, key: "up", label: "Go up", degree: 90, icon: "↑" },
  { dx: 0, dy: 1, key: "down", label: "Go down", degree: 270, icon: "↓" }
];

const GROUP_ORDER = ["Access", "Service", "Emergency", "Department", "Clinic", "Custom"];

// The triage app opens this page with ?destination=<location>&embedded=true.
// Embedded mode is the small non-interactive preview inside the
// recommendation card; without it the page is the full kiosk viewer.
const URL_PARAMS = new URLSearchParams(window.location.search);
const EMBEDDED = URL_PARAMS.get("embedded") === "true";

const state = {
  floors: {},
  activeFloorId: null,
  customStart: null,
  isAutoRouting: true,
  currentRoute: null
};

const els = {
  startSelect: document.getElementById("startSelect"),
  destinationSelect: document.getElementById("destinationSelect"),
  findRouteBtn: document.getElementById("findRouteBtn"),
  resetBtn: document.getElementById("resetBtn"),
  blockerLayer: document.getElementById("blockerLayer"),
  poiLayer: document.getElementById("poiLayer"),
  routeHalo: document.getElementById("routeHalo"),
  routeLine: document.getElementById("routeLine"),
  turnLayer: document.getElementById("turnLayer"),
  markerLayer: document.getElementById("markerLayer"),
  mapViewport: document.getElementById("mapViewport"),
  mapInner: document.getElementById("mapInner"),
  transitionOverlay: document.getElementById("transitionOverlay"),
  transitionText: document.getElementById("transitionText"),
  floorImage: document.getElementById("floorImage"),
  routeOverlay: document.getElementById("routeOverlay"),
  floorSwitcher: document.getElementById("kioskFloorSwitcher"),
  plannerCard: document.getElementById("plannerCard"),
  brandChip: document.querySelector(".brand-chip"),
  toast: document.getElementById("toast")
};

let toastTimer = null;

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => els.toast.classList.remove("show"), 3500);
}

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

function isBlockedPoint(x, y, floor, padding = WALL_PADDING) {
  if (x < 0 || y < 0 || x > floor.mapWidth || y > floor.mapHeight) {
    return true;
  }

  for (const blocker of (floor.blockers || [])) {
    if (pointInsideBlocker(x, y, blocker)) return true;
  }

  for (const wall of (floor.walls || [])) {
    const radius = wall.w / 2 + padding;
    const minX = Math.min(wall.x1, wall.x2) - radius;
    const maxX = Math.max(wall.x1, wall.x2) + radius;
    const minY = Math.min(wall.y1, wall.y2) - radius;
    const maxY = Math.max(wall.y1, wall.y2) + radius;

    if (x < minX || x > maxX || y < minY || y > maxY) continue;
    if (distancePointToSegment(x, y, wall) <= radius) return true;
  }

  return false;
}

function buildGrid() {
  state.floors = {};
  FLOORS.forEach(floor => {
    const cols = Math.ceil(floor.mapWidth / CELL_SIZE);
    const rows = Math.ceil(floor.mapHeight / CELL_SIZE);
    const grid = Array.from({ length: rows }, () => Array(cols).fill(false));

    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < cols; col += 1) {
        const x = (col + 0.5) * CELL_SIZE;
        const y = (row + 0.5) * CELL_SIZE;
        grid[row][col] = isBlockedPoint(x, y, floor);
      }
    }

    const clearancePenalty = buildClearancePenalty(grid, cols, rows);

    state.floors[floor.id] = {
      ...floor,
      cols,
      rows,
      grid,
      clearancePenalty
    };
  });
  
  if (FLOORS.length > 0) {
    state.activeFloorId = FLOORS[0].id;
  }
}

function buildClearancePenalty(grid, cols, rows) {
  const penalty = Array.from({ length: rows }, () => Array(cols).fill(0));
  const radius = 5;

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      if (grid[row][col]) {
        penalty[row][col] = 99;
        continue;
      }

      let blockedNeighbors = 0;
      for (let dr = -radius; dr <= radius; dr += 1) {
        for (let dc = -radius; dc <= radius; dc += 1) {
          if (dc === 0 && dr === 0) continue;
          const r2 = row + dr;
          const c2 = col + dc;
          if (r2 < 0 || c2 < 0 || r2 >= rows || c2 >= cols || grid[r2][c2]) {
            blockedNeighbors += 1;
          }
        }
      }
      penalty[row][col] = Math.min(0.65, blockedNeighbors * 0.01);
    }
  }
  return penalty;
}

function cellPenalty(col, row, floorId) {
  const floor = state.floors[floorId];
  if (!floor || !floor.clearancePenalty) return 0;
  return floor.clearancePenalty[row]?.[col] || 0;
}

function pointToCell(point, floorId) {
  const floor = state.floors[floorId];
  return {
    col: Math.max(0, Math.min(floor.cols - 1, Math.floor(point.x / CELL_SIZE))),
    row: Math.max(0, Math.min(floor.rows - 1, Math.floor(point.y / CELL_SIZE)))
  };
}

function cellToPoint(cell) {
  return {
    x: (cell.col + 0.5) * CELL_SIZE,
    y: (cell.row + 0.5) * CELL_SIZE
  };
}

function isCellBlocked(col, row, floorId) {
  const floor = state.floors[floorId];
  return row < 0 || col < 0 || row >= floor.rows || col >= floor.cols || floor.grid[row][col];
}

function cellKey(col, row, direction = "") {
  return `${col},${row},${direction}`;
}

function nearestFreeCell(cell, floorId, maxRadius = 40) {
  if (!isCellBlocked(cell.col, cell.row, floorId)) {
    return cell;
  }

  for (let radius = 1; radius <= maxRadius; radius += 1) {
    const options = [];
    for (let dr = -radius; dr <= radius; dr += 1) {
      for (let dc = -radius; dc <= radius; dc += 1) {
        if (Math.abs(dc) !== radius && Math.abs(dr) !== radius) continue;
        const col = cell.col + dc;
        const row = cell.row + dr;
        if (!isCellBlocked(col, row, floorId)) {
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

function findOrthogonalPath(startPoint, endPoint, floorId) {
  const startCell = nearestFreeCell(pointToCell(startPoint, floorId), floorId);
  const endCell = nearestFreeCell(pointToCell(endPoint, floorId), floorId);

  if (!startCell || !endCell) return null;

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

      if (isCellBlocked(nextCol, nextRow, floorId)) continue;

      const nextKey = cellKey(nextCol, nextRow, direction.key);
      const turnCost = current.direction !== "start" && current.direction !== direction.key ? TURN_PENALTY : 0;
      const newCost = currentCost + 1 + turnCost + cellPenalty(nextCol, nextRow, floorId);

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

function metersFromPixels(px) {
  return Math.max(1, Math.round(px / PIXELS_PER_METER));
}

function getLocations() {
  const locs = {};
  FLOORS.forEach(floor => {
    Object.entries(floor.locations).forEach(([id, loc]) => {
      locs[`${floor.id}_${id}`] = { ...loc, floorId: floor.id, originalId: id };
    });
  });
  
  if (state.customStart) locs.customStart = state.customStart;
  if (state.customDestination) locs.customDestination = state.customDestination;
  return locs;
}

function getLocation(id) {
  return getLocations()[id];
}

// Resolve a ?destination=/?start= URL value to a location id. Accepts the
// combined id ("F1_OPD"), the per-floor id ("OPD") or the display label
// ("Cardiology"), all case-insensitively, so callers don't need to know
// which floor a department sits on.
function resolveLocationId(value) {
  if (!value) return null;
  const target = String(value).trim().toLowerCase();
  if (!target) return null;
  const locations = getLocations();
  const matchers = [
    ([id]) => id.toLowerCase() === target,
    ([, location]) => (location.originalId || "").toLowerCase() === target,
    ([, location]) => (location.label || "").toLowerCase() === target
  ];
  for (const matches of matchers) {
    const entry = Object.entries(locations).find(matches);
    if (entry) return entry[0];
  }
  return null;
}

function populateSelects() {
  const startValue = els.startSelect.value;
  const destinationValue = els.destinationSelect.value;
  const locations = getLocations();

  function buildOptions() {
    return GROUP_ORDER.map(group => {
      const entries = Object.entries(locations).filter(([, location]) => location.group === group);
      if (entries.length === 0) return "";
      const optionHtml = entries
        .sort((a, b) => a[1].label.localeCompare(b[1].label))
        .map(([id, location]) => {
          return `<option value="${id}">${escapeHtml(location.label)}</option>`;
        })
        .join("");
      return `<optgroup label="${escapeHtml(group)}">${optionHtml}</optgroup>`;
    }).join("");
  }

  const html = buildOptions();
  els.startSelect.innerHTML = html;
  els.destinationSelect.innerHTML = html;
  
  const allIds = Object.keys(locations);
  const entId = allIds.find(k => locations[k].type === "entry") || allIds.find(k => locations[k].type === "hallway") || allIds[0];
  const destId = allIds.find(k => locations[k].label === "OPD") || allIds[1];
  
  els.startSelect.value = locations[startValue] ? startValue : entId;
  els.destinationSelect.value = locations[destinationValue] ? destinationValue : destId;
}

function setupFloorSwitcher() {
  const switcherHtml = FLOORS.map(f => {
    return `<button class="pill ${state.activeFloorId === f.id ? 'success' : 'outline'}" data-floor-id="${f.id}">
      ${escapeHtml(f.name)}
    </button>`;
  }).join('');
  
  els.floorSwitcher.innerHTML = switcherHtml;
  
  els.floorSwitcher.querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', () => {
      state.isAutoRouting = false;
      renderFloor(btn.dataset.floorId);
    });
  });
}

function renderFloor(floorId) {
  state.activeFloorId = floorId;
  const floor = state.floors[floorId];

  els.floorImage.src = floor.mapImageSrc || 'assets/floor-map.svg';
  els.routeOverlay.setAttribute('viewBox', `0 0 ${floor.mapWidth} ${floor.mapHeight}`);
  fitMap();

  renderBlockers();
  renderPois();
  setupFloorSwitcher();
  displayCurrentRoute();
}

function renderBlockers() {
  const floor = state.floors[state.activeFloorId];
  if (!floor) return;
  els.blockerLayer.innerHTML = (floor.blockers || []).map(blocker => {
    const padding = blocker.padding || 0;
    return `<rect class="service-block" x="${blocker.x - padding}" y="${blocker.y - padding}" width="${blocker.width + padding * 2}" height="${blocker.height + padding * 2}" rx="6"><title>${escapeHtml(blocker.label)}</title></rect>`;
  }).join("");
}

function renderPois() {
  const floor = state.floors[state.activeFloorId];
  if (!floor) return;
  els.poiLayer.innerHTML = Object.entries(floor.locations).map(([, location]) => {
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

function clearRoute() {
  if (routeAnimationFrameId) {
    cancelAnimationFrame(routeAnimationFrameId);
    routeAnimationFrameId = null;
  }
  
  [els.routeHalo, els.routeLine].forEach(path => {
    path.style.removeProperty("stroke-dasharray");
    path.style.removeProperty("stroke-dashoffset");
    path.setAttribute("d", "");
  });
  els.markerLayer.innerHTML = "";
}

function animateRouteDrawing(points, durationMs, onComplete) {
  if (routeAnimationFrameId) {
    cancelAnimationFrame(routeAnimationFrameId);
    routeAnimationFrameId = null;
  }

  if (!state.isAutoRouting) {
    let d = `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;
    for (let i = 1; i < points.length; i++) {
      d += ` L ${points[i].x.toFixed(1)} ${points[i].y.toFixed(1)}`;
    }
    els.routeHalo.setAttribute("d", d);
    els.routeLine.setAttribute("d", d);
    if (onComplete) onComplete();
    return;
  }

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
    } else if (onComplete) {
      onComplete();
    }
  }

  routeAnimationFrameId = requestAnimationFrame(step);
}

function drawRoute(points, stops, onComplete) {
  els.routeLine.style.removeProperty("stroke-dasharray");
  els.routeLine.style.removeProperty("stroke-dashoffset");

  animateRouteDrawing(points, 2000, onComplete);

  let markersHtml = "";
  for (let i = 0; i < stops.length; i++) {
    let type = "waypoint";
    let x = stops[i].x;
    let y = stops[i].y;
    
    if (i === 0) {
       type = "start";
       x = points[0].x;
       y = points[0].y;
    } else if (i === stops.length - 1) {
       type = "destination";
       x = points[points.length - 1].x;
       y = points[points.length - 1].y;
    }
    const markerLoc = { ...stops[i], x, y };
    markersHtml += markerSvg(markerLoc, type);
  }
  
  els.markerLayer.innerHTML = markersHtml;
}

function displayCurrentRoute() {
  if (!state.currentRoute) {
    clearRoute();
    return;
  }
  
  const rt = state.currentRoute;
  
  if (rt.type === 'single') {
    if (state.activeFloorId === rt.floorId) {
      drawRoute(rt.path, rt.stops);
    } else {
      clearRoute();
    }
  } else {
    if (state.activeFloorId === rt.floor1) {
      drawRoute(rt.path1, rt.stops1, state.isAutoRouting ? () => {
        setTimeout(() => {
          if (state.currentRoute === rt && state.activeFloorId === rt.floor1) {
            const nextFloorName = state.floors[rt.floor2].name;
            els.transitionText.innerText = `Take the elevator to ${nextFloorName}...`;
            els.transitionOverlay.style.display = 'flex';
            
            // trigger CSS transition
            setTimeout(() => {
              els.transitionOverlay.classList.add('show');
            }, 10);
            
            setTimeout(() => {
              if (state.currentRoute === rt) {
                renderFloor(rt.floor2);
                els.transitionOverlay.classList.remove('show');
                setTimeout(() => {
                  els.transitionOverlay.style.display = 'none';
                }, 300);
              } else {
                els.transitionOverlay.classList.remove('show');
                els.transitionOverlay.style.display = 'none';
              }
            }, 2000);
          }
        }, 200);
      } : null);
    } else if (state.activeFloorId === rt.floor2) {
      drawRoute(rt.path2, rt.stops2);
    } else {
      clearRoute();
    }
  }
}

function runRoute() {
  state.isAutoRouting = true;
  const startLocation = state.customStart || getLocation(els.startSelect.value);
  const destinationLocation = getLocation(els.destinationSelect.value);
  
  if (!startLocation || !destinationLocation) {
    clearRoute();
    return;
  }
  
  if (startLocation.floorId === destinationLocation.floorId) {
    const path = findOrthogonalPath(startLocation, destinationLocation, startLocation.floorId);
    if (!path) {
      state.currentRoute = null;
      clearRoute();
      showToast("No safe route found. Try a different start or destination.");
      return;
    }
    state.currentRoute = {
      type: 'single',
      floorId: startLocation.floorId,
      path,
      stops: [startLocation, destinationLocation]
    };
  } else {
    const elevators1 = Object.values(state.floors[startLocation.floorId].locations).filter(l => l.type === 'elevator');
    const elevators2 = Object.values(state.floors[destinationLocation.floorId].locations).filter(l => l.type === 'elevator');
      
    let bestElevatorLabel = null;
    let shortestLen = Infinity;
    let bestPath1 = null;
    let bestPath2 = null;
    let elevatorLoc1 = null;
    let elevatorLoc2 = null;

    elevators1.forEach(e1 => {
      const e2 = elevators2.find(e => e.label === e1.label);
      if (e2) {
        const path1 = findOrthogonalPath(startLocation, e1, startLocation.floorId);
        const path2 = findOrthogonalPath(e2, destinationLocation, destinationLocation.floorId);
        if (path1 && path2) {
          const len = routeLength(path1) + routeLength(path2);
          if (len < shortestLen) {
            shortestLen = len;
            bestElevatorLabel = e1.label;
            bestPath1 = path1;
            bestPath2 = path2;
            elevatorLoc1 = { ...e1, floorId: startLocation.floorId };
            elevatorLoc2 = { ...e2, floorId: destinationLocation.floorId };
          }
        }
      }
    });

    if (!bestPath1) {
      state.currentRoute = null;
      clearRoute();
      showToast("No elevator route found between floors.");
      return;
    }
    
    state.currentRoute = {
      type: 'multi',
      floor1: startLocation.floorId,
      floor2: destinationLocation.floorId,
      path1: bestPath1,
      path2: bestPath2,
      stops1: [startLocation, elevatorLoc1],
      stops2: [elevatorLoc2, destinationLocation],
      elevatorLabel: bestElevatorLabel
    };
    
    if (state.activeFloorId !== startLocation.floorId) {
       renderFloor(startLocation.floorId);
       return; 
    }
  }
  
  displayCurrentRoute();
}

function mapPointFromEvent(event) {
  const rect = els.mapInner.getBoundingClientRect();
  const floor = state.floors[state.activeFloorId];
  const x = ((event.clientX - rect.left) / rect.width) * floor.mapWidth;
  const y = ((event.clientY - rect.top) / rect.height) * floor.mapHeight;
  if (x < 0 || y < 0 || x > floor.mapWidth || y > floor.mapHeight) return null;
  return { x, y };
}

function snapToWalkable(point, floorId) {
  const cell = nearestFreeCell(pointToCell(point, floorId), floorId, 45);
  if (!cell) return null;
  const snapped = cellToPoint(cell);
  return {
    ...snapped,
    snapped: Math.abs(snapped.x - point.x) > 1 || Math.abs(snapped.y - point.y) > 1
  };
}

function resetCustomPoints() {
  state.customStart = null;
  state.customDestination = null;
  populateSelects();
  runRoute();
}


function fitMap() {
  const floor = state.floors[state.activeFloorId];
  if (!floor) return;

  const stageW = els.mapViewport.clientWidth;
  const stageH = els.mapViewport.clientHeight;
  if (!stageW || !stageH) return;

  // Reserve the bands the floating chrome occupies, then fit the whole
  // floor into what remains — aspect ratio preserved, so nothing can
  // cover the map and the kiosk never needs to scroll or pan.
  // Portrait: planner card sits along the bottom edge.
  // Landscape: planner card is docked on the left (mirrors the CSS
  // orientation media query).
  const pad = 14;
  const chromeH = Math.max(
    els.floorSwitcher?.offsetHeight || 0,
    els.brandChip?.offsetHeight || 0
  );
  const topReserve = chromeH + pad * 2;

  const isLandscape = stageW > stageH;
  let leftReserve = pad;
  let bottomReserve = pad;
  if (isLandscape) {
    leftReserve = (els.plannerCard?.offsetWidth || 0) + pad * 2;
  } else {
    bottomReserve = (els.plannerCard?.offsetHeight || 0) + pad * 2;
  }

  const availW = Math.max(160, stageW - leftReserve - pad);
  const availH = Math.max(160, stageH - topReserve - bottomReserve);

  const scale = Math.min(availW / floor.mapWidth, availH / floor.mapHeight);
  const width = Math.floor(floor.mapWidth * scale);
  const height = Math.floor(floor.mapHeight * scale);

  els.mapInner.style.width = `${width}px`;
  els.mapInner.style.height = `${height}px`;
  els.mapInner.style.left = `${Math.floor(leftReserve + (availW - width) / 2)}px`;
  els.mapInner.style.top = `${Math.floor(topReserve + (availH - height) / 2)}px`;

  // Keep the route line a constant thickness on screen. The widths are
  // in map units, so dividing by the scale makes line, halo and the
  // arrow marker (markerUnits="strokeWidth") render identically at any
  // map size — no misaligned caps or arrowheads on small screens.
  els.routeLine.style.strokeWidth = (7 / scale).toFixed(3);
  els.routeHalo.style.strokeWidth = (15 / scale).toFixed(3);
}


function init() {
  if (EMBEDDED) {
    document.body.classList.add("embedded-mode");
  }

  buildGrid();

  if (FLOORS.length > 0) {
    renderFloor(state.activeFloorId);
  }

  populateSelects();

  const startParam = resolveLocationId(URL_PARAMS.get("start"));
  if (startParam) {
    els.startSelect.value = startParam;
  }
  const destinationParam = resolveLocationId(URL_PARAMS.get("destination"));
  if (destinationParam) {
    els.destinationSelect.value = destinationParam;
  }

  runRoute();

  els.findRouteBtn.addEventListener("click", runRoute);
  els.startSelect.addEventListener("change", () => {
    state.customStart = null; 
    populateSelects();
    runRoute();
  });
  els.destinationSelect.addEventListener("change", () => {
    runRoute();
  });
  els.resetBtn.addEventListener("click", resetCustomPoints);

  els.mapInner.addEventListener("click", event => {
    if (EMBEDDED) return;
    const point = mapPointFromEvent(event);
    if (!point) return;
    const snapped = snapToWalkable(point, state.activeFloorId);
    if (!snapped) return;

    const stop = { 
      label: "Custom Start", 
      group: "Custom", 
      x: snapped.x, 
      y: snapped.y, 
      type: "entry",
      floorId: state.activeFloorId
    };

    state.customStart = stop;
    populateSelects();
    els.startSelect.value = "customStart";
    runRoute();
  });
}

init();



// Refit whenever the stage or the planner card changes size (e.g. the
// route summary appears) so the map never gets covered.
const mapObserver = new ResizeObserver(() => fitMap());
mapObserver.observe(els.mapViewport);
mapObserver.observe(els.plannerCard);
