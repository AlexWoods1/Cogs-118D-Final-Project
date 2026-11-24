/** @typedef {[number, number]} Cell */
/** @typedef {[Cell, Cell]} Edge */
/** @typedef {'test' | 'pilot'} Phase */
/** @typedef {{label: string, reflected: boolean, symbol: 'circle' | 'diamond', beacon: Edge | null, edges: Edge[], learned: Cell[], shortcut: Cell[], junction: Cell}} Trial */
/** @typedef {{seed: string, participantIndex: string, width: number, height: number, start: Cell, goal: Cell, visible: Cell[], test: Trial[], pilot: Trial[]}} PreviewData */
/** @typedef {{visible: Set<string> | null, open: Set<string>, corridors: Set<string>}} Board */

/**
 * Return an element required by the preview template.
 * @param {string} id
 * @returns {HTMLElement}
 */
function byId(id) {
  const element = document.getElementById(id);
  // A missing element indicates a mismatch between the template and the renderer.
  if (!element) throw new Error(`Missing preview element ${id}`);
  return element;
}

const data = /** @type {PreviewData} */ (JSON.parse(byId('data').textContent ?? ''));
const phase = /** @type {HTMLSelectElement} */ (byId('phase'));
const selection = /** @type {HTMLSelectElement} */ (byId('trial'));
const participant = /** @type {HTMLCanvasElement} */ (byId('participant'));
const full = /** @type {HTMLCanvasElement} */ (byId('full'));
const visibleCells = new Set(data.visible.map(String));
const palette = getComputedStyle(document.documentElement);

/**
 * Read a color shared by the canvas and the legend.
 * @param {string} name
 * @returns {string}
 */
function color(name) {
  // Canvas needs the resolved value of the CSS variable.
  return palette.getPropertyValue(name).trim();
}

/**
 * Build a lookup key for an undirected edge.
 * @param {Cell} first
 * @param {Cell} second
 * @returns {string}
 */
function edgeKey(first, second) {
  // Either order must match the same opening in the generated data.
  return [String(first), String(second)].sort().join('|');
}

/**
 * Return a cell's position in canvas coordinates measured in grid units.
 * @param {Cell} cell
 * @returns {Cell}
 */
function center([x, y]) {
  // Cell coordinates refer to the top-left corner of a grid square.
  return [x + .5, y + .5];
}

/**
 * Check whether a cell contributes to the displayed geometry.
 * @param {Set<string> | null} visible
 * @param {Cell} cell
 * @returns {boolean}
 */
function isKnown(visible, cell) {
  // The full layout has no starting visibility mask.
  return visible === null || visible.has(String(cell));
}

/**
 * Index the openings that the displayed view can reveal.
 * @param {Trial} trial
 * @param {Set<string> | null} visible
 * @returns {Board}
 */
function boardFor(trial, visible) {
  const open = new Set();
  const corridors = new Set();
  for (const [first, second] of trial.edges) {
    // Ignore edges entirely under fog before identifying any corridor tiles.
    if (!isKnown(visible, first) && !isKnown(visible, second)) continue;
    open.add(edgeKey(first, second));
    corridors.add(String(first));
    corridors.add(String(second));
  }
  return { visible, open, corridors };
}

/**
 * Stroke a polyline in grid coordinates.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Cell[]} points
 * @param {string} ink
 * @param {number} width
 * @param {number[]} [dash]
 * @returns {void}
 */
function stroke(ctx, points, ink, width, dash = []) {
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(...points[0]);
  for (const point of points.slice(1)) ctx.lineTo(...point);
  ctx.lineWidth = width;
  ctx.strokeStyle = ink;
  ctx.setLineDash(dash);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.stroke();
  // Route dashes must not carry into later markers or wall segments.
  ctx.restore();
}

/**
 * Draw a filled circle with an outline in grid coordinates.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Cell} point
 * @param {number} radius
 * @param {string} fill
 * @param {string} ink
 * @param {number} [width]
 * @returns {void}
 */
function disk(ctx, point, radius, fill, ink, width = .05) {
  ctx.beginPath();
  ctx.arc(...point, radius, 0, Math.PI * 2);
  ctx.fillStyle = fill;
  ctx.fill();
  // The outline separates light markers from the corridor floor.
  ctx.strokeStyle = ink;
  ctx.lineWidth = width;
  ctx.stroke();
}

/**
 * Draw one boundary using the two cells that share it.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Board} board
 * @param {Cell} first
 * @param {Cell} second
 * @param {Edge} segment
 * @returns {void}
 */
function drawBoundary(ctx, board, first, second, segment) {
  const firstKnown = isKnown(board.visible, first);
  const secondKnown = isKnown(board.visible, second);
  if (!firstKnown && !secondKnown) return;
  if (board.open.has(edgeKey(first, second))) {
    // A light grid line marks an opening inside the view. At the fog boundary it stays clear.
    if (firstKnown && secondKnown) stroke(ctx, segment, '#dce6eb', .018);
    return;
  }
  const bordersCorridor = board.corridors.has(String(first)) || board.corridors.has(String(second));
  stroke(ctx, segment, bordersCorridor ? '#304456' : '#9db1bf', bordersCorridor ? .085 : .025);
}

/**
 * Draw the displayed floor and walls.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Board} board
 * @returns {void}
 */
function drawBoard(ctx, board) {
  for (let y = 0; y < data.height; y++) {
    for (let x = 0; x < data.width; x++) {
      const cell = /** @type {Cell} */ ([x, y]);
      if (!isKnown(board.visible, cell)) continue;
      ctx.fillStyle = board.corridors.has(String(cell)) ? '#fff' : '#dce6eb';
      ctx.fillRect(x, y, 1, 1);
    }
  }
  // Visit each horizontal and vertical boundary once, including the outer edges.
  for (let y = 0; y <= data.height; y++) {
    for (let x = 0; x <= data.width; x++) {
      if (x < data.width) drawBoundary(ctx, board, [x, y - 1], [x, y], [[x, y], [x + 1, y]]);
      if (y < data.height) drawBoundary(ctx, board, [x - 1, y], [x, y], [[x, y], [x, y + 1]]);
    }
  }
}

/**
 * Draw the learned route, center shortcut, and later junction.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Trial} trial
 * @returns {void}
 */
function drawRoutes(ctx, trial) {
  // The dashed shortcut remains identifiable where the two paths share a cell.
  stroke(ctx, trial.learned.map(center), color('--learned'), .15);
  stroke(ctx, trial.shortcut.map(center), color('--shortcut'), .14, [.20, .16]);
  disk(ctx, center(trial.junction), .185, '#fff', '#304456', .085);
}

/**
 * Draw one endpoint label using the legibility floor for small screens.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Cell} cell
 * @param {'S' | 'G'} label
 * @param {number} minimumSize
 * @returns {void}
 */
function drawEndpoint(ctx, cell, label, minimumSize) {
  const point = center(cell);
  const isStart = label === 'S';
  // Give the visible goal marker a light fill so it stays readable over fog.
  disk(ctx, point, .29, isStart ? '#24455d' : '#fff', '#24455d');
  ctx.fillStyle = isStart ? '#fff' : '#24455d';
  ctx.font = `700 ${Math.max(.36, minimumSize)}px system-ui`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(label, ...point);
}

/**
 * Draw the learned orientation symbol immediately above the start.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Trial['symbol']} symbol
 * @returns {void}
 */
function drawSymbol(ctx, symbol) {
  const [x, y] = center([data.start[0], data.start[1] - 1]);
  if (symbol === 'circle') {
    disk(ctx, [x, y], .19, '#fff', '#304456', .065);
    return;
  }
  // The diamond gives the orientation cue a shape distinct from the endpoints.
  ctx.beginPath();
  ctx.moveTo(x, y - .23);
  ctx.lineTo(x + .23, y);
  ctx.lineTo(x, y + .23);
  ctx.lineTo(x - .23, y);
  ctx.closePath();
  ctx.fillStyle = '#fff';
  ctx.fill();
  ctx.strokeStyle = '#304456';
  ctx.lineWidth = .065;
  ctx.stroke();
}

/**
 * Draw the beacon on its boundary without changing the wall.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Edge} beacon
 * @returns {void}
 */
function drawBeacon(ctx, beacon) {
  const [a, b] = beacon.map(center);
  const x = (a[0] + b[0]) / 2;
  const y = (a[1] + b[1]) / 2;
  // A perpendicular offset follows the shared boundary between the two cells.
  const dx = (b[1] - a[1]) * .25;
  const dy = (a[0] - b[0]) * .25;
  const segment = /** @type {Edge} */ ([[x - dx, y - dy], [x + dx, y + dy]]);
  stroke(ctx, segment, '#70461e', .24);
  stroke(ctx, segment, color('--beacon'), .15);
}

/**
 * Render one maze panel for the selected trial.
 * @param {HTMLCanvasElement} canvas
 * @param {Trial} trial
 * @param {boolean} showFullLayout
 * @returns {void}
 */
function drawMaze(canvas, trial, showFullLayout) {
  const bounds = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.round(bounds.width * scale);
  canvas.height = Math.round(bounds.height * scale);
  const ctx = canvas.getContext('2d');
  const size = Math.min((canvas.width - 18 * scale) / data.width, (canvas.height - 18 * scale) / data.height);
  if (!ctx || size <= 0) return;

  ctx.fillStyle = showFullLayout ? '#e6edf1' : color('--fog');
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  // Work in grid units after centering the drawing on the device-pixel canvas.
  ctx.translate((canvas.width - data.width * size) / 2, (canvas.height - data.height * size) / 2);
  ctx.scale(size, size);

  drawBoard(ctx, boardFor(trial, showFullLayout ? null : visibleCells));
  if (showFullLayout) drawRoutes(ctx, trial);
  drawEndpoint(ctx, data.start, 'S', 11 * scale / size);
  drawEndpoint(ctx, data.goal, 'G', 11 * scale / size);
  drawSymbol(ctx, trial.symbol);
  if (trial.beacon) drawBeacon(ctx, trial.beacon);
}

/**
 * Return the current phase's schedule in presentation order.
 * @returns {Trial[]}
 */
function currentSchedule() {
  // The template supplies only the two phase names used in the generated payload.
  const key = /** @type {Phase} */ (phase.value);
  return data[key];
}

/**
 * Redraw both canvases using the current selection and dimensions.
 * @returns {void}
 */
function redraw() {
  const trial = currentSchedule()[selection.selectedIndex];
  // Both panels show the same trial so the fog can be compared spatially.
  drawMaze(participant, trial, false);
  drawMaze(full, trial, true);
}

/**
 * Describe the selected trial and refresh both drawings.
 * @returns {void}
 */
function updateTrial() {
  const trial = currentSchedule()[selection.selectedIndex];
  const learned = trial.learned.length - 1;
  const shortcut = trial.shortcut.length - 1;
  const beacon = trial.beacon
    ? `${trial.beacon[0][0] < data.start[0] ? 'Left' : 'Right'} beacon`
    : 'No beacon';
  const orientation = trial.reflected ? 'Reflected layout' : 'Original layout';
  byId('trial-summary').textContent = `${orientation} · ${beacon}`;
  byId('symbol-mark').textContent = trial.symbol === 'diamond' ? '◇' : '○';
  byId('savings').textContent = `The shortcut saves ${learned - shortcut} moves.`;
  byId('learned-length').textContent = `Learned route (${learned} moves)`;
  byId('shortcut-length').textContent = `Shortcut (${shortcut} moves)`;
  // Provide text equivalents for the cues and scoring overlays on both canvases.
  participant.setAttribute('aria-label', `Start and goal, ${trial.symbol} orientation symbol, ${beacon.toLowerCase()}, and walls visible at the start.`);
  full.setAttribute('aria-label', `${orientation}. Learned route, ${learned} moves. Shortcut, ${shortcut} moves. The later junction is marked on the learned route.`);
  redraw();
}

/**
 * Populate the trial selector for the current phase.
 * @returns {void}
 */
function updatePhase() {
  selection.replaceChildren();
  for (const trial of currentSchedule()) selection.add(new Option(trial.label));
  // A phase change starts at the first trial in the new schedule.
  selection.selectedIndex = 0;
  updateTrial();
}

byId('session').textContent = `Seed ${data.seed} · Participant index ${data.participantIndex}`;
phase.addEventListener('change', updatePhase);
selection.addEventListener('change', updateTrial);
updatePhase();
const resize = new ResizeObserver(redraw);
resize.observe(participant);
resize.observe(full);
