# ROSY 에이전트 연결

Codex와 OpenCode는 같은 ROSY 브리지를 쓴다. 터미널을 쓰는 에이전트는 `rosy snapshot`, `rosy diagnose`, `rosy propose --from <진단 폴더> --dry-run` 순서로 관측부터 제안 검증까지 진행한다.

## OpenCode에서 가상 셀 시험

Z.ai Coding Plan에 연결된 OpenCode에서 `opencode models`로 `zai-coding-plan/glm-5.4`를 확인한다. 시험 전용 OpenCode 2.x 설정에 로컬 MCP 서버를 추가한다. 아래 세 URL은 합성 데이터를 반환하는 루프백 HTTP fixture로 바꾼다. [OpenCode MCP 설정](https://opencode.ai/docs/mcp-servers)

```json
{
  "mcp": {
    "servers": {
      "rosy": {
        "type": "local",
        "command": [
          "python", "-X", "utf8", "<저장소>/tools/remote/rosy_agent_bridge.py",
          "--cell-url", "http://127.0.0.1:18781",
          "--fleet-url", "http://127.0.0.1:18000",
          "--learning-url", "http://127.0.0.1:18768",
          "mcp-stdio", "--operations-only"
        ]
      }
    }
  }
}
```

1. 시험 폴더에서 OpenCode 세션을 연 뒤 `opencode mcp list`로 ROSY 연결을 확인한다. 별도 서버로 세션을 열었다면 목록 조회에도 같은 `--server`를 지정한다.
2. 모델을 `zai-coding-plan/glm-5.4`로 지정한다. 가상 실패 번들과 해당 셀의 readiness를 조회한 뒤 한 번의 제안을 만들도록 요청한다.
3. 가상 Fleet이 `propose: true`, 동일한 `request_key`, 번들과 readiness의 CAS 값을 받았는지 확인한다. 응답 상태는 `PROPOSED`다.

브리지의 `--operations-only`는 관측 및 Fleet 제안 도구 9개를 제공한다. 같은 목록을 도구 호출에도 적용한다. 브리지는 Fleet 요청에 `propose: true`를 붙이고 응답에서 `PROPOSED`를 확인한다. Fleet에서 다른 작업자 ID가 제안을 승인해야 한다.

정책 실패의 후속 제안은 원래 작업 ID를 포함한다. `rosy diagnose`는 실패 번들의 `correlation.fleet_task_id`를 저장하고, `rosy propose`는 이를 `fallback_from_task_id`로 전달한다. 네이티브 MCP 호출에서는 이 값을 실패 번들에서 읽어 제안에 넣는다. Fleet이 `STALE_FAILURE_CONTEXT`를 반환하면 번들과 readiness를 다시 조회한다.

진단은 만료된 실패 기록도 보여 준다. 제안 검증과 제출에서는 셀에서 해당 번들을 다시 읽고 유효성·해시·대상 및 허용된 복구 동작을 확인한다. 모델 추론 중 번들이 만료되면 제안이 거절된다. 그때는 기존 기록을 진단 근거로 쓰고, 새 제안에는 유효한 실패 맥락과 현재 readiness가 필요하다.

클라우드 모델에 전달하는 도구 응답에는 현장 상태와 카메라 프레임이 포함될 수 있다. GLM 시험에는 합성 fixture를 사용한다. 실데이터 연결은 D-1072의 기본 거부 전송 정책과 허용된 데이터 등급 및 마스킹을 적용한 경로에서 수행한다. [D-1072 외부 전송 관문](../adr/D-1072-omx-ai-failure-fallback-context-and-agent-tool-pipeline.md)
