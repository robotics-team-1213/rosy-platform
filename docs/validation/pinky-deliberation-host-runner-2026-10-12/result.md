# Pinky 후보 토론 연결과 호스트 실행 책임 검증

- Date: 2026-10-12
- Contract: [D-672](../../adr/D-672-pinky-advisory-deliberation-host-boundary.md)
- Plan: [책임과 수용 순서](../../plans/2026-10-12-pinky-deliberation-host-runner.md)
- Source commit / local landing: `b4f653c8e3b1b8f583969aaaeb02a3eba76cc387`
- Result: SOURCE / REMOTE TEST / WHEEL-SDIST / LOCAL MERGE PASS. HOST ISOLATION / REAL PROVIDER / DEPLOY / FIELD HOLD.

## Source acceptance

최종 `tools/land.py`의 원격 시험에서 337건 통과, known failures NEW 0, harness lint 오류 0건이다. 기존 검증 시점과 deprecation 경고는 남아 있으며 이를 새 실패로 숨기지 않았다. AI PC의 시험 선택은 CPU·메모리 floor를 충족했다. 노트북에서는 pytest를 실행하지 않았다.

시험은 host launcher, Pinky 판단 연결과 board caller, 후보 supervisor, CLI, durable 원장, 고정 replay, 판단 receipt/API, 기존 정지 근거·중재·무명령 경계, Fleet wheel/sdist 설치, 폴더·문서·레이어 경계를 포함했다. wheel/sdist 설치의 새 Fleet 모듈 import를 확인했으며 실제 호스트 설치를 수행한 것은 아니다.

원격 Linux 자식 프로세스 fixture로 시간 초과·취소·재취소·지연 spawn·출력 초과 후 정리를 검증했다. 일반 프로세스 fixture의 성공을 bwrap/cgroup 실제 격리 증명으로 사용하지 않는다. 독립 코드 검토는 추가 차단 결함 없이 source 범위를 승인했다.

Raw log: `X:/DevTemp/land/feat-deliberation-process/run-1-1.txt`.
SHA256: `27e07faa912db89e31359ca90b08ddd3051cad7e232c736bc841b9df73f97b9b`.
로컬 main에 FF 착지했으며 push·CI·배포 증거는 없다. 공유 main의 다른 세션 미커밋 파일은 보존했다.

## Runtime admission remains HOLD

Model PC의 무제공자 bwrap probe는 `loopback: Failed RTM_NEWADDR: Operation not permitted`로 종료됐다. 도구 설치·kernel 설정 read만으로 실행 가능하다고 판정하지 않았다. 호스트 보호 설정을 낮추거나 host network fallback을 추가하지 않았다.

승격에는 실제 namespace/cgroup 자원 상한·환경/파일/네트워크 비상속·새 세션 자손 종료 확인, 전용 계정과 고정 공급자 프로파일, 실제 CLI 의존성과 출력 envelope, 비용 제한, 팀의 Pinky 독립 정답·정확도/지연 한계가 필요하다. 현재 launcher는 offline-only이며 자동 worker·HTTP 호출이 없다. CORE 명령·정지 해제·주행·학습 후보의 자동 운영 승격을 수행하지 않았다.

Discord는 별도 담당 세션에 source 경계와 HOLD 상태를 전달했다. 이 기록은 해당 세션의 작업 완료·메시지 수신·알림 발송 증거가 아니다.
