# OpenCode 고정 CLI 수용

실제 설치 버전은 1.18.35이고 run 도움말에는 --pure가 있다. 기존 Decision 번역기의 2.0.22 --standalone을 그대로 보내면 설치 버전과 맞지 않는다. CliProvider와 sandbox_provider에 명시 cli_version을 전달하고 1.18.35는 --pure, 2.0.22는 기존 --standalone을 사용한다. 다른 버전은 거절한다.

--pure는 외부 플러그인 제한이며 도구·설정 차단 증거가 아니다. 기존 event allowlist, 비용 불명/초과 거절, 출력·시간 제한, snapshot 정리를 유지한다. 설치 실행 파일 digest는 `77b2cfe4b97df6f15c3673b22100b9f79c711f25ecb9bf513bb82526b15d24fa`다.

소스 `4ebcb80c86bcdf889defd086f3e0717e393c33ba`, 병렬 작업 remote 48 passed, NEW 0, independent review blocker 없음. Log: `X:/DevTemp/projects/rosy-platform/2026-10-12--031946--opencode-admission--52ffd0/logs/final/run-1.txt`, SHA256 `cc8d4379f0bf4af21a288b9575dc589dabb4266d482b8ae878fb48b45f6aac07`.

다음은 관리자 전용 providers 경로에 이 digest의 실행 파일만 stage한 뒤, 기존 sandbox launcher로 --version 및 run --help를 실행하는 단계다. 별도 스모크 script를 AI PC 임시 경로에 준비했으며 관리자 계정의 shell redirection으로 전용 계정 Python stdin에 전달한다. 개인 홈·설정·credential을 열어 주지 않는다. 실제 모델 호출은 이 단계에서 0회다. 성공은 PASS_OFFLINE_OPENCODE_CLI_ONLY로만 기록한다.

그 다음 실제 OpenCode→로컬 Qwen 호출에는 최소 제공자 연결 경계와 token cap이 필요하다. fresh HOME/XDG, host /etc 비노출, provider ollama만 허용, 모든 도구와 agent override 거절, plugin/MCP 비활성, autoupdate/share/snapshot 비활성을 검수한다. 승인된 loopback 요청만 중계하는 경로 없이 네트워크 namespace를 공유하는 fallback을 쓰지 않는다. 인증된 온라인 GLM/Claude와 유료 호출은 이번 수용에서 활성화하지 않는다.
