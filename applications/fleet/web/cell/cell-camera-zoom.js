import {actionIcon} from '/common/ui.js';

export function buildCameraZoomHeading(card, label, onExpand) {
  const heading = document.createElement('div');
  heading.className = 'cell-camera-card-head';
  const title = document.createElement('h4');
  title.textContent = label;
  const zoom = document.createElement('ui-button');
  zoom.setAttribute('kind', 'quiet');
  zoom.setAttribute('type', 'button');
  zoom.setAttribute('data-icon-only', '');
  zoom.setAttribute('aria-label', label + ' 크게 보기');
  const setZoom = (expanded) => {
    card.classList.toggle('focused', expanded);
    zoom.setAttribute('aria-pressed', String(expanded));
    zoom.setAttribute('data-ui-tooltip', expanded ? '원래 크기' : '크게 보기');
    actionIcon(zoom, expanded ? 'fit' : 'expand');
    if (expanded) onExpand?.();
  };
  setZoom(false);
  zoom.addEventListener('click', (event) => {
    event.stopPropagation();
    setZoom(!card.classList.contains('focused'));
  });
  zoom.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && card.classList.contains('focused')) {
      event.stopPropagation();
      setZoom(false);
    }
  });
  card.addEventListener('click', (event) => {
    if (!event.target.closest('button, ui-button, a, [data-cam-object]')) zoom.click();
  });
  heading.append(title, zoom);
  return heading;
}
