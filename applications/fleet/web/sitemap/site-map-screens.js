// D-926 3: the sub-nav moves between screens. The map stays as the shared stage; only the chosen task shows below it.
const STAGE = 'map-heading';
const GROUPS = {'survey-heading': ['survey-heading', 'drawing-heading']};

export function bindScreens(main, nav, map) {
  const links = [...nav.querySelectorAll('a[href^="#"]')];
  const known = new Set(links.map(link => link.hash.slice(1)));
  const sections = [...main.querySelectorAll('ui-section[aria-labelledby]')];
  const current = () => (known.has(location.hash.slice(1)) ? location.hash.slice(1) : STAGE);
  const show = () => {
    const screen = current(), visible = new Set([STAGE, ...(GROUPS[screen] || [screen])]);
    for (const section of sections) section.hidden = !visible.has(section.getAttribute('aria-labelledby'));
    for (const link of links) {
      if (link.hash.slice(1) === screen) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    }
  };
  addEventListener('hashchange', show);
  // The map legend promises that picking a place or lane on the view screen opens it for editing.
  map.addEventListener('click', event => {
    if (current() === STAGE && event.target.closest('[data-place], [data-edge], [data-crosswalk]')) location.hash = '#edit-heading';
  });
  show();
}
