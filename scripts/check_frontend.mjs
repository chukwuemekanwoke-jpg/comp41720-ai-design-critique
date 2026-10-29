// Check shipped assets and JavaScript without requiring a frontend toolchain.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../frontend/dist');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
if (new Set(ids).size !== ids.length) throw new Error('Duplicate HTML element IDs');

function checkReference(value, from) {
  if (/^(?:https?:|data:|#)/i.test(value)) return;
  const resolved = path.resolve(path.dirname(from), value.split(/[?#]/)[0]);
  if (!resolved.startsWith(root + path.sep) || !fs.statSync(resolved).isFile()) {
    throw new Error(`Invalid or missing local asset: ${value}`);
  }
}

for (const match of html.matchAll(/\b(?:src|href)="([^"]+)"/g)) {
  checkReference(match[1], path.join(root, 'index.html'));
}
for (const entry of fs.readdirSync(root)) {
  const file = path.join(root, entry);
  if (entry.endsWith('.js')) {
    const result = spawnSync(process.execPath, ['--check', file], {stdio: 'inherit'});
    if (result.error || result.status !== 0) throw new Error(`Invalid JavaScript: ${entry}`);
  }
  if (entry.endsWith('.css')) {
    for (const match of fs.readFileSync(file, 'utf8').matchAll(/@import\s+(?:url\()?['"]([^'"]+)['"]/g)) {
      checkReference(match[1], file);
    }
  }
}
console.log('Frontend JavaScript, local asset references and element IDs passed.');
