// A focused picker or motor table keeps its card across polling updates.
export function placeRosterCards(box, cards) {
  const focus = document.activeElement;
  const focused = focus?.matches("select, .motor-health-scroll") ? focus.closest("#robot-workspace article") : null;
  const keep = focused?.parentElement === box ? focused : null;
  if (keep) {
    const current = cards.find(node => node.dataset.robotId === keep.dataset.robotId);
    const form = keep.querySelector(".card-trip"), previous = form?.querySelector(".stuck-result");
    const note = current?.querySelector(".card-trip .stuck-result");
    if (previous?.textContent !== note?.textContent) {
      previous?.remove();
      if (form && note) form.append(note);
    }
  }
  const nodes = cards.map((node) => (keep && node.dataset.robotId === keep.dataset.robotId ? keep : node));
  if (!nodes.includes(keep)) { box.replaceChildren(...nodes); return; }
  for (const node of [...box.children]) if (node !== keep) node.remove();
  nodes.forEach((node, i) => { if (box.children[i] !== node) box.insertBefore(node, box.children[i] || null); });
}
