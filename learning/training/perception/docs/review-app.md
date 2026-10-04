# Pinky 학습 검수 웹앱

결정은 [D-459](../../../../docs/adr/D-459-pinky-persistent-label-review-application.md)이다. 이 앱은 PC에서 실행하는 영속 객체 라벨 검수 도구다. 로봇·모델 API를 호출하지 않는다.

Python 3.10 이상과 기존 receiver 의존성 `numpy`, `opencv-python`이 필요하다. 서버·SQLite는 Python 표준 라이브러리이며 Node 빌드가 필요하지 않다. 브라우저 자동 검증은 별도 개발 의존성 Playwright/Chromium을 쓴다.

첫 실행은 저장소 루트에서 한다. `--images`는 source JSONL의 상대 image 경로가 시작하는 디렉터리다. 아래 경로는 자신의 저장 위치로 바꾼다. 실험실 PC의 일회성 상태·로그·증거는 X 드라이브에 둔다.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python learning/training/perception/dataset/review_app.py --state X:/DevTemp/pinky-review-state --source <source.jsonl> --human <human.jsonl> --images <image-root> --port 8767
```

브라우저에서 `http://127.0.0.1:8767`를 연다. 종료는 실행 터미널에서 Ctrl+C다. 재실행에는 초기 입력을 반복하지 않는다.

```powershell
python learning/training/perception/dataset/review_app.py --state X:/DevTemp/pinky-review-state --port 8767
```

사진을 선택하고 박스를 그리거나 좌표·클래스·신호를 바꾼다. 유효한 수정은 자동 저장되고 `서버 저장됨 · vN`이 표시된다. 수정한 사진은 검수 대기로 돌아간다. 전체 사진과 모든 박스를 확인한 후 체크하고 승인한다. 제외 사진은 재검수로 돌린 후에만 편집할 수 있다. 신호가 불확실하면 `알 수 없음`을 유지한다.

기존 좌표는 사진 위에 자동으로 박스로 표시된다. 빈 곳에서 드래그하면 새 박스가 생긴다. 기존 박스는 사진에서 누르거나 목록의 `박스 선택`으로 선택한다. 안쪽을 끌면 이동하고, 선택한 박스의 모서리/변 손잡이를 끌면 크기가 바뀐다. 선택 박스 삭제 또는 행 삭제를 누르면 삭제된다. 캔버스에 포커스가 있으면 Delete도 삭제다. 숫자 입력 칸의 Delete는 숫자 편집으로 남는다. 드래그 중 미리보기를 보여주고 놓았을 때만 저장한다. Esc 또는 터치 취소는 저장 없이 원래 상태로 돌아간다. 겹치는 새 박스를 그릴 때는 `박스 그리기`를 누른다. 새 박스는 클래스 선택 전까지 미분류다.

다른 탭이 먼저 저장했다면 그 탭의 내용을 덮어쓰지 않는다. 오류를 읽고 `최신 내용 불러오기`로 복원한 뒤 다시 편집한다. 사진을 불러오지 못하면 승인할 수 없다. 서버 연결이 끊겨 저장에 실패하면 저장됐다고 표시하지 않는다.

`자동·초안 라벨`은 원본의 기존 LiDAR `objects` 또는 모델/시각 `boxes` 후보를 다시 가져온다. 현재 수동 수정을 대체하므로 브라우저 확인을 받는다. 이 동작은 새 모델 추론·자동 기하 job 실행이 아니며 미승인 상태를 만든다. 미분류 후보의 클래스는 사람이 지정해야 한다. 기존 자동 생성은 `autolabel.py`, `prelabel.py` 경로에서 준비한다. 벽·차선·횡단보도는 CVAT와 `edge_review_return.py`의 별도 픽셀 검수 경로를 사용하며 이 앱에는 픽셀 편집기가 없다.

`승인 자료 준비`는 서버에서 기존 `review_return.receive_review`를 호출한다. 수동 다운로드/JSONL 이동 없이 `<state>/exports/<id>`에 원본 크기별 YOLO 객체 라벨, 동결된 source/human 입력, hash manifest와 COMPLETE가 기록된다. 앱 안의 전달 정보에서 경로·승인 장수·제외 index·frame version·HOLD를 확인할 수 있다. 학습 세션은 이 export를 읽어 검증하고 session mapping, session-disjoint 분할, 고정 평가 세트 전체 `build.py --exclude-eval`을 확인한다. export는 학습 dataset 수용·학습 실행·모델 활성화가 아니다.

운영 workspace에서 승인된 원본을 자동 테스트 승인으로 덮어쓰지 않는다. 브라우저 시나리오는 별도 `--state`에서 실행한다. 기본 loopback Host와 쓰기 token/origin 검사는 외부 사이트 요청을 거부하지만 인증된 검수자 신원을 증명하지 않는다. 원격 접근과 서비스 배포는 지원 범위 밖이다. SQLite·동결 원본·exports를 포함한 state 디렉터리가 재시작 정본이다.

테스트:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python -m pytest learning/training/perception/test/test_review_app.py learning/training/perception/test/test_review_return.py learning/training/perception/test/test_object_boxes.py learning/training/perception/test/test_review_pack.py -q -rfE -p no:cacheprovider --basetemp X:/DevTemp/pinky-review-tests | Out-File -Encoding utf8 X:/DevTemp/pinky-review-run.txt
python test/known_failures.py X:/DevTemp/pinky-review-run.txt
```

Windows PowerShell 5의 기본 `>`는 UTF-16을 쓸 수 있어 위처럼 UTF-8 출력으로 남긴다. pytest의 종료 코드와 출력의 실패 요약도 함께 확인한다.

개발용 순수 좌표 기하 시험은 Node 24 이상에서 `node --test learning/training/perception/test/review_box_geometry.test.mjs`로 실행한다. Node는 앱 실행 의존성이 아니다.
### 공통 학습 작업 화면 (D-458)

같은 서버의 `/learning`에서 사진 검수 상태와 기존 학습 도구의 결과를 확인한다.
작업 종류·이름·결과 폴더 전체 경로를 입력하면 SQLite에 연결 목록을 저장한다.
지원 JSON 파일은 종류 선택 시 표시한다. JSONL 다운로드나 수동 파일 이동 없이
최신 결과 확인으로 보고서 상태·단계 실패·파일 변경을 읽는다. 연결 해제는 원본 파일을 지우지 않는다.

Perception 단계 job, Pinky 원본 검증·행동 비교, OMX ACT, 영역 검수 반환,
정책 산출물과 Isaac 환경을 구분한다. 보고서의 선언 상태·SHA와 등록 후 변경 여부만 확인한다.
이 화면은 원본 closure나 승인 receipt를 검증하지 않으며, 학습 시작·정책 승격·로봇 활성화 기능은 없다.
새 결과 버전의 기준을 등록하려면 기존 연결을 해제하고 새 이름으로 연결한다.
### 작업 화면 사용 (D-461)

사진 상태 필터는 이전/다음 이동과 선택 사진에도 적용된다. 필터에 해당하는 사진이 없으면
편집기를 숨기고 전체 사진 보기로 복귀할 수 있다. 저장한 사진의 상태가 필터에서 빠지면
전체 보기로 전환하여 방금 수정한 사진을 유지한다.

`마지막 라벨 수정 되돌리기`는 현재 사진에서 마지막으로 저장한 박스 수정·삭제·초안 적용을
한 번 복구한다. 서버의 현재 version으로 저장하며 승인 상태를 복원하지 않는다.
사진 이동·필터 변경·새로고침·승인·제외 후에는 복구 기억을 비운다. 다른 탭이 먼저 저장하면
409로 거부하고 최신 내용을 불러올 때까지 추가 수정을 막는다.

- `/learning`에서 이름·종류를 검색하고 `확인 필요` 필터로 실패·변경·누락 결과를 찾는다. 검색과 필터는 URL에 유지되어 새로고침 후 복원된다.
- `작업 결과 연결`을 열면 입력으로 이동한다. 결과 파일·진행 단계·연결 해제는 각 작업의 상세 내용을 펼쳐 확인한다. 결과 선언은 학습 수용이나 정책 승격이 아니다.
- 사진 검수에서는 thumbnail, 이전/다음, 다음 검수 대기를 이용한다. `/?filter=pending`으로 대기 사진에 바로 진입할 수 있고 선택 사진은 `frame` URL로 복원된다.
- 박스 제목을 펼쳐 좌표·클래스를 편집한다. 사진 안의 박스를 선택해 이동·크기 변경하거나 빈 곳을 드래그해 새 박스를 그린다. 놓으면 저장되고 Esc·터치 취소는 저장하지 않는다.
- 사진 전체 확인 뒤 명시 승인한다. 박스를 수정하면 재검수 대기가 된다. 객체 승인과 영역 마스크 승인은 별개다.
