// A5b: each Learning page has one #page-alerts surface and every page script reaches the API through review-alerts.js.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const web = new URL('../../../learning/curation/perception/review_app_web/', import.meta.url);
const read = (name) => readFileSync(new URL(name, web), 'utf8');

test('omx, tasks and learning pages carry one alert list and its stylesheet', () => {
  for (const page of ['omx.html', 'tasks.html', 'learning.html']) {
    const html = read(page);
    assert.equal(html.split('id="page-alerts"').length - 1, 1, page);
    assert.match(html, /\/common\/alert-center\.css/, page);
    assert.doesNotMatch(html, /role="alert"|aria-live="assertive"/, page);
  }
});

test('page scripts use the tracked fetch, never account-session directly', () => {
  for (const script of ['omx.js', 'omx-review.js', 'omx-profiles.js', 'omx-native-train.js', 'tasks.js', 'learning.js']) {
    const source = read(script);
    assert.match(source, /from '\/review-alerts\.js'/, script);
    assert.doesNotMatch(source, /import \{accountFetch\} from '\/account-session\.js'/, script);
  }
});

test('the common failure is one keyed warn item', () => {
  const source = read('review-alerts.js');
  assert.match(source, /key: KEY/);
  assert.match(source, /const KEY = 'api-unreachable'/);
  assert.match(source, /kind: 'warn'/);
});

// A5c: every review page carries the one alert list and no page script reaches the API around the tracked fetch.
test('all review pages carry one alert list; scripts use the tracked fetch', () => {
  const pages = ['accounts', 'camera', 'catalog', 'classes', 'evaluate', 'imitate', 'incidents', 'index', 'ladder', 'pixels', 'record', 'sim', 'vlm', 'workflow', 'workspaces'];
  for (const page of pages) {
    const html = read(`${page}.html`);
    assert.equal(html.split('id="page-alerts"').length - 1, 1, page);
    assert.match(html, /\/common\/alert-center\.css/, page);
    assert.doesNotMatch(html, /role="alert"|aria-live="assertive"/, page);
  }
  for (const script of ['accounts', 'app', 'camera', 'catalog', 'classes', 'evaluate', 'imitate', 'incidents', 'ladder', 'pixels', 'record', 'sim', 'versions', 'vlm', 'workflow', 'workspaces', 'omx-hub']) {
    const source = read(`${script}.js`);
    assert.match(source, /from '\/review-alerts\.js'/, script);
    assert.doesNotMatch(source, /from '\/account-session\.js'/, script);
  }
});
