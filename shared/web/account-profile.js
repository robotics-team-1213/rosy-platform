// Display-only account context. Authorization remains with the receiving service.
const ROLE = {operator: "운영자", viewer: "보기 전용", "policy-admin": "관리자"};
export const roleLabel = role => ROLE[role] || "권한 없음";

export function profileView(session) {
  if (session?.authenticated !== true || !session.account_id) return null;
  let url;
  try { url = new URL(session.profile_url); } catch { return null; }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash
      || url.pathname !== '/console/profile') return null;
  const profile = session.profile;
  const validName = typeof profile?.display_name === 'string' && profile.display_name.trim()
    && [...profile.display_name].length <= 80 && !/[\p{Cc}\p{Cs}]/u.test(profile.display_name);
  const name = profile?.account_id === session.account_id && validName ? profile.display_name : null;
  return {href: url.href, label: name ? `${name} · 내 계정` : '내 계정 · 이름 확인 불가'};
}

// D-955 step 4: what Account says this person can open. Navigation only; each app still authorizes.
export function appLinks(session, here = globalThis.location?.href || '') {
  if (session?.authenticated !== true || !Array.isArray(session.apps)) return [];
  const links = [];
  for (const app of session.apps) {
    let url;
    try { url = new URL(app?.home_url); } catch { continue; }
    const label = app?.label;
    if (url.protocol !== 'https:' || url.username || url.password || typeof label !== 'string' || !label.trim()
        || [...label].length > 96 || /[\p{Cc}\p{Cs}]/u.test(label)
        // A bare-origin home is a prefix of every page there, so only an exact match means it is open.
        || (url.pathname === '/' ? here === url.href : here.startsWith(url.href))) continue;
    links.push({href: url.href, label});
  }
  return links;
}

export function renderAccountApps(session, anchor) {
  if (!anchor?.after) return;
  const links = appLinks(session), doc = anchor.ownerDocument;
  let menu = anchor.nextElementSibling;
  if (!menu?.matches('[data-account-apps]')) {
    if (!links.length) return;
    if (!doc.querySelector('link[data-account-apps-style]')) {
      const style = doc.createElement('link');
      style.rel = 'stylesheet'; style.href = new URL('./account-apps.css', import.meta.url).href;
      style.dataset.accountAppsStyle = '';
      doc.head.append(style);
    }
    menu = doc.createElement('details');
    menu.className = 'account-apps'; menu.dataset.accountApps = '';
    const summary = doc.createElement('summary');
    summary.textContent = '앱 전환';
    menu.append(summary, doc.createElement('ul'));
    anchor.after(menu);
  }
  menu.hidden = !links.length;
  const shown = JSON.stringify(links);
  if (menu.dataset.accountApps === shown) return;  // the session poll must not close an open menu
  menu.dataset.accountApps = shown;
  menu.querySelector('ul').replaceChildren(...links.map(({href, label}) => {
    const item = doc.createElement('li'), link = doc.createElement('a');
    link.href = href; link.textContent = label; link.target = '_blank'; link.rel = 'noopener noreferrer';
    item.append(link);
    return item;
  }));
}

export function renderAccountProfile(session, root = document) {
  const shell = root.documentElement?.dataset.pilotShell === 'android';
  const view = shell ? null : profileView(session);
  for (const link of root.querySelectorAll('[data-account-profile]')) {
    link.hidden = !view;
    link.textContent = view?.label || '';
    if (view) {
      link.href = view.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
    } else link.removeAttribute('href');
    renderAccountApps(shell ? null : session, link);
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('rosy:account-profile', event => renderAccountProfile(event.detail));
}
