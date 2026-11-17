// 관제 접속 토큰 — 이 탭의 sessionStorage 에만 둔다(D-193). 읽기·저장·삭제와 "로그인이 필요한 오류" 판정을
// 여러 문서가 따로 쓰지 않게 한다. DOM 없는 순수 모듈이라 node 로 시험한다.
export const TOKEN_KEY = "rosy-console-token";

export const readToken = () => sessionStorage.getItem(TOKEN_KEY) || "";

// 빈 값은 저장하지 않고 지운다.
export function storeToken(token) {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

// 401 이거나 첫 로그인 비밀번호 변경 대기면 세션을 다시 열어야 한다. 403(권한 없음)은 여기에 들지 않는다.
export const isSignedOut = (error) => error?.status === 401 || error?.code === "PASSWORD_CHANGE_REQUIRED";
