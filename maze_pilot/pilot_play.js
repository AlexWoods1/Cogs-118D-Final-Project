/** @typedef {[number, number]} Cell */
/** @typedef {[Cell, Cell]} Edge */
/** @typedef {'learned' | 'shortcut' | 'other' | 'timeout'} FirstChoice */
/** @typedef {'learned' | 'alternate' | 'none'} Continuation */
/**
 * @typedef {{
 *   label: string,
 *   kind: string | null,
 *   landmark: string | null,
 *   timed: boolean,
 *   deadline_ms: number | null,
 *   guidance: 'full' | 'fade' | 'none',
 *   reflected: boolean,
 *   symbol: 'circle' | 'diamond',
 *   beacon: Edge | null,
 *   edges: Edge[],
 *   learned_side: 'left' | 'right',
 *   learned_route: Cell[],
 *   later_junction: Cell,
 *   shortcut_savings: number
 * }} PlayTrial
 */
/**
 * @typedef {{
 *   seed: string,
 *   participantIndex: string,
 *   phase: 'test' | 'pilot',
 *   width: number,
 *   height: number,
 *   start: Cell,
 *   goal: Cell,
 *   centerEntry: Cell,
 *   initialVisible: Cell[],
 *   trials: PlayTrial[]
 * }} PlayData
 */
/**
 * @typedef {{
 *   trialIndex: number,
 *   label: string,
 *   kind: string | null,
 *   landmark: string | null,
 *   timed: boolean,
 *   firstChoice: FirstChoice | null,
 *   firstChoiceRtMs: number | null,
 *   laterContinuation: Continuation,
 *   beaconVisibleAtJunction: boolean | null,
 *   path: Cell[],
 *   reachedGoal: boolean
 * }} TrialLog
 */
/**
 * @typedef {{
 *   seed: string,
 *   participantIndex: string,
 *   phase: string,
 *   trialIndex: number,
 *   trialAttempt: number,
 *   label: string,
 *   kind: string | null,
 *   landmark: string | null,
 *   timed: boolean,
 *   guidance: string,
 *   moveIndex: number,
 *   event: 'move' | 'timeout',
 *   tMs: number | null,
 *   fromX: number,
 *   fromY: number,
 *   toX: number | null,
 *   toY: number | null,
 *   dx: number | null,
 *   dy: number | null,
 *   legal: boolean,
 *   firstChoice: FirstChoice | null,
 *   laterContinuation: Continuation | null,
 *   beaconVisibleAtJunction: boolean | null,
 *   reachedGoal: boolean
 * }} MoveRow
 */

/**
 * Return a required DOM element.
 * @param {string} id
 * @returns {HTMLElement}
 */
function byId(id) {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing element ${id}`);
  return element;
}

const data = /** @type {PlayData} */ (JSON.parse(byId('data').textContent ?? ''));
const canvas = /** @type {HTMLCanvasElement} */ (byId('board'));
const instructions = byId('instructions');
const play = byId('play');
const startButton = /** @type {HTMLButtonElement} */ (byId('start'));
const nextButton = /** @type {HTMLButtonElement} */ (byId('next'));
const restartButton = /** @type {HTMLButtonElement} */ (byId('restart'));
const downloadButton = /** @type {HTMLButtonElement} */ (byId('download'));
const downloadCsvButton = /** @type {HTMLButtonElement} */ (byId('download-csv'));
/** Whether the participant has left the instruction page. */
let sessionStarted = false;
const palette = getComputedStyle(document.documentElement);

/** @type {number} */
let trialIndex = 0;
/** @type {number} */
let trialAttempt = 0;
/** @type {number} */
let moveIndex = 0;
/** @type {Cell} */
let position = [...data.start];
/** @type {Cell[]} */
let path = [data.start];
/** @type {Set<string>} */
let visible = new Set(data.initialVisible.map(String));
/** @type {Set<string>} */
let openEdges = new Set();
/** @type {FirstChoice | null} */
let firstChoice = null;
/** @type {number | null} */
let cueShownAt = null;
/** @type {number | null} */
let firstChoiceRtMs = null;
/** @type {Continuation} */
let laterContinuation = 'none';
/** @type {boolean | null} */
let beaconVisibleAtJunction = null;
/** @type {boolean} */
let sawJunction = false;
/** @type {boolean} */
let trialDone = false;
/** @type {number | null} */
let deadlineTimer = null;
/** @type {TrialLog[]} */
const logs = [];
/** @type {MoveRow[]} */
const moveRows = [];

/**
 * Resolve a CSS color variable for canvas drawing.
 * @param {string} name
 * @returns {string}
 */
function color(name) {
  return palette.getPropertyValue(name).trim();
}

/**
 * Canonical undirected edge key.
 * @param {Cell} first
 * @param {Cell} second
 * @returns {string}
 */
function edgeKey(first, second) {
  return [String(first), String(second)].sort().join('|');
}

/**
 * Cell center in grid units.
 * @param {Cell} cell
 * @returns {Cell}
 */
function center([x, y]) {
  return [x + 0.5, y + 0.5];
}

/**
 * @returns {PlayTrial}
 */
function currentTrial() {
  return data.trials[trialIndex];
}

/**
 * Classify the first leave-start move.
 * @param {Cell} destination
 * @param {PlayTrial} trial
 * @returns {FirstChoice}
 */
function classifyFirstChoice(destination, trial) {
  if (destination[0] === data.centerEntry[0] && destination[1] === data.centerEntry[1]) {
    return 'shortcut';
  }
  const side = destination[0] < data.start[0] ? 'left' : 'right';
  if (destination[1] === data.start[1] && side === trial.learned_side) return 'learned';
  return 'other';
}

/**
 * Score the first departure from the later junction.
 * @param {Cell} nextCell
 * @param {PlayTrial} trial
 * @returns {Continuation}
 */
function classifyLaterContinuation(nextCell, trial) {
  const route = trial.learned_route;
  const index = route.findIndex(
    (cell) => cell[0] === trial.later_junction[0] && cell[1] === trial.later_junction[1],
  );
  if (index < 0 || index + 1 >= route.length) return 'none';
  const learnedNext = route[index + 1];
  return nextCell[0] === learnedNext[0] && nextCell[1] === learnedNext[1]
    ? 'learned'
    : 'alternate';
}

/**
 * Index openings for the current trial.
 * @param {PlayTrial} trial
 * @returns {void}
 */
function loadOpenEdges(trial) {
  openEdges = new Set(trial.edges.map(([a, b]) => edgeKey(a, b)));
}

/**
 * Whether a move uses an open edge.
 * @param {Cell} first
 * @param {Cell} second
 * @returns {boolean}
 */
function canMove(first, second) {
  return openEdges.has(edgeKey(first, second));
}

/**
 * Stroke a polyline in grid units.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Cell[]} points
 * @param {string} ink
 * @param {number} width
 * @returns {void}
 */
function stroke(ctx, points, ink, width) {
  ctx.beginPath();
  ctx.moveTo(...points[0]);
  for (const point of points.slice(1)) ctx.lineTo(...point);
  ctx.lineWidth = width;
  ctx.strokeStyle = ink;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.stroke();
}

/**
 * @param {CanvasRenderingContext2D} ctx
 * @param {Cell} point
 * @param {number} radius
 * @param {string} fill
 * @param {string} ink
 * @param {number} [width]
 * @returns {void}
 */
function disk(ctx, point, radius, fill, ink, width = 0.05) {
  ctx.beginPath();
  ctx.arc(...point, radius, 0, Math.PI * 2);
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.strokeStyle = ink;
  ctx.lineWidth = width;
  ctx.stroke();
}

/**
 * Draw one grid boundary under fog rules.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Cell} first
 * @param {Cell} second
 * @param {Edge} segment
 * @param {Set<string>} corridors
 * @returns {void}
 */
function drawBoundary(ctx, first, second, segment, corridors) {
  const firstKnown = visible.has(String(first));
  const secondKnown = visible.has(String(second));
  if (!firstKnown && !secondKnown) return;
  if (openEdges.has(edgeKey(first, second))) {
    if (firstKnown && secondKnown) stroke(ctx, segment, '#dce6eb', 0.018);
    return;
  }
  const bordersCorridor =
    corridors.has(String(first)) || corridors.has(String(second));
  stroke(ctx, segment, bordersCorridor ? '#304456' : '#9db1bf', bordersCorridor ? 0.085 : 0.025);
}

/**
 * Draw floors and walls for the currently revealed fog set.
 * @param {CanvasRenderingContext2D} ctx
 * @returns {void}
 */
function drawBoard(ctx) {
  /** @type {Set<string>} */
  const corridors = new Set();
  for (const [first, second] of currentTrial().edges) {
    // Match the preview rule: an opening appears once either endpoint is known.
    if (!visible.has(String(first)) && !visible.has(String(second))) continue;
    corridors.add(String(first));
    corridors.add(String(second));
  }
  for (let y = 0; y < data.height; y++) {
    for (let x = 0; x < data.width; x++) {
      const cell = /** @type {Cell} */ ([x, y]);
      if (!visible.has(String(cell))) continue;
      ctx.fillStyle = corridors.has(String(cell)) ? '#fff' : '#dce6eb';
      ctx.fillRect(x, y, 1, 1);
    }
  }
  for (let y = 0; y <= data.height; y++) {
    for (let x = 0; x <= data.width; x++) {
      if (x < data.width) {
        drawBoundary(ctx, [x, y - 1], [x, y], [[x, y], [x + 1, y]], corridors);
      }
      if (y < data.height) {
        drawBoundary(ctx, [x - 1, y], [x, y], [[x, y], [x, y + 1]], corridors);
      }
    }
  }
}

/**
 * Draw a filled polygon path in grid coordinates.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Cell[]} points
 * @param {string} fill
 * @param {string} ink
 * @param {number} [width]
 * @returns {void}
 */
function polygon(ctx, points, fill, ink, width = 0.06) {
  ctx.beginPath();
  ctx.moveTo(...points[0]);
  for (const point of points.slice(1)) ctx.lineTo(...point);
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.strokeStyle = ink;
  ctx.lineWidth = width;
  ctx.lineJoin = 'round';
  ctx.stroke();
}

/**
 * Draw the orientation landmark above start (matches media/landmark-*.svg).
 * Circle = teal bullseye (left); diamond = coral diamond (right).
 * @param {CanvasRenderingContext2D} ctx
 * @param {PlayTrial['symbol']} symbol
 * @returns {void}
 */
function drawSymbol(ctx, symbol) {
  const [x, y] = center([data.start[0], data.start[1] - 1]);
  if (symbol === 'circle') {
    disk(ctx, [x, y], 0.28, '#0f766e', '#143243', 0.07);
    ctx.beginPath();
    ctx.arc(x, y, 0.15, 0, Math.PI * 2);
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 0.07;
    ctx.stroke();
    disk(ctx, [x, y], 0.055, '#ffffff', '#ffffff', 0.02);
    return;
  }
  polygon(
    ctx,
    [
      [x, y - 0.3],
      [x + 0.3, y],
      [x, y + 0.3],
      [x - 0.3, y],
    ],
    '#c2410c',
    '#143243',
    0.07,
  );
  polygon(
    ctx,
    [
      [x, y - 0.14],
      [x + 0.14, y],
      [x, y + 0.14],
      [x - 0.14, y],
    ],
    '#fdba74',
    '#fdba74',
    0.02,
  );
}

/**
 * Draw the beacon star on a wall boundary without opening it.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Edge} beacon
 * @returns {void}
 */
function drawBeacon(ctx, beacon) {
  const [a, b] = beacon.map(center);
  const x = (a[0] + b[0]) / 2;
  const y = (a[1] + b[1]) / 2;
  const tips = 5;
  const outer = 0.28;
  const inner = 0.12;
  /** @type {Cell[]} */
  const points = [];
  for (let i = 0; i < tips * 2; i += 1) {
    const radius = i % 2 === 0 ? outer : inner;
    const angle = -Math.PI / 2 + (i * Math.PI) / tips;
    points.push([x + Math.cos(angle) * radius, y + Math.sin(angle) * radius]);
  }
  polygon(ctx, points, color('--beacon'), '#7c2d12', 0.055);
  disk(ctx, [x, y], 0.06, '#fff7ed', '#7c2d12', 0.03);
}

/**
 * Draw endpoint labels when their cells are visible.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Cell} cell
 * @param {'S' | 'G'} label
 * @returns {void}
 */
function drawEndpoint(ctx, cell, label) {
  if (!visible.has(String(cell))) return;
  const point = center(cell);
  const isStart = label === 'S';
  disk(ctx, point, 0.29, isStart ? '#24455d' : '#fff', '#24455d');
  ctx.fillStyle = isStart ? '#fff' : '#24455d';
  ctx.font = '700 0.36px system-ui';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(label, ...point);
}

/**
 * Draw training guidance for the learned route without unlocking walls.
 * @param {CanvasRenderingContext2D} ctx
 * @param {PlayTrial} trial
 * @returns {void}
 */
function drawGuidance(ctx, trial) {
  if (trial.guidance === 'none') return;
  const route =
    trial.guidance === 'fade' ? trial.learned_route.slice(0, 3) : trial.learned_route;
  if (route.length < 2) return;
  const visibleRoute = route.filter((cell) => visible.has(String(cell)));
  if (visibleRoute.length < 2) return;
  stroke(ctx, visibleRoute.map(center), '#007e70', trial.guidance === 'fade' ? 0.08 : 0.14);
}

/**
 * Draw the participant marker on the current cell.
 * @param {CanvasRenderingContext2D} ctx
 * @returns {void}
 */
function drawPlayer(ctx) {
  disk(ctx, center(position), 0.22, color('--player'), '#6b2e10', 0.06);
}

/**
 * Redraw the playable board.
 * @returns {void}
 */
function redraw() {
  const trial = currentTrial();
  const bounds = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.round(bounds.width * scale);
  canvas.height = Math.round(bounds.height * scale);
  const ctx = canvas.getContext('2d');
  const size = Math.min(
    (canvas.width - 18 * scale) / data.width,
    (canvas.height - 18 * scale) / data.height,
  );
  if (!ctx || size <= 0) return;

  ctx.fillStyle = color('--fog');
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.translate((canvas.width - data.width * size) / 2, (canvas.height - data.height * size) / 2);
  ctx.scale(size, size);

  drawBoard(ctx);
  drawGuidance(ctx, trial);
  drawEndpoint(ctx, data.start, 'S');
  drawEndpoint(ctx, data.goal, 'G');
  // Cues stay on screen only while their cells remain in the revealed fog set.
  if (visible.has(String(data.start))) drawSymbol(ctx, trial.symbol);
  if (
    trial.beacon &&
    (visible.has(String(trial.beacon[0])) || visible.has(String(trial.beacon[1])))
  ) {
    drawBeacon(ctx, trial.beacon);
  }
  drawPlayer(ctx);
}

/**
 * Refresh status text and the running trial log preview.
 * @returns {void}
 */
function updateHud() {
  const trial = currentTrial();
  const cueParts = [
    trial.kind ? `Cue ${trial.kind}` : null,
    trial.landmark ? `${trial.landmark} beacon` : null,
    trial.timed ? `timed${trial.deadline_ms ? ` ${trial.deadline_ms}ms` : ''}` : 'untimed',
    trial.guidance !== 'none' ? `guidance ${trial.guidance}` : null,
    trial.symbol,
  ].filter(Boolean);
  byId('trial-meta').textContent =
    `Trial ${trialIndex + 1} of ${data.trials.length} · ${trial.label} · ${cueParts.join(' · ')}`;
  if (trialDone) {
    byId('status').textContent =
      firstChoice === 'timeout'
        ? 'First-move deadline missed. Press Next trial or Restart.'
        : position[0] === data.goal[0] && position[1] === data.goal[1]
          ? `Goal reached. First choice: ${firstChoice ?? 'none'}; later continuation: ${laterContinuation}.`
          : 'Trial ended.';
  } else if (trial.guidance === 'full') {
    byId('status').textContent = 'Follow the guided learned route. Symbol maps to the first turn.';
  } else if (trial.guidance === 'fade') {
    byId('status').textContent = 'Guidance is fading. Continue the learned route from the symbol.';
  } else {
    byId('status').textContent = 'Find the goal. Only open corridors are walkable.';
  }
  nextButton.disabled = !(trialDone && trialIndex + 1 < data.trials.length);
}

/**
 * Append one attempted-move row for CSV / JSON export.
 * @param {Partial<MoveRow> & {event: MoveRow['event'], legal: boolean}} fields
 * @returns {void}
 */
function recordMove(fields) {
  const trial = currentTrial();
  moveIndex += 1;
  moveRows.push({
    seed: data.seed,
    participantIndex: data.participantIndex,
    phase: data.phase,
    trialIndex,
    trialAttempt,
    label: trial.label,
    kind: trial.kind,
    landmark: trial.landmark,
    timed: trial.timed,
    guidance: trial.guidance,
    moveIndex,
    event: fields.event,
    tMs: fields.tMs ?? null,
    fromX: fields.fromX ?? position[0],
    fromY: fields.fromY ?? position[1],
    toX: fields.toX ?? null,
    toY: fields.toY ?? null,
    dx: fields.dx ?? null,
    dy: fields.dy ?? null,
    legal: fields.legal,
    firstChoice: fields.firstChoice ?? null,
    laterContinuation: fields.laterContinuation ?? null,
    beaconVisibleAtJunction: fields.beaconVisibleAtJunction ?? null,
    reachedGoal: fields.reachedGoal ?? false,
  });
}

/**
 * Commit the current trial into the session log.
 * @returns {void}
 */
function commitTrialLog() {
  const trial = currentTrial();
  logs.push({
    trialIndex,
    label: trial.label,
    kind: trial.kind,
    landmark: trial.landmark,
    timed: trial.timed,
    firstChoice,
    firstChoiceRtMs,
    laterContinuation,
    beaconVisibleAtJunction,
    path: path.map((cell) => /** @type {Cell} */ ([...cell])),
    reachedGoal: position[0] === data.goal[0] && position[1] === data.goal[1],
  });
  if (logs.length >= data.trials.length) renderSessionReport();
}

/**
 * Count first-choice outcomes for one grouping key.
 * @param {TrialLog[]} rows
 * @param {string} groupKey
 * @returns {Record<string, {n: number, choices: Record<string, number>, meanRtMs: number | null}>}
 */
/**
 * Bucket trial logs by a string field, defaulting missing values to unknown.
 * @param {TrialLog[]} rows
 * @param {string} groupKey
 * @returns {Record<string, TrialLog[]>}
 */
function groupLogs(rows, groupKey) {
  /** @type {Record<string, TrialLog[]>} */
  const buckets = {};
  for (const row of rows) {
    const key = String(/** @type {Record<string, unknown>} */ (row)[groupKey] ?? 'unknown');
    (buckets[key] ??= []).push(row);
  }
  return buckets;
}

/**
 * Aggregate first decisions and mean RT by cue or landmark group.
 * @param {TrialLog[]} rows
 * @param {string} groupKey
 * @returns {Record<string, {n: number, choices: Record<string, number>, meanRtMs: number | null}>}
 */
function summarizeChoices(rows, groupKey) {
  /** @type {Record<string, {n: number, choices: Record<string, number>, meanRtMs: number | null}>} */
  const summary = {};
  for (const [key, group] of Object.entries(groupLogs(rows, groupKey))) {
    /** @type {Record<string, number>} */
    const choices = {};
    const times = [];
    for (const item of group) {
      const choice = item.firstChoice ?? 'none';
      choices[choice] = (choices[choice] ?? 0) + 1;
      if (typeof item.firstChoiceRtMs === 'number') times.push(item.firstChoiceRtMs);
    }
    summary[key] = {
      n: group.length,
      choices,
      meanRtMs: times.length
        ? Math.round(times.reduce((sum, value) => sum + value, 0) / times.length)
        : null,
    };
  }
  return summary;
}

/**
 * Count later-junction continuations separately from first moves.
 * @param {TrialLog[]} rows
 * @param {string} groupKey
 * @returns {Record<string, {n: number, continuations: Record<string, number>}>}
 */
function summarizeContinuations(rows, groupKey) {
  /** @type {Record<string, {n: number, continuations: Record<string, number>}>} */
  const summary = {};
  for (const [key, group] of Object.entries(groupLogs(rows, groupKey))) {
    /** @type {Record<string, number>} */
    const continuations = {};
    for (const item of group) {
      const value = item.laterContinuation ?? 'none';
      continuations[value] = (continuations[value] ?? 0) + 1;
    }
    summary[key] = { n: group.length, continuations };
  }
  return summary;
}

/**
 * Suggest a first-move deadline from completed untimed probe RTs.
 * @param {number[]} times
 * @param {number} [percentile]
 * @param {number} [floorMs]
 * @returns {number | null}
 */
function calibrateDeadline(times, percentile = 0.7, floorMs = 400) {
  if (!times.length) return null;
  const ordered = [...times].sort((a, b) => a - b);
  const index = Math.min(
    ordered.length - 1,
    Math.max(0, Math.trunc(percentile * (ordered.length - 1))),
  );
  return Math.max(floorMs, ordered[index]);
}

/**
 * Show condition-level totals once every scheduled trial is logged.
 * @returns {void}
 */
function renderSessionReport() {
  const probes = logs.filter((row) =>
    row.kind === 'symbol-only' || row.kind === 'aligned' || row.kind === 'conflicting',
  );
  const testTrials = logs.filter((row) => row.landmark !== null);
  const timed = testTrials.filter((row) => row.timed);
  const untimed = testTrials.filter((row) => !row.timed);
  const landmarkKeys = [...new Set(testTrials.map((row) => String(row.landmark)))];
  /** @type {Record<string, number | null>} */
  const deltas = {};
  for (const landmark of landmarkKeys) {
    const timedRows = timed.filter((row) => String(row.landmark) === landmark);
    const untimedRows = untimed.filter((row) => String(row.landmark) === landmark);
    if (!timedRows.length || !untimedRows.length) {
      deltas[landmark] = null;
      continue;
    }
    const timedRate =
      timedRows.filter((row) => row.firstChoice === 'learned').length / timedRows.length;
    const untimedRate =
      untimedRows.filter((row) => row.firstChoice === 'learned').length /
      untimedRows.length;
    deltas[landmark] = Math.round((timedRate - untimedRate) * 1000) / 1000;
  }
  const probeRts = probes
    .map((row) => row.firstChoiceRtMs)
    .filter(/** @returns {value is number} */ (value) => typeof value === 'number');
  const report = {
    byCueKind: summarizeChoices(probes, 'kind'),
    byLandmark: summarizeChoices(testTrials, 'landmark'),
    learnedChoiceDeltaByLandmark: deltas,
    laterContinuations: summarizeContinuations(
      testTrials.length ? testTrials : probes,
      testTrials.length ? 'landmark' : 'kind',
    ),
    calibratedDeadlineMs: calibrateDeadline(probeRts),
  };
  const panel = byId('report');
  panel.classList.add('visible');
  panel.textContent = [
    'Session report',
    `First choices by cue: ${JSON.stringify(report.byCueKind)}`,
    `First choices by landmark: ${JSON.stringify(report.byLandmark)}`,
    `Timed − untimed learned delta: ${JSON.stringify(report.learnedChoiceDeltaByLandmark)}`,
    `Later continuations: ${JSON.stringify(report.laterContinuations)}`,
    `Calibrated deadline (ms): ${report.calibratedDeadlineMs ?? 'n/a'}`,
  ].join('\n');
}

/**
 * Clear any pending first-move deadline timer.
 * @returns {void}
 */
function clearDeadline() {
  if (deadlineTimer !== null) {
    window.clearTimeout(deadlineTimer);
    deadlineTimer = null;
  }
}

/**
 * End the trial on a missed first-move deadline.
 * @returns {void}
 */
function onTimeout() {
  if (trialDone || firstChoice !== null) return;
  firstChoice = 'timeout';
  firstChoiceRtMs =
    cueShownAt === null ? null : Math.round(performance.now() - cueShownAt);
  recordMove({
    event: 'timeout',
    legal: false,
    tMs: firstChoiceRtMs,
    fromX: position[0],
    fromY: position[1],
    firstChoice: 'timeout',
  });
  trialDone = true;
  commitTrialLog();
  updateHud();
  redraw();
}

/**
 * Reset mutable state for the selected trial index.
 * @returns {void}
 */
function beginTrial() {
  const trial = currentTrial();
  clearDeadline();
  loadOpenEdges(trial);
  trialAttempt += 1;
  moveIndex = 0;
  position = /** @type {Cell} */ ([...data.start]);
  path = [/** @type {Cell} */ ([...data.start])];
  visible = new Set(data.initialVisible.map(String));
  firstChoice = null;
  firstChoiceRtMs = null;
  laterContinuation = 'none';
  beaconVisibleAtJunction = null;
  sawJunction = false;
  trialDone = false;
  // Deadline starts when cues appear and stops on the first legal move.
  cueShownAt = performance.now();
  if (trial.timed && trial.deadline_ms) {
    deadlineTimer = window.setTimeout(onTimeout, trial.deadline_ms);
  }
  updateHud();
  redraw();
  canvas.focus();
}

/**
 * Attempt one cardinal step from the current cell.
 * @param {number} dx
 * @param {number} dy
 * @returns {void}
 */
function tryMove(dx, dy) {
  if (trialDone) return;
  const trial = currentTrial();
  const from = /** @type {Cell} */ ([...position]);
  const next = /** @type {Cell} */ ([position[0] + dx, position[1] + dy]);
  const tMs = cueShownAt === null ? null : Math.round(performance.now() - cueShownAt);
  if (!canMove(position, next)) {
    // Keep illegal attempts for wall-bump and timeout-pressure analyses.
    recordMove({
      event: 'move',
      legal: false,
      tMs,
      fromX: from[0],
      fromY: from[1],
      toX: next[0],
      toY: next[1],
      dx,
      dy,
    });
    updateHud();
    return;
  }

  const leavingStart =
    position[0] === data.start[0] && position[1] === data.start[1] && path.length === 1;
  /** @type {FirstChoice | null} */
  let moveFirstChoice = null;
  if (leavingStart) {
    clearDeadline();
    firstChoice = classifyFirstChoice(next, trial);
    firstChoiceRtMs = tMs;
    moveFirstChoice = firstChoice;
  }

  /** @type {Continuation | null} */
  let moveContinuation = null;
  /** @type {boolean | null} */
  let moveBeaconVisible = null;
  const atJunction =
    position[0] === trial.later_junction[0] && position[1] === trial.later_junction[1];
  if (atJunction && !sawJunction) {
    laterContinuation = classifyLaterContinuation(next, trial);
    beaconVisibleAtJunction = Boolean(
      trial.beacon &&
        (visible.has(String(trial.beacon[0])) || visible.has(String(trial.beacon[1]))),
    );
    sawJunction = true;
    moveContinuation = laterContinuation;
    moveBeaconVisible = beaconVisibleAtJunction;
  }

  position = next;
  path.push(/** @type {Cell} */ ([...next]));
  visible.add(String(next));
  const reachedGoal = next[0] === data.goal[0] && next[1] === data.goal[1];
  recordMove({
    event: 'move',
    legal: true,
    tMs,
    fromX: from[0],
    fromY: from[1],
    toX: next[0],
    toY: next[1],
    dx,
    dy,
    firstChoice: moveFirstChoice,
    laterContinuation: moveContinuation,
    beaconVisibleAtJunction: moveBeaconVisible,
    reachedGoal,
  });

  if (reachedGoal) {
    trialDone = true;
    commitTrialLog();
  }
  updateHud();
  redraw();
}

/**
 * Advance to the next scheduled trial when the current one is finished.
 * @returns {void}
 */
function goNext() {
  if (!sessionStarted || !trialDone || trialIndex + 1 >= data.trials.length) return;
  trialIndex += 1;
  beginTrial();
}

/**
 * Restart the current trial without advancing the schedule.
 * @returns {void}
 */
function restartTrial() {
  if (!sessionStarted) return;
  // Drop a partial log entry by not committing unfinished restarts.
  beginTrial();
}

/**
 * Leave the instruction page and start the first trial clock.
 * @returns {void}
 */
function startSession() {
  if (sessionStarted) return;
  sessionStarted = true;
  instructions.hidden = true;
  play.hidden = false;
  beginTrial();
}

/**
 * Escape one CSV field.
 * @param {string | number | boolean | null | undefined} value
 * @returns {string}
 */
function csvField(value) {
  if (value === null || value === undefined) return '';
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/**
 * Build a CSV string with one row per attempted move.
 * @returns {string}
 */
function movesCsv() {
  const headers = [
    'seed',
    'participant_index',
    'phase',
    'trial_index',
    'trial_attempt',
    'label',
    'kind',
    'landmark',
    'timed',
    'guidance',
    'move_index',
    'event',
    't_ms',
    'from_x',
    'from_y',
    'to_x',
    'to_y',
    'dx',
    'dy',
    'legal',
    'first_choice',
    'later_continuation',
    'beacon_visible_at_junction',
    'reached_goal',
  ];
  const lines = [headers.join(',')];
  for (const row of moveRows) {
    lines.push(
      [
        row.seed,
        row.participantIndex,
        row.phase,
        row.trialIndex,
        row.trialAttempt,
        row.label,
        row.kind,
        row.landmark,
        row.timed,
        row.guidance,
        row.moveIndex,
        row.event,
        row.tMs,
        row.fromX,
        row.fromY,
        row.toX,
        row.toY,
        row.dx,
        row.dy,
        row.legal,
        row.firstChoice,
        row.laterContinuation,
        row.beaconVisibleAtJunction,
        row.reachedGoal,
      ]
        .map(csvField)
        .join(','),
    );
  }
  return `${lines.join('\n')}\n`;
}

/**
 * Trigger a browser download for the given blob contents.
 * @param {Blob} blob
 * @param {string} filename
 * @returns {void}
 */
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * Download the completed decision log as JSON, including every move attempt.
 * @returns {void}
 */
function downloadLog() {
  const probes = logs.filter((row) =>
    row.kind === 'symbol-only' || row.kind === 'aligned' || row.kind === 'conflicting',
  );
  const probeRts = probes
    .map((row) => row.firstChoiceRtMs)
    .filter(/** @returns {value is number} */ (value) => typeof value === 'number');
  const payload = {
    seed: data.seed,
    participantIndex: data.participantIndex,
    phase: data.phase,
    trials: logs,
    moves: moveRows,
    analysis: {
      byCueKind: summarizeChoices(probes, 'kind'),
      byLandmark: summarizeChoices(
        logs.filter((row) => row.landmark !== null),
        'landmark',
      ),
      laterContinuations: summarizeContinuations(logs, 'kind'),
      calibratedDeadlineMs: calibrateDeadline(probeRts),
    },
  };
  downloadBlob(
    new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }),
    `maze-pilot-log-${data.seed}-${data.participantIndex}.json`,
  );
}

/**
 * Download one CSV row per attempted move (legal and blocked).
 * @returns {void}
 */
function downloadCsv() {
  downloadBlob(
    new Blob([movesCsv()], { type: 'text/csv;charset=utf-8' }),
    `maze-pilot-moves-${data.seed}-${data.participantIndex}.csv`,
  );
}

/**
 * Map keyboard input onto cardinal steps.
 * @param {KeyboardEvent} event
 * @returns {void}
 */
function onKey(event) {
  if (!sessionStarted) return;
  const key = event.key.toLowerCase();
  /** @type {Record<string, [number, number]>} */
  const steps = {
    arrowup: [0, -1],
    w: [0, -1],
    arrowdown: [0, 1],
    s: [0, 1],
    arrowleft: [-1, 0],
    a: [-1, 0],
    arrowright: [1, 0],
    d: [1, 0],
  };
  const step = steps[key];
  if (!step) return;
  event.preventDefault();
  tryMove(...step);
}

byId('session').textContent =
  `Seed ${data.seed} · Participant ${data.participantIndex} · Phase ${data.phase}`;
startButton.addEventListener('click', startSession);
nextButton.addEventListener('click', goNext);
restartButton.addEventListener('click', restartTrial);
downloadButton.addEventListener('click', downloadLog);
downloadCsvButton.addEventListener('click', downloadCsv);
window.addEventListener('keydown', onKey);
new ResizeObserver(() => {
  if (sessionStarted) redraw();
}).observe(canvas);
startButton.focus();
