# Rosy Media

영상 세션 권한, 시청 요청, 미디어 프로세스 관리를 맡는 공통 서비스다([D-789](../../../docs/adr/D-789-six-robot-webrtc-camera-transport.md), [카탈로그](../../../docs/reference/common-services.md)). Fleet이 설치하거나 제공하지 않고, 로봇 제어 권한이 없다.

| 알고 싶은 것 | 볼 곳 |
|---|---|
| 현재 검증·배포 상태 | [progress.md](progress.md) |
| 변경 기록 | [logs.md](logs.md) |
| 수정 규칙과 시험 | [AGENTS.md](AGENTS.md) |

## 코드가 있는 곳

| 역할 | 위치 |
|---|---|
| 미디어 위임 검증과 CORE 재확인 | `src/rosy_media/authority.py` |
| MediaMTX callback과 시청 요청 | `src/rosy_media/server.py` |
| 미디어 프로세스 감독 | `src/rosy_media/supervisor.py` |
| 현장 배치 | `deploy/site/compose.media.yaml`, `deploy/site/Dockerfile.media` |
| 로봇 쪽 영상 송출 | `middleware/media` (D-791) |
