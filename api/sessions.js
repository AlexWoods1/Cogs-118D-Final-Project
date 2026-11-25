import { createHash, timingSafeEqual } from 'node:crypto';
import { neon } from '@neondatabase/serverless';

/** Max JSON body size for POST (bytes). */
const MAX_BODY_BYTES = 256 * 1024;
/** Max trials / moves arrays stored in a session payload. */
const MAX_ARRAY_LENGTH = 500;
/** Max length for seed / clientSessionId strings. */
const MAX_STRING_LENGTH = 128;
/** Participant TSN: non-negative integer string, bounded length. */
const PARTICIPANT_INDEX_RE = /^\d{1,6}$/;
/** Allowed study phases. */
const ALLOWED_PHASES = new Set(['pilot', 'test']);

/** @type {Promise<void> | null} */
let schemaReady = null;

/**
 * @returns {ReturnType<typeof neon>}
 */
function getSql() {
  const url = process.env.DATABASE_URL;
  if (!url) {
    throw new Error('DATABASE_URL is not configured');
  }
  return neon(url);
}

/**
 * Create table/indexes only. One-time data migrations belong in scripts/.
 * @param {ReturnType<typeof neon>} sql
 * @returns {Promise<void>}
 */
async function ensureSchema(sql) {
  if (!schemaReady) {
    schemaReady = (async () => {
      await sql`
        CREATE TABLE IF NOT EXISTS pilot_sessions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          client_session_id TEXT UNIQUE NOT NULL,
          seed TEXT NOT NULL,
          participant_index TEXT UNIQUE NOT NULL,
          phase TEXT NOT NULL,
          completed BOOLEAN NOT NULL DEFAULT FALSE,
          trial_count INTEGER NOT NULL DEFAULT 0,
          payload JSONB NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
      `;
      await sql`
        CREATE UNIQUE INDEX IF NOT EXISTS pilot_sessions_participant_unique
          ON pilot_sessions (participant_index)
      `;
      await sql`
        CREATE INDEX IF NOT EXISTS pilot_sessions_updated_idx
          ON pilot_sessions (updated_at DESC)
      `;
    })().catch((error) => {
      schemaReady = null;
      throw error;
    });
  }
  await schemaReady;
}

/**
 * Origins allowed for browser CORS (same deployment + optional override).
 * @returns {string[]}
 */
function allowedOrigins() {
  const origins = new Set();
  const configured = String(process.env.SESSIONS_ALLOWED_ORIGIN ?? '').trim();
  if (configured) origins.add(configured.replace(/\/$/, ''));

  const prodHost = String(process.env.VERCEL_PROJECT_PRODUCTION_URL ?? '').trim();
  if (prodHost) origins.add(`https://${prodHost.replace(/\/$/, '')}`);

  const deploymentHost = String(process.env.VERCEL_URL ?? '').trim();
  if (deploymentHost) origins.add(`https://${deploymentHost.replace(/\/$/, '')}`);

  // Local static preview / vercel dev
  origins.add('http://localhost:3000');
  origins.add('http://127.0.0.1:3000');
  return [...origins];
}

/**
 * @param {import('http').IncomingMessage} req
 * @param {import('http').ServerResponse} res
 */
function applyCors(req, res) {
  const origin = String(req.headers.origin ?? '').trim();
  const allowed = allowedOrigins();
  if (origin && allowed.includes(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
  }
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
}

/**
 * Constant-time Bearer token compare.
 * @param {string} authHeader
 * @param {string} expectedToken
 * @returns {boolean}
 */
function bearerMatches(authHeader, expectedToken) {
  if (!expectedToken) return false;
  const prefix = 'Bearer ';
  if (!authHeader.startsWith(prefix)) return false;
  const provided = authHeader.slice(prefix.length);
  const a = createHash('sha256').update(provided).digest();
  const b = createHash('sha256').update(expectedToken).digest();
  return timingSafeEqual(a, b);
}

/**
 * @param {import('http').IncomingMessage} req
 * @returns {Promise<{ raw: string, body: Record<string, unknown> }>}
 */
async function readJson(req) {
  if (req.body && typeof req.body === 'object') {
    const raw = JSON.stringify(req.body);
    if (Buffer.byteLength(raw, 'utf8') > MAX_BODY_BYTES) {
      /** @type {Error & { statusCode?: number }} */
      const error = new Error('Payload too large');
      error.statusCode = 413;
      throw error;
    }
    return { raw, body: /** @type {Record<string, unknown>} */ (req.body) };
  }

  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    total += buf.length;
    if (total > MAX_BODY_BYTES) {
      /** @type {Error & { statusCode?: number }} */
      const error = new Error('Payload too large');
      error.statusCode = 413;
      throw error;
    }
    chunks.push(buf);
  }
  const raw = Buffer.concat(chunks).toString('utf8');
  if (!raw) return { raw: '', body: {} };
  return { raw, body: /** @type {Record<string, unknown>} */ (JSON.parse(raw)) };
}

/**
 * Whitelist fields persisted in JSONB (never store arbitrary extra keys).
 * @param {Record<string, unknown>} body
 * @param {{
 *   clientSessionId: string,
 *   seed: string,
 *   participantIndex: string,
 *   phase: string,
 *   completed: boolean,
 *   trials: unknown[],
 *   moves: unknown[],
 * }} fields
 * @returns {Record<string, unknown>}
 */
function buildStoredPayload(body, fields) {
  const analysis =
    body.analysis && typeof body.analysis === 'object' && !Array.isArray(body.analysis)
      ? body.analysis
      : null;
  return {
    clientSessionId: fields.clientSessionId,
    seed: fields.seed,
    participantIndex: fields.participantIndex,
    phase: fields.phase,
    completed: fields.completed,
    trials: fields.trials,
    moves: fields.moves,
    analysis,
  };
}

/**
 * @param {Record<string, unknown>} body
 * @returns {{
 *   clientSessionId: string,
 *   seed: string,
 *   participantIndex: string,
 *   phase: string,
 *   completed: boolean,
 *   trials: unknown[],
 *   moves: unknown[],
 * } | { error: string }}
 */
function validatePostBody(body) {
  const clientSessionId = String(body.clientSessionId ?? '').trim();
  const seed = String(body.seed ?? '').trim();
  const participantIndex = String(body.participantIndex ?? '').trim();
  const phase = String(body.phase ?? '').trim();
  const completed = Boolean(body.completed);
  const trials = Array.isArray(body.trials) ? body.trials : null;
  const moves = Array.isArray(body.moves) ? body.moves : [];

  if (!clientSessionId || !seed || !participantIndex || !phase) {
    return {
      error: 'clientSessionId, seed, participantIndex, and phase are required',
    };
  }
  if (
    clientSessionId.length > MAX_STRING_LENGTH ||
    seed.length > MAX_STRING_LENGTH
  ) {
    return { error: 'seed or clientSessionId is too long' };
  }
  if (!PARTICIPANT_INDEX_RE.test(participantIndex)) {
    return { error: 'participantIndex must be a non-negative integer' };
  }
  if (!ALLOWED_PHASES.has(phase)) {
    return { error: 'phase must be pilot or test' };
  }
  if (!trials) {
    return { error: 'trials must be an array' };
  }
  if (trials.length > MAX_ARRAY_LENGTH || moves.length > MAX_ARRAY_LENGTH) {
    return { error: 'trials or moves exceeds maximum length' };
  }

  return {
    clientSessionId,
    seed,
    participantIndex,
    phase,
    completed,
    trials,
    moves,
  };
}

/**
 * @param {import('http').ServerResponse} res
 * @param {number} status
 * @param {unknown} body
 */
function sendJson(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.end(JSON.stringify(body));
}

/**
 * Vercel Node.js serverless entry: upsert a pilot session by Participant TSN.
 * @param {import('http').IncomingMessage & { method?: string, query?: Record<string, string | string[]> }} req
 * @param {import('http').ServerResponse} res
 */
export default async function handler(req, res) {
  applyCors(req, res);

  if (req.method === 'OPTIONS') {
    res.statusCode = 204;
    res.end();
    return;
  }

  try {
    const sql = getSql();
    await ensureSchema(sql);

    if (req.method === 'POST') {
      const { body } = await readJson(req);
      const validated = validatePostBody(body);
      if ('error' in validated) {
        sendJson(res, 400, { error: validated.error });
        return;
      }

      const payload = buildStoredPayload(body, validated);

      const rows = await sql`
        INSERT INTO pilot_sessions (
          client_session_id,
          seed,
          participant_index,
          phase,
          completed,
          trial_count,
          payload
        )
        VALUES (
          ${validated.clientSessionId},
          ${validated.seed},
          ${validated.participantIndex},
          ${validated.phase},
          ${validated.completed},
          ${validated.trials.length},
          ${payload}
        )
        ON CONFLICT (participant_index) DO UPDATE SET
          client_session_id = EXCLUDED.client_session_id,
          seed = EXCLUDED.seed,
          phase = EXCLUDED.phase,
          completed = EXCLUDED.completed,
          trial_count = EXCLUDED.trial_count,
          payload = EXCLUDED.payload,
          updated_at = NOW()
        RETURNING id, client_session_id, completed, trial_count, updated_at
      `;

      sendJson(res, 200, rows[0]);
      return;
    }

    if (req.method === 'GET') {
      const admin = process.env.SESSIONS_ADMIN_TOKEN;
      const auth = String(req.headers.authorization ?? '');
      if (!admin || !bearerMatches(auth, admin)) {
        sendJson(res, 401, { error: 'Unauthorized' });
        return;
      }

      const query = req.query ?? {};
      const participant = String(query.participant ?? '').trim();
      if (participant && !PARTICIPANT_INDEX_RE.test(participant)) {
        sendJson(res, 400, {
          error: 'participant must be a non-negative integer',
        });
        return;
      }
      const limitRaw = Number(query.limit ?? 50);
      const limit = Number.isFinite(limitRaw)
        ? Math.min(Math.max(Math.trunc(limitRaw), 1), 200)
        : 50;

      const rows = participant
        ? await sql`
            SELECT
              id,
              client_session_id,
              seed,
              participant_index,
              phase,
              completed,
              trial_count,
              created_at,
              updated_at
            FROM pilot_sessions
            WHERE participant_index = ${participant}
            ORDER BY updated_at DESC
            LIMIT ${limit}
          `
        : await sql`
            SELECT
              id,
              client_session_id,
              seed,
              participant_index,
              phase,
              completed,
              trial_count,
              created_at,
              updated_at
            FROM pilot_sessions
            ORDER BY updated_at DESC
            LIMIT ${limit}
          `;

      sendJson(res, 200, { sessions: rows });
      return;
    }

    sendJson(res, 405, { error: 'Method not allowed' });
  } catch (error) {
    const status =
      error && typeof error === 'object' && 'statusCode' in error
        ? Number(/** @type {{ statusCode?: number }} */ (error).statusCode)
        : 500;
    if (status === 413) {
      sendJson(res, 413, { error: 'Payload too large' });
      return;
    }
    console.error('sessions API error:', error);
    sendJson(res, 500, { error: 'Internal server error' });
  }
}
