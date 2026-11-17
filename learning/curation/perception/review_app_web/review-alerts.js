// One alert surface for the Learning pages (D-1117): a server that cannot be reached, a 5xx or an expired login is ONE warn item
// ("api-unreachable") in #page-alerts, published once and resolved by the next request that reaches the server.
// Panels read commonDown() and show only a quiet "불러오지 못함"; they never repeat the error text.
import {accountFetch as rawFetch} from '/account-session.js';
import {createAlertCenter} from '/common/alert-center.js';
import {getAnnouncer} from '/common/announcer.js';

import {createFailureTracker} from '/review-failures.js';

const KEY = 'api-unreachable';
const UNKNOWN = '불러오지 못함';
let center;
function alerts() {
  return center ??= createAlertCenter({listEl: document.getElementById('page-alerts'), toastEl: null,
    announcer: getAnnouncer(document), isOnScreen: () => true});
}
const failures = createFailureTracker(
  (message) => alerts().publish({kind: 'warn', key: KEY, title: '서버 연결 문제', message}),  // same text again is a no-op in the tracker
  () => alerts().resolve(KEY));
export const commonDown = () => failures.down();
// Panel text for a failed read: quiet while the common cause is shown once above, the real message otherwise.
export const panelError = (error, quiet = UNKNOWN) => commonDown() ? quiet : (error?.message || String(error));
// Write only when the text changed (polling).
export function setText(node, value) { if (node.textContent !== value) node.textContent = value; }

export async function accountFetch(path, options) {
  const key = `${String(options?.method || 'GET').toUpperCase()} ${String(path).split('?')[0]}`;  // a write's failure outlives the reads of the same path
  let response;
  try { response = await rawFetch(path, options); }
  catch (error) { if (error?.name !== 'AbortError') failures.fail(key, error?.message || String(error)); throw error; }
  if (response.status >= 500 || response.status === 401) {
    let detail = '';
    try { detail = (await response.clone().json())?.error || ''; } catch (_) { /* HTML or empty body */ }
    failures.fail(key, detail || (response.status === 401 ? '로그인이 필요합니다. 로그인·계정에서 접속한 뒤 다시 확인하세요.' : `서버가 요청을 끝내지 못했습니다(HTTP ${response.status}).`));
  } else failures.recover(key);
  return response;
}
