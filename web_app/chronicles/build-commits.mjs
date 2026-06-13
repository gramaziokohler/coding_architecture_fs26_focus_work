#!/usr/bin/env node
/**
 * build-commits.mjs
 * Generates commits.json from the repository's git history for the
 * Coding Chronicles skyline visualization.
 *
 * Output shape (array, oldest → newest):
 *   { hash, author, time (ms epoch), subject, files, add, del }
 *
 * Usage:
 *   node scripts/build-commits.mjs [--since "30 days ago"] [--out commits.json]
 *
 * Requires a full-history checkout (fetch-depth: 0 in the Action).
 */

import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';

// --- args ---
const args = process.argv.slice(2);
function arg(name, fallback) {
  const i = args.indexOf(name);
  return i !== -1 && args[i + 1] ? args[i + 1] : fallback;
}
const SINCE = arg('--since', '');          // empty = full history
const OUT = arg('--out', 'commits.json');

// --- run git log with shortstat, machine-parseable record separators ---
// Each commit header is a single line:  HASH|AUTHOR|UNIX_TS|SUBJECT
// followed (optionally) by a shortstat line: " N files changed, A insertions(+), D deletions(-)"
const fmt = '%H|%an|%at|%s';
const gitArgs = [
  'log',
  `--pretty=format:${fmt}`,
  '--shortstat',
  '--reverse',
  '--no-merges',
];
if (SINCE) gitArgs.push(`--since=${SINCE}`);

let raw;
try {
  raw = execFileSync('git', gitArgs, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
} catch (e) {
  console.error('git log failed:', e.message);
  process.exit(1);
}

// --- parse ---
const commits = [];
let pending = null;
for (const rawLine of raw.split('\n')) {
  const line = rawLine.trim();
  if (!line) continue;
  if (line.includes('|') && line.split('|').length >= 4) {
    if (pending) commits.push(pending);
    const [hash, author, ts, ...rest] = line.split('|');
    pending = {
      hash: hash.slice(0, 7),
      author: author.trim(),
      time: parseInt(ts, 10) * 1000,
      subject: rest.join('|').trim(),
      files: 0, add: 0, del: 0,
    };
  } else if (pending && /changed/.test(line)) {
    const f = line.match(/(\d+) files? changed/);
    const a = line.match(/(\d+) insertions?\(\+\)/);
    const d = line.match(/(\d+) deletions?\(-\)/);
    if (f) pending.files = +f[1];
    if (a) pending.add = +a[1];
    if (d) pending.del = +d[1];
  }
}
if (pending) commits.push(pending);

commits.sort((x, y) => x.time - y.time);

writeFileSync(OUT, JSON.stringify(commits));
console.log(`Wrote ${commits.length} commits to ${OUT}` + (SINCE ? ` (since ${SINCE})` : ' (full history)'));
