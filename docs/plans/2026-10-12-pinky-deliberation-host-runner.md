# Pinky 판단 연결과 호스트 실행 책임 후속 계획

- 계약: [D-672](../adr/D-672-pinky-advisory-deliberation-host-boundary.md), [D-640 선행 구현](2026-10-12-decision-deliberation-boundary.md).
- 브랜치: `feat/deliberation-process`.
- Discord는 별도 담당 세션이 진행한다. 이 작업은 채널 설정·발송을 수행하지 않는다.

## 소유자와 실제 호출 흐름

`LineStuckBoard.deliberate` → 기존 `intervention_assessment` → Fleet `run_line_judgment` → 기존 `DeliberationJournal.run` → Decision `Supervisor` → `CliProvider` → 호스트 `sandbox_provider`.

앞의 Fleet 호출은 명시적인 shadow 진입점이다. 자동 worker·HTTP·설정 활성화는 없다. 마지막 호스트 연결은 Linux의 검수된 고정 실행 파일과 프로파일을 명시적으로 주입해야 한다. Decision과 Fleet DB에 subprocess·호스트 설정·제공자 자격 증명을 넣지 않는다. 실제 실행 호스트가 Model PC인지 Fleet PC인지는 승인 프로파일로 정하며 노트북에서 모델 실행/시험을 하지 않는다.

| 순서 | 소유자 | 현재 처리와 남은 관문 |
|---|---|---|
| 소유자 확인 | 기존 ADR·각 모듈 | D-640/D-672에 판단, DB, 설치 책임 기록 |
| 모델 원장 도구 분리 | Decision 계약 / Fleet DB | 선행 D-657 경계와 기존 원장 재사용 |
| 작업 규칙 추출 | Situation 판단 / Fleet 현장 연결 | 기존 `Assessment` 재사용; 정상·기권 모델 미호출 |
| 중앙 판단·결과 연결 | Fleet / Decision | Pinky 사건·상태 revision·정책·시각을 보존한 후보 연결 |
| 알림·사람 인수 | Discord 담당 세션 / 팀 | 이번 소스에서 분리; 기존 사람 검수 책임 유지 |
| 독립 평가 | 기존 replay / 팀 정답 검수 | 규칙·단일·토론 비교 도구 재사용; 실제 정답·한계 확정은 HOLD |
| 제한 모델 토론·개선 | Decision / 호스트 설치 | 고정 snapshot, 시간·출력 제한·정리 구현; 실제 격리·모델 smoke 이후에만 활성화 |

## 수용 순서

1. 소스 회귀와 wheel/sdist 설치를 원격 PC에서 확인하고 독립 코드 검토 후 로컬 main에 FF 병합한다.
2. 승인된 Linux 호스트에서 bwrap namespace와 systemd cgroup을 실제 확인한다. 읽기 전용 파일, 환경·설정 비상속, 네트워크 차단, 자원 상한, 새 세션 자손 종료 readback이 필요하다.
3. 전용 계정·고정 CLI/모델 ID·승인된 제공자 접속·비용 제한을 검수한다. 현재 offline-only launcher에는 인증이나 네트워크 허용을 추가하지 않았다. Node 기반 CLI는 선택 실행 파일 하나의 snapshot만으로 의존성이 충족된다고 가정하지 않는다.
4. 팀이 Pinky 차선 정지·재관측 정답과 정확도·지연 한계를 확정한 뒤 동일 사건 세트로 독립 비교한다. 관측 부족·위험 누락·다른 사건 조치·정상 상태 불필요 명령은 수용 세트에서 0건이다.
5. shadow와 제한 장치 수용을 구분해 기록한다. 실제 결과와 사람 교정을 수집하되 새 모델·규칙·사례의 운영 승격은 별도 승인이다.

## 이번 확인과 제한

원격 source `a987bba361`에서 launcher·후보·CLI·원장·replay 등 54건 통과, `2a2045a519`에서 Pinky bridge·판단 receipt·launcher 등 43건 통과했다. 최종 병합 검증은 별도 기록한다.

Model PC의 도구 설치 확인과 실제 격리 확인은 다르다. 무제공자 bwrap probe는 `loopback: Failed RTM_NEWADDR: Operation not permitted`로 실패했다. 호스트 보호 설정을 약화하거나 네트워크를 공유하는 fallback을 만들지 않았다. 따라서 실제 격리·제공자 호출·장치 배포·주행·FIELD는 HOLD다.

실행 명령의 근거: [bubblewrap](https://github.com/containers/bubblewrap/blob/main/README.md), [scope RuntimeMaxSec](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.scope.xml), [scope 전체 종료](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemctl.xml). 이 문서는 실제 실행 증거를 대체하지 않는다.
