// D-461: opt-in task rows, composed from existing ROSY controls. Text only.
import '/common/ui.js';

export function taskRow({title, subtitle = '', status = '', attention = false, description = ''}) {
  const row = document.createElement('article');
  row.className = 'ui-task-row';
  const heading = document.createElement('header');
  heading.className = 'ui-task-heading';
  const name = document.createElement('h3'); name.textContent = title;
  const tag = document.createElement('ui-tag'); tag.textContent = status;
  tag.setAttribute('status', attention ? 'warn' : 'neutral');
  heading.append(name, tag); row.append(heading);
  if (subtitle) {
    const meta = document.createElement('p'); meta.className = 'ui-task-meta';
    meta.textContent = subtitle; row.append(meta);
  }
  if (description) {
    const next = document.createElement('p'); next.className = 'ui-task-next';
    next.textContent = description; row.append(next);
  }
  return row;
}
