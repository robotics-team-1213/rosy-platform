import {prepareConsoleSession} from "../client.js";

// 기기 연결 코드 발급은 로봇 대시보드만 맡는다(D-370:155, 2026-11-17 사용자 결정).
// Pilot은 자기 로그인만 하고 발급 화면으로 가는 링크만 둔다. 반대 방향(상대 화면 코드 →
// 이 태블릿 입력)은 접속 폼의 pairWithCode. 대시보드에 발급 전용 경로가 아직 없어 루트로 잇는다.
export function mountShowCode(root) {
  const section = document.createElement("div");
  section.dataset.enrollSection = "";
  const note = document.createElement("p");
  note.dataset.enrollGuidance = "";
  note.append("기기 연결 코드는 로봇 대시보드에서 발급합니다 ");
  const link = document.createElement("a");
  link.href = "/dashboard";
  link.textContent = "로봇 대시보드 열기";
  link.dataset.enrollLink = "";
  link.addEventListener("click", prepareConsoleSession);  // 같은 탭 인증 인계(운용 지도와 같은 방식)
  note.append(link);
  section.append(note);
  root.append(section);
}
