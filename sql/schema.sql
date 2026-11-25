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
);

-- One-time cleanup for DBs created before participant_index was UNIQUE.
DELETE FROM pilot_sessions a
USING pilot_sessions b
WHERE a.participant_index = b.participant_index
  AND (
    a.updated_at < b.updated_at
    OR (a.updated_at = b.updated_at AND a.id::text < b.id::text)
  );

CREATE UNIQUE INDEX IF NOT EXISTS pilot_sessions_participant_unique
  ON pilot_sessions (participant_index);

CREATE INDEX IF NOT EXISTS pilot_sessions_updated_idx
  ON pilot_sessions (updated_at DESC);
