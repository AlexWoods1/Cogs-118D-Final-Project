import { existsSync, readFileSync } from 'node:fs';
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

const url = process.env.DATABASE_URL;
if (!url) {
  console.error('DATABASE_URL missing. Run: vercel env pull .env.local --yes');
  process.exit(1);
}

const sql = neon(url);
const schemaPath = resolve('sql/schema.sql');
const statements = readFileSync(schemaPath, 'utf8')
  .split(';')
  .map((chunk) => chunk.trim())
  .filter(Boolean);

for (const statement of statements) {
  await sql.query(statement);
  console.log('ok:', statement.split('\n')[0].slice(0, 72));
}

console.log('Schema applied.');
