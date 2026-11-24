import test from "node:test";
import assert from "node:assert/strict";

const {
  readStoredToken, writeStoredToken, classifyAuthFailure, bindTokenAccess,
} = await import("../../../../applications/fleet/web/shared/fleet-session.js");
const { renderActiveHistoryList } = await import("../../../../applications/fleet/web/shared/disclosure-list.js");
const { childUnitLinks, renderUnitLinks } = await import("../../../../applications/fleet/web/shared/unit-links.js");

function makeEl(tag, text = "") {
  const attrs = new Map();
  const listeners = {};
  const el = {
    tagName: tag.toUpperCase(),
    textContent: text,
    className: "",
    hidden: false,
    disabled: false,
    open: false,
    value: "",
    href: "",
    rel: "",
    dataset: {},
    children: [],
    get childElementCount() { return this.children.length; },
    get firstElementChild() { return this.children[0] ?? null; },
    replaceChildren(...items) { this.children = [...items]; },
    getAttribute(name) { return attrs.has(name) ? attrs.get(name) : null; },
    setAttribute(name, val) { attrs.set(name, String(val)); },
    removeAttribute(name) { attrs.delete(name); },
    hasAttribute(name) { return attrs.has(name); },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    dispatchEvent(event) {
      for (const fn of listeners[event.type] || []) fn(event);
    },
  };
  return el;
}

function makeFakeStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  };
}

test("readStoredToken and writeStoredToken persist safely across normal and restricted storage", () => {
  const store = makeFakeStorage();
  assert.equal(readStoredToken(store), "");
  writeStoredToken("abc-token", store);
  assert.equal(readStoredToken(store), "abc-token");
  writeStoredToken("", store);
  assert.equal(readStoredToken(store), "");

  const broken = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
    removeItem() { throw new Error("blocked"); },
  };
  assert.equal(readStoredToken(broken), "");
  assert.doesNotThrow(() => writeStoredToken("x", broken));
});

test("classifyAuthFailure distinguishes expired session, D-1043 403 FORBIDDEN, generic 403, and transport loss", () => {
  assert.deepEqual(classifyAuthFailure({status: 401}), {kind: "auth", signOut: true, refused: true, offerLogin: true});
  assert.deepEqual(classifyAuthFailure({status: 403, code: "PASSWORD_CHANGE_REQUIRED"}), {
    kind: "auth", signOut: true, refused: true, offerLogin: true,
  });
  assert.deepEqual(classifyAuthFailure({status: 403, code: "FORBIDDEN"}), {
    kind: "forbidden", signOut: false, refused: false, offerLogin: false,
  });
  assert.deepEqual(classifyAuthFailure({status: 403}), {kind: "auth", signOut: true, refused: false, offerLogin: false});
  assert.deepEqual(classifyAuthFailure(new Error("network")), {kind: "connection", signOut: false, refused: false, offerLogin: false});
});

test("bindTokenAccess wires token input, Enter/save submit, cookie login change, and bootstrap", async () => {
  const prevStorage = globalThis.sessionStorage;
  const store = makeFakeStorage();
  store.setItem("rosy-console-token", "saved-tok");
  globalThis.sessionStorage = store;
  try {
    const field = makeEl("input");
    const save = makeEl("button");
    const loginHost = makeEl("div");
    const nodes = {"console-token": field, "token-save": save, "password-login": loginHost};
    const fakeDoc = {getElementById: (id) => nodes[id] ?? null};

    const credentials = [];
    const typed = [];
    let refreshCalls = [];
    let loginOnChange = null;
    const access = bindTokenAccess({
      doc: fakeDoc,
      persist: true,
      onCredential: (tok, changed) => credentials.push({tok, changed}),
      onTokenInput: (tok) => typed.push(tok),
      createLogin: (_host, opts) => {
        loginOnChange = opts.onChange;
        return {
          refresh(open) {
            refreshCalls.push(open);
            return Promise.resolve(false);
          },
        };
      },
    });

    assert.equal(access.getToken(), "saved-tok");
    field.value = "  new-tok  ";
    field.dispatchEvent({type: "input"});
    assert.deepEqual(typed, ["new-tok"]);

    let prevented = false;
    field.dispatchEvent({type: "keydown", key: "Enter", preventDefault() { prevented = true; }});
    assert.equal(prevented, true);
    assert.deepEqual(credentials.at(-1), {tok: "new-tok", changed: true});
    assert.equal(readStoredToken(store), "new-tok");

    loginOnChange();
    assert.equal(access.getToken(), "");
    assert.equal(readStoredToken(store), "");

    let connected = [];
    let signedOut = 0;
    await access.bootstrap({
      developmentToken: async () => "",
      connect: async (changed) => { connected.push(changed); },
      onSignedOut: () => { signedOut += 1; },
    });
    assert.deepEqual(connected, []);
    assert.equal(signedOut, 1);
    assert.deepEqual(refreshCalls, [true]);

    await access.bootstrap({
      developmentToken: async () => "dev-tok",
      connect: async (changed) => { connected.push(changed); },
      onSignedOut: () => { signedOut += 1; },
    });
    assert.deepEqual(connected, [false]);
    assert.equal(access.getToken(), "dev-tok");
  } finally {
    globalThis.sessionStorage = prevStorage;
  }
});

test("renderActiveHistoryList places active rows first and preserves open historyFold across polls", () => {
  const prevDoc = globalThis.document;
  globalThis.document = {createElement: (tag) => makeEl(tag)};
  try {
    const container = makeEl("ul");
    const historyFold = makeEl("details");
    const historySummary = makeEl("summary");
    const historyContainer = makeEl("ul");
    const sigMap = new Map();

    const first = renderActiveHistoryList({
      container, historyFold, historySummary, historyContainer,
      items: [{id: "a1", active: true}, {id: "h1", active: false}],
      isActive: (x) => x.active,
      renderItem: (x) => makeEl("li", x.id),
      emptyActiveText: "없음",
      sigMap, sigKey: "rows",
    });
    assert.equal(first.active.length, 1);
    assert.equal(first.history.length, 1);
    assert.equal(container.children[0].textContent, "a1");
    assert.equal(historyContainer.children[0].textContent, "h1");
    assert.equal(historyFold.hidden, false);
    assert.equal(historySummary.textContent, "이전 기록 1건");

    historyFold.open = true;
    renderActiveHistoryList({
      container, historyFold, historySummary, historyContainer,
      items: [{id: "h1", active: false}, {id: "h2", active: false}],
      isActive: (x) => x.active,
      renderItem: (x) => makeEl("li", x.id),
      emptyActiveText: "없음",
      emptyHistoryOnlyText: "현재 항목 없음",
      sigMap, sigKey: "rows",
    });
    assert.equal(historyFold.open, true);
    assert.equal(container.children[0].textContent, "현재 항목 없음");
    assert.equal(historySummary.textContent, "이전 기록 2건");

    renderActiveHistoryList({
      container, historyFold, historySummary, historyContainer,
      items: [{id: "a2", active: true}],
      isActive: (x) => x.active,
      renderItem: (x) => makeEl("li", x.id),
      emptyActiveText: "없음",
      sigMap, sigKey: "rows",
    });
    assert.equal(historyFold.hidden, true);
    assert.equal(historyContainer.children.length, 0);
  } finally {
    globalThis.document = prevDoc;
  }
});

test("childUnitLinks and renderUnitLinks enforce D-977 verified HTTPS origins", () => {
  const prevDoc = globalThis.document;
  globalThis.document = {createElement: (tag) => makeEl(tag)};
  try {
    const summary = {
      child_arm_units: ["cell-a", "cell-http", "cell-token", "cell-path"],
      child_origins: {
        "cell-a": "https://cell-a.example:8543",
        "drive-b": "https://drive-b.example",
        "cell-http": "http://cell-http.example",
        "cell-token": "https://user:pass@cell-token.example",
        "cell-path": "https://cell-path.example/token=abc",
      },
    };
    assert.deepEqual(childUnitLinks(summary, {includeCell: true}), [
      {href: "https://cell-a.example:8543/console/cell", label: "cell-a 셀 관제 화면 열기"},
    ]);
    assert.deepEqual(childUnitLinks(summary, {target: "drive-b", includeConsole: true, includeCell: true}), [
      {href: "https://drive-b.example/console", label: "관제 화면 열기"},
    ]);

    const host = makeEl("div");
    const sigCache = new Map();
    const links = childUnitLinks(summary, {includeCell: true});
    renderUnitLinks(host, links, {sigCache, hideWhenEmpty: true});
    assert.equal(host.hidden, false);
    assert.equal(host.children.length, 1);
    assert.equal(host.children[0].className, "ui-action-link");
    assert.equal(host.children[0].dataset.kind, "quiet");
    assert.equal(host.children[0].rel, "noreferrer");

    const sameRef = host.children[0];
    renderUnitLinks(host, links, {sigCache, hideWhenEmpty: true});
    assert.equal(host.children[0], sameRef);

    renderUnitLinks(host, [], {sigCache, hideWhenEmpty: true});
    assert.equal(host.hidden, true);
    assert.equal(host.children.length, 0);
  } finally {
    globalThis.document = prevDoc;
  }
});
