# 모델 PC 설치 소스 갱신과 producer 연결 후보

D-434 모델 PC 배치를 유지하며 공유 발행 수정 `f874e0dbd`와 CRLF 설정 파싱 수정
`b8be9ee73`을 설치용 v3 소스에 포함했다. 이전 archive와 설치 후보는 보존했다.
현재 후보는 비공개 관리자 요청서에 있으며 실제 sudo 설치나 외부 전달은 실행하지 않았다.

## 소스·데이터·설치 단계 검증

기존 묶음은 D-427 이전 `src/` 경로를 담았다. v2는 현행 경로의 881개 파일로
새로 묶어 전체 archive·manifest·추출 파일의 경로/크기/SHA 일치를 확인했다.
Git 내용과는 LF 정규화 후 일치하며 archive 자체의 exact bytes는 manifest로 고정했다.
실제 CPU intake는 고정 평가 126장·mIoU 0.5185248134695789·lane IoU
0.7242653772798793, exit 0·PASS·reasons 없음이었다. snapshot 입력은 보존됐다.

그러나 v2 installer dry-run exit 0에는 store 생성과 writable drop-in이 없었다.
독립 리뷰가 CRLF 예제에서 backend가 `inbox\r`로 읽혀 분기가 생략되는 결함을
발견했다. native parser의 실제 bytes는 수정 전 backend/store 뒤에 CR을 포함했고,
수정 후에는 CR이 없었다. 초기 comment 포함 fixture는 이 결함을 드러내지 못했다.
plain/quoted와 LF/CRLF를 추가한 RED는 2 failed, 4 passed였다.
CR 제거를 quote/comment 파싱 전에 넣은 후 native install/unit suite 23 passed였다.
v2는 설치 승인 후보가 아니며 실패 증거를 보존했다.

수정된 커밋의 v3는 882개 파일로, 전체 경로·크기·해시와 추출 bytes를 실제 모델
PC에서 확인했다. 동일 추출 installer와 원본 CRLF example의 dry-run에서 store
2770 생성, `store.conf`의 `ReadWritePaths=/srv/rosy/store`, timer 비활성 출력을
모두 직접 확인했다. wrapper locate·CPU watch help·dry-run도 exit 0이었다.

실제 v3의 발행·dataset/eval·watcher·install/unit 12개 suite는 150 passed,
0 skipped였다. intake의 runtime 파일 484개는 v2와 v3 간 exact bytes가 같았고,
v2의 이미 종료한 CPU PASS 보고서 SHA를 연결했다. installer만 바뀐 뒤 같은 평가를
불필요하게 다시 실행하지 않았다. 테스트 실행 뒤 source의 모든 선언 파일 SHA도 일치했다.
컴파일 cache를 제외한 source 파일 집합의 정확한 일치를 확인했다.

v3 wrapper는 stage1/data archive/manifest를 고정한다. native verify-only는
5,980개 데이터 파일 확인·system writes 0·timer activation false였다.
일반 사용자 실제 설치 모드는 입력/쓰기 전에 exit 1로 거절했다. 비특권 shim에서
loaded/masked/active/enabled unit 네 경우 모두 exit 1, mutation commands 0이었다.
독립 리뷰는 pins·882개 archive closure·syntax·dry-run 실제 단계와 runtime 비교를 승인했다.

CRLF 수정의 D-436 HOST affected는 294 passed, 10 skipped, 기존 last_verified
경고 19건이었다. 별도 ambient 실행은 WSL bash를 선택해 5 failed/12 passed였으며,
Git Bash·UTF-8 환경의 해당 두 suite는 17 passed였다. native 23 passed와 구분했다.

## producer 후보와 남은 수용

실제 완료된 녹화 job recipe에서 store·trainer gate·trainer replay 위치 세 필드만
서비스 경로로 연결하는 별도 후보를 만들었다. 원본 SHA, 녹화 5개, 라벨·학습 설정,
camera provenance와 producer 자체 intake 출력은 유지했다. v3 `validate_config`는
PASS였으며 config 원본은 바뀌지 않았다. watcher는 별도 canonical 최고 모델 이력으로
최종 평가한다. producer의 선행 평가를 watcher 승격 승인으로 대체하지 않는다.

서비스 store는 아직 없고 service/timer는 not-found/inactive다. 관리자 설치 뒤 그룹
등록과 새 로그인, 실제 producer 접근, 서비스 UID의 신규 READY 처리, systemd sandbox,
서비스 공개 키 등록·doctor·로봇 HOLD 소유자 조율과 shadow/rollback을 검증해야 한다.
후보 config로 재학습하거나 timer를 활성화하지 않았다. 사람 라벨·새 holdout·crosswalk와
roundabout 검증, trusted policy/owner/Fleet·DEVICE/FIELD 수용도 계속 남았다.

비공개 증거: `X:/DevTemp/rosy-learning-audit-20261004/model-watch-source-v3/`,
`model-watch-install-v3/`, `producer-binding-v1/`, `installer-native-parser-proof.json`,
`model-watch-source-v2-intake-result.json`, `model-admin-request.md`.
보고서의 설치 후보 승인과 실제 설치/전체 파이프라인 완료는 서로 다른 상태다.
