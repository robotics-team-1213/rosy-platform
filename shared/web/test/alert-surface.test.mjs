// C25 static gate: the alert surface rules that keep apps from re-inventing banners, toasts and live regions (D-1117 alerts spec).
//   1. role="alert" only in ALLOWED_ALERT (announcer assertive region, safety header)
//   2. at most one assertive region (role="alert" or aria-live="assertive") per HTML document
//   3. no role="status" together with aria-live="assertive" on one element
//   4. no toast or banner class outside alert-center
// Files that break a rule today are listed in TO_MIGRATE with the slice that removes the breakage (A1 Monitoring/Calibration,
// A2 Robot dashboard, A3 Pilot, A4 Fleet; "unassigned" has no slice yet). The list only shrinks: a listed file that no longer
// breaks its rules fails the test until its entry is deleted, and a file or rule that is not listed fails the test.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {REPO, RULES, scanRepo, violations} from './alert-surface-scan.mjs';

const ALLOWED_ALERT = new Set(['shared/web/announcer.js', 'shared/web/stop-control.js']);  // stop-control.js: the C9 safety header, reserved
const ALERT_CENTER_FILES = new Set(['shared/web/alert-center.js', 'shared/web/alert-center.css']);
const TO_MIGRATE = {};  // every slice (A1-A6) has migrated; a new breakage must be fixed, not listed

const allowed = (file, rule) => (rule === 'alert' && ALLOWED_ALERT.has(file)) || (rule === 'toast' && ALERT_CENTER_FILES.has(file));

test('every surface-rule breakage is on the to-migrate list, and nothing new appears', () => {
  const unlisted = [];
  for (const [file, found] of Object.entries(scanRepo())) {
    for (const rule of found) if (!allowed(file, rule) && !TO_MIGRATE[file]?.rules.includes(rule)) unlisted.push(`${file}: ${RULES[rule]}`);
  }
  assert.deepEqual(unlisted, [], 'use shared/web/alert-center.js and announcer.js instead of a new alert surface');
});

test('the to-migrate list only shrinks: a fixed file or rule must be deleted from it', () => {
  const now = scanRepo();
  const stale = [];
  for (const [file, entry] of Object.entries(TO_MIGRATE)) {
    assert.match(entry.slice, /^(A[1-4]|unassigned)$/, file);
    for (const rule of entry.rules) if (!now[file]?.has(rule)) stale.push(`${file}: ${rule}`);
  }
  assert.deepEqual(stale, [], 'these no longer break the rule: delete them from TO_MIGRATE');
});

test('the allow-list holds only files that exist, and announcer.js makes exactly one assertive region', () => {
  for (const file of [...ALLOWED_ALERT, ...ALERT_CENTER_FILES]) assert.ok(readFileSync(path.join(REPO, file), 'utf8'), file);
  const announcer = readFileSync(path.join(REPO, 'shared/web/announcer.js'), 'utf8');
  assert.equal((announcer.match(/region\(\s*"alert"/g) || []).length, 1);
  assert.equal((announcer.match(/region\(\s*"status"/g) || []).length, 1);
});

test('the scanner catches each rule and ignores comments and the banner landmark', () => {
  assert.deepEqual([...violations('a.html', '<p role="alert"></p>')], ['alert']);
  assert.deepEqual([...violations('a.js', 'el.setAttribute("role", ok ? "status" : "alert");')], ['alert']);  // a conditional alert is still an alert
  assert.deepEqual([...violations('a.js', 'el.setAttribute("role", "alert");')], ['alert']);
  assert.deepEqual([...violations('a.js', 'const row = {role: "alert"};')], ['alert']);
  assert.ok(violations('a.html', '<p role="alert"></p><p aria-live="assertive"></p>').has('multi'));
  assert.ok(!violations('a.js', 'a.setAttribute("aria-live", "assertive"); b.setAttribute("aria-live", "assertive");').has('multi'), 'multi counts HTML documents only');
  assert.ok(violations('a.html', '<div role="status" aria-live="assertive">').has('status'));
  assert.ok(!violations('a.html', '<div role="status"></div><div aria-live="assertive"></div>').has('status'));
  assert.ok(violations('a.css', '.conn-banner { color: red }').has('toast'));
  assert.ok(violations('a.js', 'el.className = "toast-card";').has('toast'));
  assert.ok(violations('a.css', '.toast { }').has('toast'));
  assert.deepEqual([...violations('a.html', '<header role="banner"></header>')], []);
  assert.deepEqual([...violations('a.js', '// role="alert" in a comment\n/* .x-toast */')], []);
});
