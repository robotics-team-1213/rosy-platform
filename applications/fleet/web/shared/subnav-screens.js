// D-926 3: an in-page sub-nav moves between screens instead of jumping down one long page.
// `mark` is 'step' when the sub-nav also links to the page itself. `stage` stays visible on every screen (the site map); `groups` lists headings that belong to a screen without a link.
// `label` (D-926 2 path bar) mirrors the current screen's name in the document head.
export function bindScreens({nav, home, stage = null, groups = {}, mark = 'page', label = null}) {
  const links = [...nav.querySelectorAll('a[href^="#"]')];
  const known = new Set(links.map(link => link.hash.slice(1)));
  const holder = id => document.getElementById(id)?.closest('ui-section, details');
  const managed = [...known, ...Object.values(groups).flat()].filter(id => id !== stage);
  const current = () => (known.has(location.hash.slice(1)) ? location.hash.slice(1) : home);
  const show = () => {
    const screen = current(), visible = new Set(groups[screen] || [screen]);
    for (const id of managed) {
      const box = holder(id);
      if (!box) continue;
      box.hidden = !visible.has(id);
      if (!box.hidden && box.localName === 'details') box.open = true;
    }
    for (const link of links) {
      if (link.hash.slice(1) === screen) link.setAttribute('aria-current', mark);
      else link.removeAttribute('aria-current');
    }
    const active = links.find(link => link.hash.slice(1) === screen);
    if (label && active) label.replaceChildren(active.textContent.trim());
  };
  addEventListener('hashchange', show);
  // The same link again changes no hash; it still reopens a step the operator folded.
  for (const link of links) link.addEventListener('click', () => { if (link.hash === location.hash) show(); });
  show();
  return {current};
}
