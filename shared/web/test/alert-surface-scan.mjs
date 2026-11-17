// Static scan behind alert-surface.test.mjs: which alert-surface rules a source file breaks (D-1117 alerts spec).
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

export const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
export const RULES = Object.freeze({
  alert: 'role="alert" outside the allow-list',
  multi: 'more than one assertive region in one HTML document',
  status: 'role="status" together with aria-live="assertive" on one element',
  toast: 'toast or banner class outside alert-center',
});
const ALERT = /role\s*=\s*["']alert["']|setAttribute\(\s*["']role["']\s*,[^)\n]*["']alert["']|role\s*:\s*["']alert["']/g;
const ASSERTIVE = /aria-live\s*=\s*["']assertive["']|setAttribute\(\s*["']aria-live["']\s*,\s*["']assertive["']/g;
const STATUS = /role\s*=\s*["']status["']|["']role["']\s*,\s*["']status["']/;
// a class-like name with a toast or banner segment; bare "banner" is the ARIA landmark role, bare "toast" is not
const TOAST = /(?<![\w-])(?:[a-z0-9]+-)+(?:toast|banner)(?:-[a-z0-9]+)*(?![\w-])|(?<![\w-])(?:toast|banner-[a-z0-9]+)(?:-[a-z0-9]+)*(?![\w-])/;
const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/<!--[\s\S]*?-->/g, '').replace(/^\s*\/\/.*$/gm, '');

// -> Set of rule ids (keys of RULES) that `text` of file `name` breaks
export function violations(name, text) {
  const t = strip(text);
  const found = new Set();
  const alerts = (t.match(ALERT) || []).length;
  if (alerts) found.add('alert');
  if (name.endsWith('.html') && alerts + (t.match(ASSERTIVE) || []).length > 1) found.add('multi');
  const pieces = name.endsWith('.html') ? t.match(/<[^>]*>/g) || [] : t.split('\n');
  if (pieces.some((p) => STATUS.test(p) && /assertive/.test(p))) found.add('status');
  if (TOAST.test(t)) found.add('toast');
  return found;
}

export function sourceFiles() {
  const out = execFileSync('git', ['ls-files', '-z', '--', '*.html', '*.js', '*.css', '*.inc'], {cwd: REPO, encoding: 'utf8', maxBuffer: 1 << 26});
  return out.split('\0').filter(Boolean)
    .filter((f) => !/(^|\/)(test|tests|vendor|node_modules|docs|archive)\//.test(f) && !/\.(test|min)\./.test(f));
}

export function scanRepo() {
  const result = {};
  for (const file of sourceFiles()) {
    const found = violations(file, readFileSync(path.join(REPO, file), 'utf8'));
    if (found.size) result[file] = found;
  }
  return result;
}
