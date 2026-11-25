import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { neon } from '@neondatabase/serverless';

function loadEnvFile(path) {
  if (!existsSync(path)) return;
  for (const line of readFileSync(path, 'utf8').split(/\r?\n/)) {
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = value;
  }
}

loadEnvFile(resolve('.env.local'));

const sql = neon(process.env.DATABASE_URL);
const args = process.argv.slice(2);
const includeAll = args.includes('--all');
const targets = args.filter((arg) => arg !== '--all');
const rows =
  targets.length > 0
    ? await sql`
        SELECT participant_index, seed, phase, completed, trial_count, updated_at, payload
        FROM pilot_sessions
        WHERE participant_index = ANY(${targets})
        ORDER BY updated_at DESC
      `
    : includeAll
      ? await sql`
          SELECT participant_index, seed, phase, completed, trial_count, updated_at, payload
          FROM pilot_sessions
          ORDER BY updated_at DESC
        `
      : await sql`
          SELECT participant_index, seed, phase, completed, trial_count, updated_at, payload
          FROM pilot_sessions
          WHERE completed = TRUE
          ORDER BY updated_at DESC
        `;

mkdirSync('Data', { recursive: true });

for (const row of rows) {
  const payload =
    row.payload && typeof row.payload === 'object' ? row.payload : {};
  const out = {
    participant_index: row.participant_index,
    seed: row.seed,
    phase: row.phase,
    completed: row.completed,
    trial_count: row.trial_count,
    updated_at: row.updated_at,
    ...payload,
  };
  const path = `Data/maze-pilot-log-${row.seed}-${row.participant_index}.json`;
  writeFileSync(path, JSON.stringify(out, null, 2));
  const trials = Array.isArray(out.trials) ? out.trials : [];
  console.log(`=== TSN ${row.participant_index} ===`);
  console.log(
    `updated ${row.updated_at} · trials ${trials.length} · moves ${
      Array.isArray(out.moves) ? out.moves.length : 0
    }`,
  );
  if (out.analysis) {
    console.log('analysis', JSON.stringify(out.analysis, null, 2));
  }
  console.log(
    'firstChoices',
    JSON.stringify(
      trials.map((t) => ({
        label: t.label,
        kind: t.kind,
        firstChoice: t.firstChoice,
        rt: t.firstChoiceRtMs,
        later: t.laterContinuation,
        goal: t.reachedGoal,
      })),
      null,
      2,
    ),
  );
  console.log('wrote', path);
}
