# 모델 PC 관리자 데이터 반입 후보 검증

D-434의 모델 PC 배치를 유지하며 소스·오프라인 의존성 설치와 검증된 서비스
데이터 반입을 한 관리자 명령으로 묶었다. 후보는 비공개 경로와 설정을 포함하므로
저장소에는 넣지 않고 별도 요청서와 증거에 보관했다.

후보 SHA256은 비공개 관리자 요청서와 실제 모델 PC 검증 결과에 일치하게 기록했다.
설치 스크립트와 archive/manifest를 고정하고 전체 5,980개 파일 경로·크기·해시를
비교한다. 실제 모델 PC `--verify-only`는 exit 0, system writes 0이었다.
관리자 권한 없이 설치 모드로 실행하면 입력 읽기와 쓰기 전에 exit 1로 거절했다.
서비스와 타이머는 여전히 not-found/inactive다.

첫 후보의 root copy가 service 소유 디렉터리를 따라가면 같은 UID의 symlink 교체로
외부 파일을 덮어쓸 수 있다는 독립 리뷰 결함을 재현했다. 첫 후보는 실행하지 않았다.
수정본은 root 통제 부모와 0700 staging에서 검증된 store를 준비하고 설치기의
빈 skeleton을 rename으로 격리한다. state도 새 root 소유 0700에서 준비한다.
하위 파일부터 권한을 부여하고 루트는 마지막에 열며 store는 root 통제 부모 아래
rename으로 게시한다. 수정본 독립 syntax·격리·게시 순서 검토가 승인됐다.

기존 설치를 보존하고 새 서비스 자체 키를 생성하며 개인 키를 복사하지 않는다.
timer enable, 로봇 전달, HOLD 해제, 주행 명령은 실행하지 않는다.
실제 sudo 설치 및 systemd sandbox 안의 서비스 사용자 접근은 아직 검증되지 않았다.

## 상시 producer 연결의 별도 결함

현재 producer는 사용자 홈의 store를 사용한다. 스냅샷 반입만으로 이후 모델이
watcher에 도달하지 않는다. 실제 Linux 격리 fixture에서 setgid 2770 공유 부모에
발행해도 `Store.put_dataset`은 원본 directory 0700/file 0600을 복사했고,
`handover.package`도 모델과 manifest의 0600을 보존했다. 공유 그룹만으로는
서비스 계정의 읽기 접근을 보장할 수 없다. 실제 데이터와 모델은 변경하지 않았다.

`train_job.publish_ready`는 `copyfile`을 사용하므로 같은 copy2 결함으로
단정하지 않는다. 그 경로도 실제 설정·umask·새 파일 접근을 검증해야 한다.
남은 작업은 producer의 서비스 store 연결, 발행 권한 계약과 신규 READY의 서비스
사용자 읽기/처리 검증, 서비스 공개 키 등록과 doctor, 기존 HOLD 소유자 조율이다.
인간 라벨·새 holdout·정책 owner/Fleet·DEVICE/FIELD 수용도 계속 미완료다.

비공개 증거: `X:/DevTemp/rosy-learning-audit-20261004/admin-install-with-data.py`,
`admin-and-publication-verification.json`, `verify-admin-and-publication.py`,
`model-admin-request.md`. 후보 소스 승인은 실제 설치나 전체 목표 완료가 아니다.

문서 변경의 D-436 affected 선택 12개 시험 파일은 235 passed, 4 skipped,
19 warnings였다. 경고는 기존 last_verified 지연이며 lint는 0 errors였다.
이 HOST 결과는 설치·장치·현장 수용을 대신하지 않는다.
