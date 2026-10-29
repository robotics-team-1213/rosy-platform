# Learning 자료·계정·작업 공간의 상태 복구

기준 `5e6aeb1e2a`, 최종 제품 소스 `03d493964c`, 시험 보완 `4bf1db6427`다. 2026-10-28에 시작해29일에 마무리했다. `fix/robot-pilot-learning-ux`에서 기존 상태·버튼·목록 부품을 재사용했다. 새 토큰·의존성·API·ADR은 없다.

| 문제 | 수정·경계 |
|---|---|
| Catalog의 실패·취소·차단·권한 보류·미확인 HF 작업이 진행 중으로 보임 | learning_imports.py의 실제 상태와 표시를 대조했다. 대기/실행과 terminal 상태를 구분하고 상태·권한 관리로 이동한다. completed만 기존 검수 인계 동작을 제공한다. |
| 하위 목록 GET 실패를 섹션 숨김으로 처리하고 401/403 후 활성 폼이 무반응 | 목록의 pending/error/empty/ready와 다시 확인을 표시한다. 등록 권한 상실은 폼에도 반영한다. 마지막 목록은 마지막 확인 결과임을 표시하고 전송을 잠근다. 재조회는 작성 중 경로를 보존한다. |
| HF 검수 인계 후 목록 GET 전에 잠금이 풀림 | 후속 GET까지 기다리고 모든 관련 버튼을 잠근다. 성공한 행의 결과 링크로 돌아가며 사용자가 옮긴 초점은 빼앗지 않는다. |
| 계정 자동 GET이 사용자 작업 실패를 지움 | 명시적 작업 오류와 자동 조회 오류를 분리한다. 자동 조회가 복구돼도 작업 오류는 유지하고 사용자 재시도에서 해제한다. 로그아웃은 이전 세션의 오류·입력을 정리한다. |
| 새로고침이 선택한 HF 연결 B를 첫 연결 A로 바꿈 | 유효한 ID를 보존한다. 사라진 ID는 반복 새로고침에서도 명시적 재선택을 요구하며 빈 ID 요청을 막는다. 초기 빈 목록에서 첫 연결이 생기는 기존 흐름은 유지한다. |
| 느린 자동 GET 중 활성처럼 보이는 작업 버튼의 클릭이 버려짐 | 기존 직렬화를 유지하면서 실제 정적/동적 버튼을 잠그고 기존 상태 줄에 진행을 표시한다. 입력과 권한별 disabled 상태를 보존하며 자동 POST 대기열·재송신은 하지 않는다. |
| 재시도·취소 후 원래 버튼이 사라져 초점이 body에 남음 | 현재 job의 상태 문구로 복원한다. 같은 버튼이 있으면 해당 버튼으로 복원하고, 사용자가 다른 제어로 이동했다면 유지한다. |
| 계정 페이지의 작은 기본 브라우저 버튼이 다른 Learning 조작과 다름 | 정적8개와 동적 계정/작업 버튼을 공용 ui-button으로 통일했다. 기존 primary/quiet/irreversible 역할과 최소44px 표적을 사용하고 실제 삭제의 이름 확인·submit·API는 유지했다. |
| Workspaces 오류에 복구 동작이 없고 재시도 초점이 사라짐 | 같은 다시 확인 버튼을 제공하고 이전 링크를 지운 뒤 pending/error/empty/ready를 표시한다. 중복 요청을 막고 원래 버튼에서 시작했을 때만 조건부 초점을 복원한다. |

## 원격 증거

원본은 외부 `C:/DevTemp/rosy-ui-product-data-review/`에 보존한다. pytest는 승인된 시험 PC의 커밋에서만 실행했다. 합성 ReviewStore·HF 연결·작업·권한·지연 응답을 사용했고 실제 HF·실물·사람 라벨에는 접근하지 않았다. 기존 검증 파일의 실제 HTTP/SQLite 경로와 대체 HF transport 성공 회귀도 유지했다.

| 실행 | SHA | 결과 |
|---|---|---|
| 첫 RED | `60bfe60276` | 31 failed. terminal 오표시·숨긴 실패·계정 선택/오류·복구 부재 재현. 대기/실행 명칭 통일도 포함 |
| 첫 GREEN | `5028ccd264` | 43 passed/7 failed. 새 잠금에서 초점을 너무 늦게 읽는 실제 결함7건을 발견 |
| 인계·재조회 초점 GREEN | `adbf87eb2a` | 52 passed, skip0. 기존 계정/검수 인계·작업 공간 성공 회귀 포함 |
| 느린 계정 조회 RED | `970a6da1b8` | 3 failed/36 deselected. 작업 버튼이 잠기지 않는 상태 재현 |
| 계정 잠금 GREEN | `4e8e75bfe1` | 47 passed, skip0. 기존 계정 성공 경로와 명시적 요청/자동 조회 분리 |
| 최종 상태·촬영 | `cd224ea53f` | 43 passed, skip0. 취소→cancelled/재시도→running과 초점 이동4분기 포함 |
| 최초 공식 브라우저18파일·8묶음 | `adbf87eb2a` | 300 passed, skip0 |
| 공용 버튼 기능 검사 | `03d493964c` | 51 passed/6 failed. 6건은 details 자체에 details 자식을 찾은 잘못된 geometry fixture selector timeout |
| 공용 버튼 크기·테마 검사 | `4bf1db6427` | 6 passed/43 deselected. 실제 summary 문구로 열고 기존 크기·넘침·역할 assertion을 유지 |
| 최종 계정 변경 범위9파일·8묶음 | `03d493964c` | 최초259 passed/6 fixture failed. 아래 전체 묶음 교체 뒤 유효 선택265 passed/skip0 |
| 잘못된 selector가 있던 묶음 전체 재검증 | `4bf1db6427` | 49 passed, skip0. 최종 제품과 화면 소스 동일; browser-corrected/data-recovery.txt |
| 최종 공식 영향 | `03d493964c` | 3012 passed/439 skipped, NEW0. affected, escalation/미매핑 없음 |

자동 조회/작업 직렬화를 풀면 이전 GET이 새 POST 뒤의 목록·초점을 덮을 수 있어 기존 직렬화를 유지했다. 새 동작은 숨긴 클릭 대신 잠금·진행을 표시하고, 새 요청은 사용자가 다시 명시적으로 실행한다. disabled가 초점을 제거하기 전에 시작점을 보존하고, 같은 job의 변경된 제어·상태를 잠금 해제 후 복원한다. 기존 assertion은 약화하지 않았다.

`adbf87eb2a` 이후 제품 변경은 Accounts HTML·JS에 한정되며 나머지 화면 소스는 같다. 최종 변경의 공식 browser_scope 선택9파일을 새 SHA로 재검증하고, 변경하지 않은 나머지는 최초18파일 결과와 구분한다. 마지막9파일의 다른7묶음216 passed에 교정한 전체 묶음49 passed를 더한 결과가265 passed다. 최초 실패는 삭제하거나 같은 로그 뒤에 성공으로 덮어쓰지 않았다. 최종439 skipped는 브라우저 opt-in·환경 조건 등의 미실행 검사이며 통과로 계산하지 않는다.

## 독립 검토·한계

A는 상태 producer/consumer·계정 선택·직렬화·초점·공용 버튼 submit 경계를 읽었고 최종 `03d493964c`에서 남은 P1/P2가 없었다. B는 별도로 Catalog 하위 조회와 Workspaces 복구를 지적했다. 3문서 detector는0건/exit0이나 `/common` CSS 해석 제한이 있어 동적 상태·색·키보드 계약의 증거로 확대하지 않는다.

독립 B는 `cd224ea53f`의56장 중35장(320px HF8상태, 계정 상태/선택·오류/복구·인계)을 실제 확인했다. 공용 버튼 변경 후의68장은 별도 폴더로 보존했고, B가 새 geometry12장 전체(320/390/1440×dark/light)와 계정 대표6장, 총18장을 실제 검토해 잘림·겹침 없이 위험 동작과 초점·대기 상태가 구별됨을 확인했다. 나머지50장을 새로 검토했다고 주장하지 않는다. 상태 문단의 프로그램 초점은 PNG만으로 확정하지 않고 원격 assertion과 구분한다. 작성자도320px 권한 보류 카드와 계정 전환 화면을 직접 확인했다.

최종 캡처는 `screenshots-controls-final/`, 이전 캡처는 별도 `screenshots-final/`·`screenshots/`에 보존한다. `captures.sha256`·`reports.sha256`는 외부 원본 바이트 해시다.

CE: 해당 없음 — 입력·오류·잠금·초점의 판단을 코드·회귀·이 기록에서 복구할 수 있다. 기존 `docs/solutions/workflow-issues/server-guard-tested-without-its-client.md`의 실제 클라이언트·권한 오류 구분 원칙을 적용했으며 실물 수용 교훈과 이번 UI 검증을 구분했다.

판정/권한·라벨 정본·HF 전송·학습/승격·장치 명령 owner를 바꾸지 않았다. 실제 HF 다운로드/쓰기·모델 평가·실물·APK/ARM64 빌드·배포·merge/push는 수행하지 않았다. 이 결과는 DEVICE/FIELD 수용이 아니다.
