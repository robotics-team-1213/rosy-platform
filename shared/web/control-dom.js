// Small DOM builders shared by compositions; content is always text, never HTML.
import "/common/ui.js";

export function node(tag, text = "", className = "") {
  const result = document.createElement(tag);
  result.textContent = text;
  if (className) result.className = className;
  return result;
}

export function action(label, onClick, kind = "quiet") {
  const button = node("ui-button", label);
  button.setAttribute("kind", kind);
  button.setAttribute("type", "button");
  if (onClick) button.addEventListener("click", onClick);
  return button;
}

export function input(id, label, type = "text") {
  const wrapper = node("label", label, type === "checkbox" || type === "radio" ? "ui-check" : "ui-field-label");
  const control = node("input", "", "ui-field");
  control.id = id;
  control.name = id;
  control.type = type;
  wrapper.htmlFor = id;
  wrapper.append(control);
  return {element: wrapper, control};
}

export function select(id, label, choices) {
  const element = node("label", label, "ui-field-label");
  const control = node("select", "", "ui-field");
  control.id = id;
  control.name = id;
  for (const {value, label: text} of choices) control.add(new Option(text, value));
  element.append(control);
  return {element, control};
}
