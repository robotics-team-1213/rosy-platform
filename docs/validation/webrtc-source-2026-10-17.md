# D-789 첫 WebRTC 소스 구현 검증 — 2026-10-17

사용자가 목표를 등록하고 즉시 구현하도록 요청한 뒤 전용 워크트리에서 수행한 첫 구현 기록이다.
브랜치는 `feat/webrtc-camera-migration`이며 base는 ADR·계획 커밋 `060dc8f436`이다.

## 확인한 것

- 원격 AI 역할 시험 PC의 Ubuntu x86_64에서 실행했다. 시험 의존성은 `~/rosy-test/media-runtime-d789` 안에 apt 패키지 39개를 추출해 구성했다. 시스템 설치·Fleet/로봇 재시작은 하지 않았다.
- 공식 MediaMTX v1.21.2 AMD64/ARM64 archive를 내려받아 공식 release API의 SHA256과 일치함을 확인했다. ARM64 파일 다운로드는 ARM64 실행이나 제품 payload 수용을 뜻하지 않는다.
- 실제 GStreamer `webrtcbin`·x264 → 인증된 WHIP → MediaMTX → WHEP → 실제 headless Chromium 재생을 실행했다. 렌더 프레임의 watermark에서 epoch 17, sequence 47과 51 및 UTC capture milliseconds를 회수했다. 자동으로 재인코딩했다는 가정을 쓰지 않았다.
- 실제 loopback의 시그널링은 시험용 loopback HTTP였다. 제품 HTTPS·인증서·Android·무선망 검증을 대신하지 않는다.
- CORE 영상 grant는 일반 CORE Bearer와 분리된 Ed25519 서명·로봇/path/action/audience·최대 60초에 결속된다. Account media check는 10초 cache/offline grace를 사용하지 않는다.
- media authority/감독 정책은 현재 단위·HTTP 및 소유 subprocess 검증이다. 실제 MediaMTX session kick와 production supervisor 배치 결합은 후속 검증이다.

## 커밋별 원격 결과

서로 겹치는 회귀 묶음이 있으므로 아래 계수를 합산해 고유 시험 수라고 부르지 않는다.
중간 RED·환경 실패는 같은 외부 scratch의 별도 폴더에 보존했다. NEW baseline은 변경하지 않았다.

Log SHA256 values: [webrtc-source-2026-10-17.sha256](webrtc-source-2026-10-17.sha256) (sha256sum format).

| Revision | Log (external scratch relative path) | Result |
|---|---|---|
| `75600d7705` | `t1-green/run-1.txt` | 5 passed; runtime inventory, no native acceptance |
| `34cee8b1cc` | `watermark-green/run-1.txt` | 6 passed; capture identity primitives |
| `c2fe2e5d4b` | `whip-green/run-1.txt` | 13 passed; WHIP signaling and watermark, overlaps prior watermark suite |
| `c2fe2e5d4b` | `loopback-offer/run-1.txt` | 1 passed; real synthetic H.264/WHIP/MediaMTX/WHEP/Chromium rendering |
| `0d80797f10` | `grants-green/run-1.txt` | 6 passed; original CORE authority and scoped grants |
| `1d5230667e` | `media-config-green/run-1.txt` | 16 passed; media API plus existing import/MJPEG regression |
| `77ccc7ed02` | `account-media-green/run-1.txt` | 14 passed; Account client suite including strict media revalidation |
| `683d93218b` | `media-server-green/run-1.txt` | 13 passed; media lease, HTTP and process ownership |

## 미확인·진행 중

T1의 native Ubuntu 24.04 ARM64 package closure·실행·Android, T2의 실제 MediaMTX kick 결합,
T3의 기존 단일 카메라 producer/IPC 연결·자원 정책, T4의 운영 뷰어 전환,
T5의 서명 payload/site 설치, T6의 6대 30분·지연 p95·wire 예산·제어 deadline 수용은 미완료다.
기존 JPEG/MJPEG와 운영 기본값은 유지한다. synthetic source 증거로 DEVICE/FIELD를 승격하지 않는다.
