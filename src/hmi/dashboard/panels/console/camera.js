import { authHeaders, session } from "/assets/client.js";
import { createVisionPreview } from "/assets/vision.js";

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  const head = el("ui-head", "", "전방 카메라");
  const stage = el("div", "surface-camera-stage"); stage.id = "vision-stage"; stage.dataset.state = "waiting";
  const frame = el("img", "surface-camera-frame"); frame.id = "vision-frame"; frame.alt = "전방 카메라 실시간 영상"; frame.hidden = true;
  const empty = el("ui-empty", "surface-camera-empty", "카메라 프레임 수신 대기"); empty.id = "vision-empty";
  stage.append(frame, empty);
  const status = el("ui-status", "", "WAITING"); status.id = "vision-status";
  const facts = el("dl", "ui-readout");
  const source = el("dd", "", "—"); source.id = "vision-source";
  const resolution = el("dd", "", "—"); resolution.id = "vision-resolution";
  const age = el("dd", "", "—"); age.id = "vision-age";
  const captured = el("dd", "", "—"); captured.id = "vision-captured";
  facts.append(el("dt", "", "소스"), source, el("dt", "", "해상도"), resolution,
    el("dt", "", "프레임 나이"), age, el("dt", "", "촬영 시각"), captured);
  root.append(head, stage, status, facts);
  const elements = {"vision-stage": stage, "vision-frame": frame, "vision-empty": empty,
    "vision-status": status, "vision-source": source, "vision-resolution": resolution,
    "vision-age": age, "vision-captured": captured};
  const preview = createVisionPreview({elements, setText: (id, value) => { elements[id].textContent = value ?? "—"; },
    api: ctx.api, authHeaders, hasToken: () => Boolean(session.token), isHidden: () => document.hidden});
  const visibility = () => { if (document.hidden) preview.stop("화면이 숨겨져 카메라를 중지했습니다."); else preview.start(); };
  document.addEventListener("visibilitychange", visibility);
  preview.start();
  return () => { document.removeEventListener("visibilitychange", visibility); preview.stop("카메라 패널을 닫았습니다."); };
}
