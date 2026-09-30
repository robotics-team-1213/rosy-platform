// 접속 경로(D-323 §3.1): 최근 접속 + mDNS 발견으로 바로 연결한다.
// 게임처럼 "계속하기" UX — 마지막 로봇을 원터치로 재접속.

const KEY = "rosy.pilot.recent";
const MAX = 5;

export function getRecent() {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch { return []; }
}

export function addRecent(entry) {
  const list = getRecent().filter((r) => r.host !== entry.host);
  list.unshift(entry);
  localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX)));
}

export function removeRecent(host) {
  localStorage.setItem(KEY, JSON.stringify(getRecent().filter((r) => r.host !== host)));
}
