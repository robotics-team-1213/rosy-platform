import { createPasswordLogin } from "/console/assets/password-login.js";

const STORAGE_KEY = "rosy-console-token";

export function readStoredToken(storage = globalThis.sessionStorage) {
  try { return storage?.getItem?.(STORAGE_KEY) || ""; }
  catch { return ""; }
}

export function writeStoredToken(token, storage = globalThis.sessionStorage) {
  try {
    if (token) storage?.setItem?.(STORAGE_KEY, token);
    else storage?.removeItem?.(STORAGE_KEY);
  } catch { /* Restricted storage keeps in-tab credential only. */ }
}

/** D-1043: role refusal (403 FORBIDDEN) keeps the active session and E-stop live; 401/expired signs out. */
export function classifyAuthFailure(error) {
  const status = error?.status, code = error?.code;
  if (status === 401 || code === "PASSWORD_CHANGE_REQUIRED") {
    return { kind: "auth", signOut: true, refused: true, offerLogin: true };
  }
  if (status === 403 && code === "FORBIDDEN") {
    return { kind: "forbidden", signOut: false, refused: false, offerLogin: false };
  }
  if (status === 403) {
    return { kind: "auth", signOut: true, refused: false, offerLogin: false };
  }
  return { kind: "connection", signOut: false, refused: false, offerLogin: false };
}

/** Shared topbar token + password-login binding for Fleet documents. */
export function bindTokenAccess({
  scope,
  onCredential,
  onTokenInput = null,
  persist = true,
  createLogin = createPasswordLogin,
  doc = globalThis.document,
} = {}) {
  const field = () => doc?.getElementById?.("console-token") || null;
  const save = () => doc?.getElementById?.("token-save") || null;
  const loginHost = () => doc?.getElementById?.("password-login") || null;
  const listen = scope?.listen
    ? (target, type, fn) => { if (target) scope.listen(target, type, fn); }
    : (target, type, fn) => target?.addEventListener?.(type, fn);

  const initial = readStoredToken();
  if (field() && initial) field().value = initial;

  const getToken = () => field()?.value?.trim() || "";
  const setToken = (value, { persistValue = persist } = {}) => {
    const next = String(value || "").trim();
    if (field()) field().value = next;
    if (persistValue) writeStoredToken(next);
    return next;
  };
  const submit = () => {
    const next = setToken(getToken(), { persistValue: persist });
    onCredential?.(next, true);
  };

  listen(save(), "click", submit);
  listen(field(), "keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault?.(); submit(); }
  });
  if (onTokenInput) {
    listen(field(), "input", () => onTokenInput(getToken()));
  }

  const login = loginHost()
    ? createLogin(loginHost(), {
        onChange: () => {
          setToken("", { persistValue: true });
          onCredential?.("", true);
        },
      })
    : null;

  async function bootstrap({
    developmentToken,
    connect,
    onSignedOut = () => {},
    onError = () => {},
  }) {
    try {
      const issued = developmentToken ? await developmentToken(getToken()) : "";
      if (issued) {
        setToken(issued, { persistValue: false });
        return await connect(false);
      }
      const cookie = login ? await login.refresh(true) : false;
      if (cookie || readStoredToken()) return await connect(false);
      onSignedOut();
    } catch (error) {
      onError(error);
    }
    return undefined;
  }

  return {
    getToken,
    setToken,
    refreshLogin: (open = false) => login?.refresh?.(open) ?? Promise.resolve(false),
    bootstrap,
  };
}
