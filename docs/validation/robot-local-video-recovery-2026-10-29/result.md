# 로봇 자체 영상·수집 복구 검증

날짜: 2026-10-29. 소스 변경은 `fix/robot-local-video-recovery`에 있으며 아직 통합하지 않았다.

## 소스와 원격 시험

- 연결 준비 중인 primer를 지연된 영상으로 오판하지 않도록 실제 WebRTC 연결 준비와 첫 프레임을 구분했다. 준비 시간 초과·송출 종료에는 기존 authority binding도 닫아 재시도에서 새 grant를 받는다.
- 재시작한 encoder에 현재 낮춘 전송률을 첫 프레임 전에 적용한다. 네트워크 측정은 시청자 부재·연결 준비 중에도 계속한다. 대역폭·지연·신선도 한도는 유지했다.
- 공유 WHEP 클라이언트는 숨겨진 video도 명시적으로 재생한다. 재생 거절·시간 초과에는 peer·WHEP·grant를 해제한다. 화면 표시는 기존 렌더된 watermark의 신선도 판정을 따른다.
- GStreamer 핵심 런타임 버전과 플러그인의 배포 버전을 구분한다. 정상 libnice 버전이 GStreamer 핵심 버전과 다르다는 이유로 probe에서 탈락하지 않는다.

| 리비전 | 원격 검증 | 결과 |
|---|---|---|
| `d6be19bd7c` | 숨겨진 video 재생 회귀, 모델 PC | 2 failed, 9 passed: 수정 전 재현 |
| `1c8923b441` | media + shared WHEP + native probe 계약, 모델 PC | 82 passed |
| `1c8923b441` | selector 영향 범위, 모델 PC | 4,301 passed, 156 skipped, 62 subtests + 별도 10 passed |
| `ae7610a6d1` | 시청자 부재·협상 중 NIC 측정 회귀, AI PC | 1 failed, 15 passed: 수정 전 재현 |
| `93d04a2b2e` | media + shared WHEP + native probe 계약, AI PC | 83 passed |

집중 시험·영향 검사 로그는 외부 `%TEMP%/rosy-play-green/`, `%TEMP%/rosy-wire-window-green/`, `%TEMP%/rosy-video-affected/`에 보존한다. 알려진 실패 비교는 각 최종 로그에 시행한다. AI PC의 최종 실행은 공식 runner가 자원 하한 미달 fallback으로 직렬 실행했으며 peak 83 MiB였다. 이 결과를 장치·현장 수용으로 올리지 않는다. 브라우저 범위 검사는 별도 실행 중이며 완료 수치를 확인하기 전에는 통과로 간주하지 않는다.

## 실제 장치와 운영 경계

기존 단일 카메라의 main 640×480과 perception lores를 유지하고, native GStreamer·MediaMTX·authority·TLS gateway를 별도 media slice에 구성했다. aggregate 상한은 CPU 150%, 메모리 512 MiB, tasks 96이다. source/read 자격은 분리했다. CORE에 빠진 고정 버전 의존성은 별도 overlay에 설치했다. 기존 서명 릴리스의 파일은 수정하지 않았다.

초기 실제 Edge 측정에서는 명시적 재생을 진단으로 적용하자 66개의 서로 다른 watermark 프레임, 8.13 fps, 최대 간격 236.1 ms가 나왔다. 이 측정은 재생 결함의 원인 확인이며, 이후 공용 클라이언트와 연속 NIC 측정 수정 전체의 배포 수용이 아니다. 공용 클라이언트 `1c8923b441`는 CORE의 서비스 전용 읽기 전용 bind mount로 배포했고, 호스트에서 원래 서명 파일의 해시가 보존됨을 확인했다. 마지막 NIC 측정 수정의 장치 배포·렌더 검증은 장치 연결이 돌아온 뒤 수행해야 한다.

장치 초기화 서비스가 CORE를 native HTTPS로 바꾸면서 기존 HTTP upstream이 실패했다. gateway의 upstream도 native CA·인증서 이름을 검증하는 HTTPS로 맞춰 실제 200 응답을 확인했다. 백그라운드 OS 다운로드는 설치·trial 거래가 없음을 확인한 뒤 download-only 서비스를 재시작해 32 KB/s로 제한했다. 업데이트 완료 시간은 늘어난다. 최초 녹화 전송은 기존 2 Mbps로 완료했고, 이후 자동 수집은 0.25 Mbps로 제한했다. 실제 영상과 향후 자동 수집의 동시 부하 수용은 별도 확인 대상이다.

장치 연결은 Windows와 모델 PC 양쪽에서 다시 끊겼고 공유기 Tailscale 연결은 살아 있었다. 마지막 수정의 설치·실제 자동 재생·장시간 안정성은 이 상태에서 확인할 수 없다. 별도 태블릿, Android, 실제 이동, 새 서명 ARM64 이미지, OS 슬롯 전환, 6대 현장 수용도 확인하지 않았다.

## 녹화 자료

기존 D-534 HTTP fetch를 승인된 모델 코드 executor와 collection lock으로 실행했다. 별도 operator 자격과 CA를 사용하고 로봇 원본을 보존했다. 기존 다른 로봇의 수집 설정은 유지했다. 모델 작업이 사용 중이면 잠금을 우회하지 않고 재시도한다.

- 완료 녹화 2개: raw manifest의 26개 파일, 80,235,633 bytes를 독립적으로 크기·SHA-256 재검사했다. 두 manifest SHA는 장치 목록에서 먼저 확인한 값과 같았다.
- 변환 MP4·JSONL: 4,809 + 52 = 4,861프레임. 각 `.paired` receipt의 영상·sidecar SHA와 실제 파일이 일치했다. 조작값 페어링 검증과 사람 라벨 승인은 구분한다.
- 기존 Pinky 검토 서비스의 상태 저장소에 919 + 6 = 925개 표본이 object/pixel 각각 pending으로 존재한다. 사람 라벨을 추가하거나 학습을 승인하지 않았다.
- 원본은 `data/perception/raw/`, 변환은 `data/teleop/learning/`, 검토 입력은 `data/perception/pilot-review/`, 페어링 증거는 raw의 `.paired/`에 있다. `--apply` 정리·삭제는 실행하지 않았다.
- Pinky 검토 서비스와 별도 Learning Center의 상태·class set이 다르다. 기존 Pinky 수집 경로가 실제 Pinky 서비스로 연결됨을 확인했으며, 별도 프로젝트의 빈 상태로 DB를 복사하거나 경로를 바꾸지 않았다.

새 수집 timer는 10분 주기로 활성화됐다. 이번에 발급된 operator 자격은 2026-11-05 만료이며 갱신이 필요하다. 자격 값은 기록하지 않는다.

## CE

기존 교훈 `docs/solutions/workflow-issues/guards-validated-only-against-synthetic-fixtures-2026-09-23.md`를 갱신했다. 진단 import가 만든 미등록 bytecode 59개만 가역 격리한 뒤 같은 native 서명 검증기와 runtime 복구가 성공했다. 정상 manifest의 bytecode 1,302개는 보존했다. 이후 `python3 -B`와 첫 import 전 bytecode 금지를 적용했다. 문서 claims·frontmatter 검사는 통과했고, 관련 Recovery hold 용어는 확인했으며 새 용어 추가는 필요 없었다.
