# Pinky 학습 검수 웹앱

결정은 [D-459](../../../../docs/adr/D-459-pinky-persistent-label-review-application.md)이다. 이 앱은 PC에서 실행하는 영속 객체 라벨 검수 도구다. 로봇·모델 API를 호출하지 않는다.

Python 3.10 이상과 기존 receiver 의존성 `numpy`, `opencv-python`이 필요하다. 서버·SQLite는 Python 표준 라이브러리이며 Node 빌드가 필요하지 않다. 브라우저 자동 검증은 별도 개발 의존성 Playwright/Chromium을 쓴다.

첫 실행은 저장소 루트에서 한다. `--images`는 source JSONL의 상대 image 경로가 시작하는 디렉터리다. 아래 경로는 자신의 저장 위치로 바꾼다. 실험실 PC의 일회성 상태·로그·증거는 X 드라이브에 둔다.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python learning/curation/perception/review_app.py --state X:/DevTemp/pinky-review-state --source <source.jsonl> --human <human.jsonl> --images <image-root> --port 8767
```

브라우저에서 `http://127.0.0.1:8767`를 연다. 종료는 실행 터미널에서 Ctrl+C다. 재실행에는 초기 입력을 반복하지 않는다.

```powershell
python learning/curation/perception/review_app.py --state X:/DevTemp/pinky-review-state --port 8767
```

사진을 선택하고 박스를 그리거나 좌표·클래스·신호를 바꾼다. 유효한 수정은 자동 저장되고 `서버 저장됨 · vN`이 표시된다. 수정한 사진은 검수 대기로 돌아간다. 전체 사진과 모든 박스를 확인한 후 체크하고 승인한다. 제외 사진은 재검수로 돌린 후에만 편집할 수 있다. 신호가 불확실하면 `알 수 없음`을 유지한다.

좌표가 비어 있거나 사진 범위를 벗어나거나 박스의 좌우·상하 순서가 뒤집히면, 저장 전에 한국어 오류를 표시하고 승인을 막는다. 안내에 따라 좌표를 고치거나 새로고침으로 마지막 저장 내용을 다시 불러온다. 좁은 화면의 픽셀 편집 도구는 사진과 현재 결과 바로 아래에 있고, 점·브러시·영역·적용·취소 이름을 함께 표시한다.

D-542 작업대는 사진·현재 결과를 먼저 보여주고 사진 목록·상세 설정은 아래에 둔다. 좁은 화면의 이동·편집 버튼은 아이콘으로 보이며 버튼의 설명과 단축키는 접근성 이름·툴팁·도움말에서 확인할 수 있다. `←`/`→`는 이전/다음 사진, `N`은 다음 대기 사진, `Ctrl+Z`는 객체의 마지막 저장 라벨 수정 또는 픽셀의 마지막 미저장 획부터 되돌린다. 입력칸에서는 이 단축키가 작동하지 않는다. 사진 아래 결과 줄에서 저장 버전·박스 또는 클래스별 픽셀 수·남은 255와 승인 차단 사유를 확인한다. 클래스 색은 바인딩된 클래스셋을 따르며 선택칩의 이름과 번호를 함께 읽는다.

기존 좌표는 사진 위에 자동으로 박스로 표시된다. 빈 곳에서 드래그하면 새 박스가 생긴다. 기존 박스는 사진에서 누르거나 목록의 `박스 선택`으로 선택한다. 안쪽을 끌면 이동하고, 선택한 박스의 모서리/변 손잡이를 끌면 크기가 바뀐다. 선택 박스 삭제 또는 행 삭제를 누르면 삭제된다. 캔버스에 포커스가 있으면 Delete도 삭제다. 숫자 입력 칸의 Delete는 숫자 편집으로 남는다. 드래그 중 미리보기를 보여주고 놓았을 때만 저장한다. Esc 또는 터치 취소는 저장 없이 원래 상태로 돌아간다. 겹치는 새 박스를 그릴 때는 `박스 그리기`를 누른다. 새 박스는 클래스 선택 전까지 미분류다.

다른 탭이 먼저 저장했다면 그 탭의 내용을 덮어쓰지 않는다. 오류를 읽고 `최신 내용 불러오기`로 복원한 뒤 다시 편집한다. 사진을 불러오지 못하면 승인할 수 없다. 서버 연결이 끊겨 저장에 실패하면 저장됐다고 표시하지 않는다.

`자동·초안 라벨`은 원본의 기존 LiDAR `objects` 또는 모델/시각 `boxes` 후보를 다시 가져온다. 현재 수동 수정을 대체하므로 브라우저 확인을 받는다. 이 동작은 새 모델 추론·자동 기하 job 실행이 아니며 미승인 상태를 만든다. 미분류 후보의 클래스는 사람이 지정해야 한다. 기존 자동 생성은 `autolabel.py`, `prelabel.py` 경로에서 준비한다. 벽·차선·횡단보도 등은 `/pixels`에서 별도로 검수하거나 기존 CVAT와 `edge_review_return.py` 경로를 사용한다.

기존 사진과 동일한 영상 해시·프레임·원본 해시의 모델 객체 카탈로그를 `자료 등록`으로 다시 가져오면 박스는 별도 모델 초안으로 보관된다. 객체 검수의 `모델 박스 초안`에서 출처와 개수를 확인하고 명시적으로 가져올 때만 현재 박스를 바꾸며, 결정은 검수 대기로 돌아간다. 픽셀 초안은 별도 후보로 비교·적용한다. 모델 초안 등록과 적용은 승인이나 학습 반영이 아니다.

픽셀 검수의 `255만 초안 보완`은 현재 사람이 저장한 0~254 라벨을 보존하고,
선택한 초안에 실제 클래스가 있는 255 픽셀만 채운다. 미리보기는 합친 결과를 보여 준다.
초안에도 255인 곳은 미검수로 남으며 적용 후 상태는 대기다. `전체 교체`는 현재
마스크를 버리는 별도 동작이다. AI 의견 패널은 픽셀을 채우지 않는다. 승인 전에는
남은 255와 경계를 사람이 확인한다.
사람이 표시한 좌·우 차선 바깥의 새 `drivable` 제안은 255로 남기며,
사람의 주행 라벨과 충돌하는 새 차선 제안도 255로 남긴다.
남은 충돌이나 기존 사람 라벨의 경계 오류는 사람이 확인한다.

SAM 주행 영역 초안이 보이는 좌·우 차선 밖을 침범하면 가져오기가 거절된다. 모델 PC에서 `clip_lane_draft.py --catalog <SAM verified-inputs.jsonl> --classes <v13 classes.yaml> --out <새 폴더>`로 차선 밖 `drivable` 픽셀만 255로 되돌린 새 후보와 receipt를 만든 뒤, 그 폴더를 등록할 수 있다. 이 처리는 차선이 보이는 행에서만 작동하며 255를 배경이나 주행 가능 정답으로 바꾸지 않는다. 사람의 경계 확인과 승인은 여전히 필요하다.

`승인 자료 준비`는 서버에서 기존 `review_return.receive_review`를 호출한다. 수동 다운로드/JSONL 이동 없이 `<state>/exports/<id>`에 원본 크기별 YOLO 객체 라벨, 동결된 source/human 입력, hash manifest와 COMPLETE가 기록된다. 앱 안의 전달 정보에서 경로·승인 장수·제외 index·frame version·HOLD를 확인할 수 있다. 학습 세션은 이 export를 읽어 검증하고 session mapping, session-disjoint 분할, 고정 평가 세트 전체 `build.py --exclude-eval`을 확인한다. export는 학습 dataset 수용·학습 실행·모델 활성화가 아니다.

운영 workspace에서 승인된 원본을 자동 테스트 승인으로 덮어쓰지 않는다. 브라우저 시나리오는 별도 `--state`에서 실행한다. 기본 loopback Host와 쓰기 token/origin 검사는 외부 사이트 요청을 거부하지만 인증된 검수자 신원을 증명하지 않는다. 서비스 배포는 지원 범위 밖이다. 원격 접근은 아래 `--host`로만 연다. SQLite·동결 원본·exports를 포함한 state 디렉터리가 재시작 정본이다.

### 신뢰 망에서 직접 열기 (D-478)

기본은 loopback이다. 검수자가 SSH 터널 없이 모델 PC의 앱을 Tailscale로 열어야 할 때만 `--host`로 그 주소를 지정한다.

```powershell
python learning/curation/perception/review_app.py --state X:/DevTemp/pinky-review-state --port 8768 --host <model-pc>
```

검수자는 `http://<model-pc>:8768/pixels`를 연다. 받는 값은 loopback·사설(RFC1918)·link-local·Tailscale(100.64.0.0/10) 리터럴 IPv4뿐이다. `0.0.0.0`, 공인 주소, 호스트 이름은 시작 때 거부된다. HTTP만 쓰며 tailnet 구간은 이미 암호화된다.

위험: 사용자 인증이 없다. 그 주소에 닿는 누구나 사진을 보고 수정하고 승인할 수 있고, 검수자 신원은 증명되지 않는다. 신뢰한 tailnet/LAN에서 필요한 동안만 켠다. 쓰기 token과 Host/Origin 검사는 그대로다.

테스트:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python -m pytest test/learning/perception/test_review_app.py test/learning/perception/test_review_return.py test/learning/perception/test_object_boxes.py test/learning/perception/test_review_pack.py -q -rfE -p no:cacheprovider --basetemp X:/DevTemp/pinky-review-tests | Out-File -Encoding utf8 X:/DevTemp/pinky-review-run.txt
python test/known_failures.py X:/DevTemp/pinky-review-run.txt
```

Windows PowerShell 5의 기본 `>`는 UTF-16을 쓸 수 있어 위처럼 UTF-8 출력으로 남긴다. pytest의 종료 코드와 출력의 실패 요약도 함께 확인한다.

개발용 순수 좌표 기하 시험은 Node 24 이상에서 `node --test test/learning/perception/review_box_geometry.test.mjs`로 실행한다. Node는 앱 실행 의존성이 아니다.
### 다섯 단계 메뉴 (D-857)

모든 화면의 왼쪽 레일(전화에서는 위 한 줄)은 학습 루프의 단계다: **홈** `/learning` · **자료** `/catalog` · **정답** `/` · **학습** `/learning/tasks` · **평가·승격** `/learning/evaluate`. 화면이 여럿인 단계는 레일 옆(전화에서는 그 아래 한 줄)에 공용 하위 메뉴(`ui-subnav`)를 보인다. 모든 기존 화면은 레일 한 번과 하위 메뉴 한 번 안에 닿고, 기존 URL은 그대로다. 자료 칸의 접근 이름은 기능 검색이 찾는 「자료 등록」이다. 레일 칸은 지금 화면 자체일 때만 `aria-current="page"`이고, 지금 화면을 품은 단계일 때는 `aria-current="true"`다. 전화에서 하위 메뉴 줄은 위아래 여백 없이 48px 누름 칸만 차지한다. 도메인(차로·객체·OMX·SIM·VLM·판단 모델)은 메뉴가 아니라 `?domain=` 필터다(값 `lane`·`object`·`omx`·`sim`·`vlm`·`decision`). 여러 도메인을 나열하는 홈과 평가·승격만 이 값을 따른다.

| 단계 | 화면 |
|---|---|
| 홈 | 학습센터 `/learning`: 도메인별 진행, 현재 인식 자료의 학습 흐름, 현재 검수 작업, 실행·평가 결과, 수집·저장 공간 |
| 자료 | 자료 등록 `/catalog`, 카메라 맞춤 `/learning/camera` |
| 정답 | 객체 검수 `/`, 픽셀 검수 `/pixels`, 로봇암 시범 검수 `/learning/omx`, VLM 판단 `/learning/vlm` |
| 학습 | 학습 과제 `/learning/tasks`, 인식 학습 `/learning#pipeline`(홈의 학습 흐름 구역), SIM 실험 `/learning/sim` |
| 평가·승격 | `/learning/evaluate`: 지금 있는 평가 근거를 읽기 전용으로 모은다(학습 흐름의 평가 단계, VLM 모델 대 확정 정답). 승격 승인·배포는 Fleet에서 사람이 한다(D-793). `승격 요청`은 다음 조각까지 비활성이다 |

로그인·계정과 Hugging Face 가져오기는 메뉴가 아니라 상단 막대의 「로그인·계정」 `/accounts`에 있다. 수집·저장 공간은 아직 홈의 구역이다. 로봇암 화면(`/learning/omx`)은 시범 검수 밖에 학습·비교 구역도 품지만 한 화면이라 정답 단계에 둔다. 인식 학습은 별도 화면 없이 홈의 학습 흐름 구역으로 간다.

**홈의 도메인 줄.** `/api/learning`은 기존 키를 그대로 두고 `domains`와 `vlm_eval_url`을 더한다(`learning_domains.py`). 도메인마다 루프 여섯 칸(수집·정답·데이터셋·학습·평가·승격 기록, ⑦ 배포는 Learning 밖이라 없음)을 `{stage, label, state, evidence, next}`로 주고, `state`는 `done`·`active`·`blocked`·`waiting`·`not_available`이다. 도메인마다 `next`(`{label, href}` 하나)와 `blocked`(처음 막히거나 없는 칸의 이유)가 있다. 이 작업대가 이미 가진 자료만 읽는다.

| 도메인 | 근거 |
|---|---|
| `lane` | 기존 `project()` 단계를 여섯 칸에 맞춘다(자료→수집, 픽셀 검수→정답, 준비+데이터셋→데이터셋, 학습, 평가, 적용 검토→승격 기록) |
| `object` | 객체 승인·대기·제외 수와 최신 준비본(`exports`). 학습·평가는 학습기가 없어 `not_available` |
| `omx` | `learning_links`의 OMX 결과 폴더와 `omx_segment_reviews`가 있는 폴더 수. 학습 칸은 학습 과제 화면의 OMX 과제 수(`learning_task_records`의 `task` 중 `adapter`가 `omx`) |
| `sim` | `--sim-config`가 없으면 `not_available`. 있으면 실험 목록의 수와 최근 상태(홈은 1분에 한 번만 읽는다) |
| `vlm` | VLM 표가 있을 때 사진·확정·제외·임시 정답 수. 확정이 1장 이상이면 평가 칸이 열린다 |
| `decision` | 모두 `not_available`(「Learning에 연결 전」) |

모르는 칸은 숫자를 만들지 않고 이유를 적은 `not_available`이다. 표를 만들지 않고 읽으므로 홈을 열어도 VLM·OMX 표가 생기지 않는다. 홈은 도메인마다 한 줄(이름, 여섯 칸, 막힌 이유, 다음 할 일 하나)을 보이고 평가·승격 화면은 같은 `domains`의 평가·승격 기록 칸을 도메인별로 보인다. 390px에서는 줄이 세로로 쌓이고 가로 스크롤이 없다.

### 공통 학습 작업 화면 (D-458)

같은 서버의 `/learning`에서 사진 검수 상태와 기존 학습 도구의 결과를 확인한다.
객체·픽셀 검수 건수와 각 대기 목록은 따로 표시한다. 객체 사진에서 픽셀 검수로 이동하면 같은 사진을 연다.
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
- 승인 또는 제외로 사진을 마치면 다음 검수 대기 사진이 바로 열린다. `검수 대기` 필터는 유지되고, 수정 상태 줄에 방금 결정한 사진 번호가 남는다. 대기 사진이 없으면 그 사진에 머물며 `검수 대기 사진을 모두 처리했습니다`를 표시한다. 픽셀 검수도 같으며, 객체 제외로 픽셀을 편집할 수 없는 사진은 건너뛰고 고른 칠하기 클래스는 유지한다. `승인`·`제외` 필터에서 점검하며 결정하면 넘어가지 않고 그 사진을 전체 보기로 남긴다. 전체 확인 체크는 사진마다 다시 해야 한다.
- 폭이 좁은 화면(64rem 미만)에서는 사진 목록이 가로로 넘기는 한 줄이 되어 편집기가 첫 화면에 보이고, 열린 사진이 줄 안에 보이도록 이동한다.
- 사진 검수에서는 thumbnail, 이전/다음, 다음 검수 대기를 이용한다. `/?filter=pending`으로 대기 사진에 바로 진입할 수 있고 선택 사진은 `frame` URL로 복원된다.
- 객체 검수와 픽셀 검수 모두 캔버스에 포커스가 있을 때 ←·→로 이전·다음 사진을 이동한다. 숫자 입력 칸 안에서는 값 조절로 남고 이동하지 않는다. 저장 중·충돌·초안이 남은 상태에서는 이동하지 않는다.
- 픽셀 검수는 점 선택이 기본이고, 차선 클래스가 있으면 처음에 선택한다. 점 선택 중에는 브러시 커서를 숨기며, 브러시로 바꾸면 반지름을 원형으로 보여준다. 검수자가 고른 클래스는 사진 간 유지한다.
- 박스 제목을 펼쳐 좌표·클래스를 편집한다. 사진 안의 박스를 선택해 이동·크기 변경하거나 빈 곳을 드래그해 새 박스를 그린다. 놓으면 저장되고 Esc·터치 취소는 저장하지 않는다.
- 사진 전체 확인 뒤 명시 승인한다. 박스를 수정하면 재검수 대기가 된다. 객체 승인과 영역 마스크 승인은 별개다.

### 다중 영상·픽셀·최신 결정 계약 (D-462)

서버 재시작에 `--catalog <검증 입력 폴더> --cad-catalog <map-coordinate-evidence.json>`을
추가하면 `/catalog`의 등록 경로가 미리 채워진다. `verified-inputs.jsonl`의 이미지 SHA·크기와
초안 ZIP/labelmap SHA를 실제 바이트로 검증한다. 선언된 영상 SHA+video_frame이 같은 표현은
하나의 사진으로 묶되 primary 이미지와 기존 결정을 바꾸지 않는다. 표현별 provenance를 보존한다.
원본 MP4의 실제 해시 검증은 이 등록이 대신하지 않는다. 새 객체와 마스크는 항상 pending이다.

`/pixels`는 원본 크기 index PNG를 저장한다. 기본 배경·전체 사진 확인을 각각 체크하고
미검수 index255가 없어야 픽셀 승인할 수 있다. 점 1~32개로 사진의 Lab 색을 샘플링해
4방향 연결 영역을 미리 보고, `선택 영역 적용`을 누를 때만 마스크에 저장한다. 자동 허용치는
점 주변의 Lab 거리에서 제안하며 직접 입력은 0~100이다. 미리보기는 승인도 저장도 하지 않는다.
`POST /api/mask-preview/<index>`는 현재 mask version·class·seeds·tolerance를 검증하고
indexed PNG(base64), 선택 픽셀 수, 실제 허용치를 반환한다. 적용은 기존
`POST /api/masks/<index>`의 `sample` 동작으로 재계산하며 version 충돌을 거부한다.
브러시·지우기·전체 채움·한 번 되돌리기도 제공하며 수정 후 pending이다. 색 범례는 공용 UI 토큰이고 데이터의 클래스 RGB는
classes.yaml을 그대로 보존한다. crosswalk5(role ignore)와 미검수255는 별개다.
객체 제외 사진은 픽셀 수정을 막고 mask export에서도 제외한다. 고정 평가 중첩은 승인하지 않는다.

CAD 등록은 여섯 파일의 SHA/크기와 lane_graph.source_sha256↔CAD를 확인한다.
촬영 지도 revision·동기화 pose·intrinsics/extrinsics는 미검증이다. CAD 투영 생성/승인은 없다.
stop_line/crosswalk train/val 픽셀0은 2026-10-04 기존 학습 catalog snapshot의 사실이며
새 등록 자료나 실시간 coverage 측정이라고 해석하지 않는다.

`GET /api/decisions`는 한 SQLite 읽기 트랜잭션으로 모든 프레임과 workspace_id/generation,
객체·픽셀 decision/version, primary image SHA/크기, representations digest, exact class SHA와
정규화 classes_signature, ignore_index, 승인 image/mask/classes/전체·배경 확인 binding을 읽는다.
`decision_sha256`는 자신을 제외한 객체의 정렬 JSON(ensure_ascii=False, 줄바꿈 포함) SHA다.
객체/mask/import/CAD/class binding 변경은 generation을 올린다.
ETag는 따옴표로 감싼 decision_sha256이며 If-None-Match가 같으면 304를 반환한다.
frame_excluded는 사진 전체 제외 tombstone이고 객체 제외 동작과 함께 true가 된다.
object_review_sha256는 video/video_frame을 원본과 맞춘 export human row의 encoded JSON SHA이며,
source_sha256는 전체 frozen source row의 encoded JSON SHA다. 같은 revision의 박스 내용 변조도
현재 authority와 비교해 거부한다. int와 bool 승인 필드는 타입까지 확인한다.
기존 사진과 exact primary image SHA·선언 영상명/frame이 모두 같은 등록은 기존 review/version을
유지하며 출처만 보강한다. legacy_source에 이전 source 전체를 남기고 primary image를 바꾸지 않는다.
영상명만 같은 경우나 같은 픽셀을 서로 다른 촬영 세션에서 발견한 경우에는 합치지 않는다.

`POST /api/prepare`는 같은 snapshot으로 기존 객체 COMPLETE/manifest와
review-contract.json(schema rosy.pinky-review-export/2), AUTHORITY_COMPLETE를 동결한다.
후자는 contract SHA를 담아 마지막으로 쓴다. indexed mask 원본 바이트와 승인 SHA는 같아야 한다.
pixel-reviews.jsonl, pixel-classes.yaml, application-snapshot.json, representations.json,
원본 image/source/human, 기존 receiver 파일을 모두 sealed files에 포함한다.

소비자는 구성된 live `/api/decisions`를 새로 읽고 workspace identity·단조 revision을 확인한
뒤 `review_evidence.verify_current(export, current)`로 비교한다. 저장된 과거 current를 넘기는
것은 최신성 검증이 아니다. helper는 schema/digest/identity·정확한 approval·필수 파일·안전한
경로/비symlink·바이트/클래스/수량 binding을 검사하고 최신 수정·철회와 다른 export를 거부한다.
원본 객체 COMPLETE만으로 새로운 학습 자격을 부여하지 않는다.

indexed PNG는 기존 RGB CVAT builder의 직접 입력이 아니다. 학습 루트가 RGB/labelmap 변환,
정확한 signature·approval binding, 모든 고정 평가 세션 제외 및 독립 integration을 소유한다.
이 앱은 training_dataset_qualified=false를 유지한다. 실제 사용자 픽셀 승인·훈련·모델 활성화는
브라우저 테스트 상태의 합성 승인과 별개다.

### 이미지 재검증 캐싱 (D-469)

`GET /api/images/<index>`와 `GET /api/mask-images/<index>`는 `Cache-Control: no-cache`와
ETag(원본은 `image_sha256`, 마스크는 인코딩된 PNG 바이트 sha256)로 응답한다. `If-None-Match`가
일치하면 304로 본문을 보내지 않는다. 서버는 매 요청마다 디스크 바이트를 읽어 hash를 검증하므로
변조된 파일은 일치하는 ETag로도 거부된다. 재검증은 전송만 줄이고 검사를 건너뛰지 않는다.
나머지 응답은 기존 `no-store`를 유지한다. 화면은 이 재검증에 맞춰 사진 목록 구성원이 그대로면
thumbnail을 다시 만들지 않고, 픽셀 검수의 마스크 오버레이 채색을 마스크 version·불투명도·테마가
바뀔 때만 다시 계산한다. 서버 검증 오류는 화면에서 한국어 안내로 바꿔 보여주며, 미분류 박스가
있으면 승인을 화면에서 먼저 막는다. 서버 검증은 그대로 최종 방어다.

### 모든 화면의 키보드 기능 검색

`Ctrl+K`(Mac은 `Command+K`)에서 버튼·링크·입력·접힌 항목·캔버스·AI 참고 의견을 이름으로 찾는다. ↑/↓로 선택하고 Enter로 실행하거나 해당 필드에 포커스를 준다. Esc는 검색만 닫고 원래 포커스를 돌려준다. 초안 미리보기·255 보완·전체 교체·확인 체크·재검수·승인 자료 준비도 원래 버튼의 비활성 조건과 확인을 그대로 거친다. 숫자/문자 입력은 선택한 필드에서 편집하고 Tab으로 확정한다.

`R` 최신 내용, `U` 재검수, `E` 승인 자료 준비, 객체 `Insert` 좌표 박스 추가, 픽셀 `Ctrl+S` 초안 저장을 추가로 지원한다. 기존 `1–9`, `C/B/A/X`, `N`, `V`, `T/P`, Enter, Ctrl+Z, Delete, `+/-/0/H`, `?`는 유지한다. 입력 칸·IME 조합 중에는 작업 키를 실행하지 않으며 기능 검색 키만 명시적으로 열 수 있다.

픽셀 캔버스에 포커스를 준 뒤 `Alt+방향키`로 원본 좌표 1픽셀, `Alt+Shift+방향키`로 10픽셀 이동한다. 십자선과 `(x,y)`·원본 크기는 검수용 표시다. 점/영역 도구는 Space로 점/꼭짓점을 추가하고 Enter로 적용한다. 브러시는 Space를 누른 상태에서 이동하고 놓아 한 획을 끝낸 다음 Ctrl+S로 저장한다. Esc나 그리는 중 포커스 이탈은 진행 획을 버린다. `H` 이동 모드에서는 Alt+방향키로 보기만 이동하며 칠하지 않는다. 객체 박스는 Insert와 좌표·클래스 필드를 기능 검색으로 골라 마우스 없이 추가·수정할 수 있다.

AI 보조의 현재 기능과 후속 방법, 의미/현재성 제한은 [AI 검수 보조 조사](ai-review-assistance.md)를 참고한다. 이 설명과 키보드 기능은 새 추론·학습 작업을 실행하거나 사람 승인을 대신하지 않는다.

### 검수 기록

객체·픽셀 검수 화면의 「이 사진의 검수 기록」은 `GET /api/history/<index>`를 읽는다.
응답은 원본 `annotation_source`, 현재 객체·픽셀 상태와 각각 최근 20건의 `ts/action/version`만 담는다.
`import`는 가져온 상태이며 검수자 신원 증거가 아니다. 앱의 승인·제외·재검수 이벤트도
조작 종류만 기록하고 사람 이름이나 계정을 기록하지 않는다. AI 초안과 사람의 최종 승인을
동일한 기록으로 취급하지 않으며, 이전 결정을 바꾸려면 해당 화면의 재검수 동작을 사용한다.

### 밝은 사진의 검수용 보기

객체·픽셀 화면의 「명암 보정」(`V`)은 `GET /api/view-images/<index>`에서 원본 해시와
크기를 재검증한 뒤 OpenCV로 명도 감마·국소 선명도를 조절한 PNG를 **화면에만** 그린다.
픽셀 화면은 `M`으로 마스크를 숨기고 바로 옆에서 겹침 강도를 조절한다. 좌표, 색상 점 선택,
승인 바인딩, 학습 export는 언제나 원본 사진과 원래 마스크를 사용한다. 보정 보기에서
흰색으로 포화된 원본 정보는 복원되지 않는다. 경계를 여전히 판단할 수 없으면 검수 대기로
두고 노출을 조절해 새로 촬영한 원본을 별도 자료로 등록한다.

과노출 후보는 원본 사진의 하단 절반에서 회색조 245 이상인 픽셀 비율로 확인한다.
`review_quality.py`는 결정 기록을 바꾸지 않고 후보만 보고한다. 과노출이어도 원본에서
정답을 판단할 수 있으면 검수 대기로 남긴다. 일부 영역만 판단하기 어려우면 그 픽셀을
255(미검수)로 두고, 사진 전체의 정답을 판단할 수 없을 때만 검수 화면에서 사람이 제외한다.
255가 남은 마스크는 학습용 픽셀 승인을 할 수 없다(D-464).
0.15는 2026-10-08 v13 촬영분에서 측정한 분리값이므로 다른 촬영분에 그대로 적용하지 않는다.
정규분포 가정이나 흐림 필터는 쓰지 않는다.

```powershell
python learning/curation/perception/review_quality.py --state X:/DevTemp/<name>/state --threshold 0.15 > X:/DevTemp/<name>/exposure-preview.json
```

모델 PC에서 로컬 Qwen 영상 모델의 **참고 의견**을 만들려면 다음을 실행한다.
원본 사진·현재 indexed mask의 SHA를 검증하고 255 픽셀 수와 프레임별 시각 의견을
새 보고서 폴더에 기록한다. 전체 실행이 끝나고 검수 결정 세대가 유지됐을 때만
`<state>/vlm-feedback.json`을 갱신한다. `/pixels`는 해당 사진의 원본·마스크 SHA가
보고서와 같을 때만 최신 의견으로 표시한다. 다른 사진의 변경은 이미 검사한 사진의
의견을 숨기지 않으며, 해당 마스크가 바뀌면 오래된 의견으로 표시한다.

```bash
python learning/curation/perception/vlm_mask_feedback.py \
  --state <review-state> --out <new-report-directory>
```

Ollama `qwen3-vl:8b-instruct`는 모델 PC의 `127.0.0.1:11434`에서만 사용한다.
`--limit N`은 시험용 부분 보고서이며 앱에 게시하지 않는다. AI는 승인·제외·학습 자격을
바꾸지 않는다. `no_obvious_concern`도 검수 완료가 아니다. 255가 남으면 사람 픽셀
승인이 거절되며, VLM이 판단을 보류하거나 잘못 읽을 수 있으므로 원본을 직접 확인한다.

### 클래스셋 (D-485)

객체 클래스는 첫 실행의 `--object-classes <data.yaml>`로 정한다. 파일은 Ultralytics `data.yaml`의 `names`(목록 또는 번호 사전)를 읽고, 선택 항목 `display`(이름별 표시 문구)와 `colors`(이름별 `[r, g, b]`)를 받는다. 생략하면 D-423의 기본 6개 클래스다. 한 작업 공간은 객체 클래스셋 하나와 픽셀 클래스셋 하나에 묶인다. 다른 모델의 클래스로 검수하려면 다른 `--state`로 새 작업 공간을 만든다.

```powershell
python learning/curation/perception/review_app.py --state X:/DevTemp/<name>/state --source <source.jsonl> --human <human.jsonl> --images <image-root> --object-classes <data.yaml> --port 8767
```

픽셀 `classes.yaml`은 항목마다 선택 항목 `display`를 둘 수 있다. 차선 모델(왼쪽/오른쪽 차선, 횡단보도, 과속방지턱)용 파일은 `learning/curation/perception/classes/lane_lr5.yaml`이다. `/catalog`의 「클래스 파일 경로 (classes.yaml)」 칸에 이 파일 경로를 넣는다. 이 칸은 `/api/import` 요청 본문의 `classes`로 간다. 칸을 비우면 초안 마스크 zip 옆이나 카탈로그 옆의 `classes.yaml`을 쓴다. 초안 마스크가 없는 카탈로그도 작업 공간에 아직 픽셀 클래스가 없으면 카탈로그 옆 `classes.yaml`로 묶는다. 이미 픽셀 클래스가 묶인 작업 공간에서는 빈 칸이 기존 클래스를 그대로 쓴다. 초안 마스크는 같은 클래스셋으로 만든 것만 가져올 수 있다. labelmap 이름이나 indexed 초안의 classes sha가 묶을 클래스셋과 다르면 등록 전체를 거부하고, 화면은 「초안 마스크가 다른 클래스셋으로 만들어졌습니다」라고 알린다. 이때는 초안 없이 가져오거나 초안과 같은 `classes.yaml`을 지정한다.

주행 가능 영역을 검수할 때는 `learning/curation/perception/classes/lane_lr6_drivable.yaml`을 **새 `--state` 작업 공간**의 `/api/import` `classes`로 지정한다. 기존 0~4번은 그대로이고 5번 `drivable`이 추가된다. v12 작업 공간에 이 파일을 다시 바인딩하면 마스크의 뜻을 바꾸게 되므로 서버가 거절한다. 새 작업 공간에는 원본 검증 카탈로그를 다시 가져오고, 기존 픽셀 승인이나 초안을 승인 상태로 복사하지 않는다. 새 마스크는 검수 대기에서 시작하며 저장·전체 확인·픽셀 승인을 거쳐야 학습 입력으로 내보낼 수 있다. `drivable`은 D-475의 화면에 보이는 흰 경계선 안쪽 도로 바닥 전체이며, 차선 칠·도로 밖 바닥·장애물에 가린 화소와 구분한다. 기존 5채널 모델의 클래스 순서를 그대로 둔 채 6클래스 정답으로 학습하거나 승격하지 않는다.

모델 PC에서 `.pt`의 클래스 이름을 `data.yaml`로 뽑는다. 검수 앱은 모델을 열지 않는다.

```powershell
python learning/registry/perception/export_class_names.py best.pt --out data.yaml
```

클래스셋 sha(`object_class_set_sha256`)는 `review-contract.json`과 `/api/workspace`에 있고 `/api/decisions`에는 없다.

단축키 (입력 칸에 포커스가 없을 때, 한글 입력 상태에서도 같은 키):

| 키 | 동작 |
|---|---|
| `1`-`9` | 클래스 선택 (선택한 박스에 지정) |
| `A` | 승인 (전체 확인 체크 후에만, 픽셀 검수는 기본 배경 확인 체크도 필요) |
| `X` | 제외 (검수 대기 사진만) |
| `←` / `→` | 이전 / 다음 사진 |


### 공동 계정과 Hugging Face 가져오기 (D-755)

`--collaboration <private-config.json>`은 기존 검수 작업공간에 Rosy Account 로그인과 프로젝트 권한을 적용한다. 사람의 로그인은 모든 앱과 같은 Rosy Account 하나뿐이며(D-757), 이 앱은 자체 아이디·비밀번호나 HF 로그인을 받지 않는다. `/accounts`에서 Rosy Account 로그인, 개인별 복수 HF 연결, 계정 선택, dataset/model 가져오기와 같은 고정 버전 재시도를 수행한다. 기존 단일 사용자 이력은 신원 미확인으로 남는다. 협업 모드의 새 객체·픽셀 이벤트는 인증된 사용자와 revision을 기록하며 요청 본문에 적은 검수자 이름은 신원으로 쓰지 않는다.

중앙 Account 모드의 세션·PKCE·HF 쿠키 이름은 설정의 프로젝트와 공개 HTTPS origin별로 구분한다. 같은 DNS 이름의 다른 포트에서도 서로 덮어쓰지 않는다. 기존 고정 이름의 중앙 앱 쿠키는 읽지 않으므로 업데이트 후 한 번 다시 로그인한다. 관리 설치기는 `state/learning-collaboration.json`을 코드 업데이트와 지원되는 보관 릴리스 전환에서 유지하며, loopback·HTTPS 프록시와 무인증 decisions-port 제외를 요구한다. 서비스별 설치 방법은 [Model PC 배포 설명](../../../../deploy/model_pc/README.md#account-프로젝트별-설치-d-757)을 따른다.

설정 예제는 [`learning-collaboration.example.json`](../learning-collaboration.example.json)이다. 실제 설정·DB·키·OAuth 비밀·가져온 자료는 Git 밖의 private 경로에 둔다. `account_client_file`이 없는 설정은 시작을 거절한다. 모델 PC의 검수 앱 환경에서 다음을 준비한다.

```bash
python -m pip install -r learning/curation/perception/requirements-collaboration.txt
python learning/curation/perception/learning_accounts.py generate-key /private/learning/learning-accounts.key
```

저장소 루트에서 `python -m pip install ./contracts/foundation`도 설치한다. collaboration 설정의
`account_client_file`은 보호된 수신 설정의 절대 경로다. 새 사용자는 Rosy Account 계정 관리(`/console/accounts`)에서
이 프로젝트의 `learning.*` 권한을 받으면 바로 들어온다. 학습 앱에 따로 초대하지 않는다. `account_subjects`는
기존 학습 user_id의 HF 연결을 이어받을 중앙 account_id와의 선택적 일대일 매핑이며, 매핑 없이 기존 user_id와 같은
account_id는 거절한다. 학습 권한 없이 로그인한 사용자는 로그인 화면으로 되돌리지 않고 권한 요청 안내를 본다.
수신 resource는 `project:<project_id>`, callback은 `public_origin + /api/account/callback`이다.
원장에 최초 연결을 기록한 뒤 소유자를 바꾸거나 중앙 설정을 빼고 이전 비밀번호로 돌아갈 수 없다.
기존 HF 연결·암호화 키·학습 자료를 교체하지 않는다. 자세한 필드는
[Account protocol](../../../../docs/reference/rosy-account-protocol.md)을 따른다.

키 생성은 기존 파일을 덮어쓰지 않는다. Linux 키 파일, 설정, DB, 부모 폴더와 백업은 소유자만 접근하도록 관리한다. 암호화 키는 DB와 함께 복구할 수 있도록 별도로 보관한다. 키 파일 교체만으로 기존 연결 비밀이 이전되지는 않는다.

권한은 Rosy Account 원장의 `project:<project_id>` 자원에 부여한 `learning.view`, `learning.edit`, `learning.approve`, `learning.import`, `learning.manage`, `learning.publish`다. 열람, 라벨 수정, 승인, 자료 가져오기, 프로젝트 연결·학습 제어 관리, 외부 게시를 각각 허용한다. `users`는 기존 학습 신원의 연결 보존용이며 비워 둘 수 있다. 이메일로 계정을 합치지 않는다. 계정 DB는 여러 프로젝트에서 공유할 수 있지만 앱 설정과 작업공간은 `project_id` 하나에 고정한다. 첫 연결 시 DB의 프로젝트 바인딩이 남고 다른 프로젝트로 바꿀 수 없다. 사용자 제거나 membership 변경은 다음 요청과 worker 체크포인트에서 재검사한다.

개인 연결은 소유자 작업에만 사용한다. 프로젝트 연결에는 `manage` 권한과 `dataset:namespace/repo` 또는 `model:namespace/repo` 형식의 자원 허용 목록이 필요하다. 프로젝트 관리자 권한은 호스트 파일시스템 관리자 권한이 아니다. 협업 HTTP에서 임의 서버 경로를 받는 기존 `/api/import`, `/api/cad`, `/api/learning/register`는 사용할 수 없다.

운영 앱은 HTTPS reverse proxy 뒤의 loopback에 바인딩한다. `public_origin`은 경로와 끝 슬래시 없는 정확한 HTTPS origin이다. 프록시는 공개 Host를 보존하여 `127.0.0.1:<review-port>`로 전달하고 외부에서 backend에 직접 접근하게 만들지 않는다. Host·Origin과 `Secure; HttpOnly; SameSite=Lax` 쿠키를 함께 사용한다. 프록시 로그에도 callback code/state와 요청 본문을 기록하지 않는다.

```bash
python learning/curation/perception/review_app.py \
  --state /private/learning/review-state --host 127.0.0.1 --port 8767 \
  --collaboration /private/learning/learning-collaboration.json
```

위 예는 초기화된 작업공간이다. 신규 작업공간은 기존 초기화 인자 또는 `--empty-training`을 사용한다. 협업 모드에서 `--decisions-port`는 인증 없는 우회 경로라 함께 사용할 수 없다. 기존 자동화가 그 포트를 쓴다면 인증된 소비 경로를 마련하기 전까지 운영 협업 전환을 활성화하지 않는다.

HF OAuth는 등록된 앱과 실제 HTTPS callback이 있어야 한다. 준비되지 않았으면 `oauth: null`을 유지한다. Rosy Account 로그인 후 제한된 HF 읽기 토큰을 데이터 연결로 등록할 수 있다. HF OAuth와 PAT는 데이터 연결 수단이며 로그인 수단이 아니다. OAuth를 구성할 때 private 설정의 `oauth`를 다음 모양으로 바꾼다.

```json
{
  "client_id": "<registered-client-id>",
  "redirect_uri": "https://review.example.invalid/oauth/huggingface/callback",
  "client_secret_file": "/private/learning/hf-client-secret"
}
```

실제 origin과 provider에 등록한 URI가 정확히 일치해야 한다. 공개 클라이언트로 등록한 경우에만 `client_secret_file`을 생략한다. HF 연결은 로그인한 사용자가 명시적으로 시작한 경우만 허용한다. 자료 연결은 `openid profile read-repos gated-repos`를 요청한다. 저장소 관리 연결은 `read-repos write-repos manage-repos`를 요청하고, 쓰기와 저장소 관리가 모두 있을 때만 저장한다. 요청하지 않은 범위는 저장하지 않는다. PKCE·state·nonce·issuer·audience·서명·만료를 검증한다. 서버는 토큰을 암호화하며 전역 `HF_TOKEN`이나 CLI 로그인 계정을 바꾸지 않는다. offline refresh를 요청하지 않으므로 만료되면 명시적으로 다시 연결한다.

가져오기는 branch/tag를 최초 요청에서 immutable commit으로 고정한다. 재시도도 같은 commit과 계정 세대를 유지하며 다른 계정으로 자동 대체하지 않는다. gated 개인 접근 승인은 팀 이용 허가가 아니므로 팀 이용 근거가 없으면 `rights_hold`다. 크기·경로·해시 검증 후 원자적으로 등록하며 중간 파일을 완료 자료로 노출하지 않는다. 다운로드한 Python 코드·pickle·모델 코드를 실행하지 않는다.

계정 화면에서 작업·파일별 받은 bytes와 해시 검증 상태, 공간 부족·검증 실패·접근 철회 이유를 확인한다. 취소 직후 재시도는 이전 실행이 끝난 뒤 같은 입력으로 이어진다. 새로고침은 펼친 파일 목록과 키보드 초점을 유지한다. 실행 프로세스가 종료되면 OS 잠금이 풀리며 다음 목록 조회·재시도가 중단 작업을 복구한다. 계정 세대가 바뀌면 과거 작업을 새 연결로 재사용하지 않는다.

부분 재개는 최초 HF metadata의 SHA-256이 있는 파일에만 허용한다. 로컬 체크포인트는 최대 8MiB 또는 1초마다 flush/fsync 후 저장하며, 강제 종료가 남긴 미확정 tail은 마지막 정상 해시 구간 뒤에서 버린다. provider가 Range를 무시한 200 응답은 덧붙이지 않는다. 206의 시작 offset·끝·전체 길이와 인코딩을 검사하고 마지막에 전체 SHA-256을 검증한다. 해시가 없는 미완료 파일은 처음부터 다시 받는다. 완료 파일은 기록된 전체 해시를 다시 검증해 재사용한다. [HF 파일 식별](https://huggingface.co/docs/huggingface_hub/en/package_reference/file_download), [HTTP Range 의미](https://www.rfc-editor.org/rfc/rfc9110.html#name-range)를 따른다.

private 협업 설정의 `import_limits`는 `max_file_bytes`, `max_total_bytes`, `reserve_bytes` 정수 bytes다. 기본은 파일당 2GiB·작업당 8GiB·여유 1GiB, 파일 수는 최대 256개다. 파일 한도는 양수이며 작업 한도 이하여야 하고 각 값의 상한은 1TiB다. 이 상한은 검증된 운영 용량을 뜻하지 않는다. 운영자는 실제 디스크·동시 작업·전송 시험 후에만 한도를 올리고 재시작한다. HTTP 사용자는 한도를 변경할 수 없다.

하나의 private imports root에서는 OS 잠금으로 worker 하나만 실행한다. DB 트랜잭션은 중복 생성과 취소/완료 경합을 조정한다. 검증한 기존 부분 파일을 제외한 남은 bytes와 여유분·metadata 1MiB를 시작 전에 검사하고 쓰기마다 여유를 다시 검사한다. `reserved_bytes`는 이 실행기의 남은 전송량에 대한 논리 예약이며 다른 앱의 디스크 쓰기를 막지 않는다. 파일시스템과 OS 잠금을 공유하지 않는 여러 호스트의 NAS worker는 지원하지 않는다. `.partial`은 완료 자료로 등록하지 않고 취소 후에도 재개용으로 남긴다. 자동 원본 삭제·유료 증설은 하지 않는다.

완료 상태는 `pending_curation`이다. 확장자가 있어도 디코딩·시간 정렬을 증명한 것으로 보지 않는다. `rosy.media-manifest/1`은 원본 파일, 권리 증거, 외부 commit을 묶고 미확인 라벨·권리·capture group은 보류한다. 동기화된 state/action이 없는 자료는 모방 학습에 사용할 수 없다. 모델 다운로드는 적재·승격·로봇 실행을 허용하지 않는다. 다른 provider, 파일 업로드, Spaces 실행은 현재 범위에 포함되지 않는다. 외부 게시 권한이 있는 사용자는 저장된 연결로 비공개 데이터셋·모델 저장소를 조회·생성·삭제할 수 있다. 공개로 바꾸거나 기존 공개 저장소를 지우지 않는다.

전환 전 앱과 관련 쓰기를 멈추고 state, DB, 설정의 일관된 백업을 보관한다. 협업 바인딩 후 `--collaboration`만 제거하거나 DB의 바인딩 행을 지워 인증을 해제하지 않는다. 되돌릴 때도 협업을 유지하는 지원 버전을 쓰거나, 서비스를 멈추고 전환 전 백업을 별도 위치에 복원하여 기존 접근 범위를 다시 검토한다. 전환 후 이력은 별도로 보존하며 원본 백업을 덮어쓰지 않는다. 실제 외부 인증 수용은 등록된 앱과 사용자 동의로 로그인·연결·private/gated 접근·철회까지 확인해야 하며 가짜 provider 시험은 이를 대신하지 않는다.

협업 로컬 HTTP 경로는 아래와 같으며 CORE `/api/v1`이나 로봇 명령 프로토콜이 아니다. JSON POST는 정확한 Origin이 필요하며 로그아웃 외에는 세션과 `X-Pinky-Token`도 요구한다. 로그인은 `GET /api/account/login`이 Rosy Account로 보낸다. 세션 응답은 현재 사용자·프로젝트·권한·공개 연결 메타데이터와 요청 토큰을 반환하며 provider 비밀을 반환하지 않는다.

| 메서드 | 경로 | 요청 또는 동작 |
|---|---|---|
| GET | `/accounts` | 계정·가져오기 화면 |
| GET | `/api/accounts/options` | 협업/OAuth 사용 가능 여부 |
| GET | `/api/accounts/session` | 현재 세션·프로젝트·연결 |
| GET | `/api/account/login` | Rosy Account 로그인으로 이동, 복귀는 `/api/account/callback` |
| POST | `/api/accounts/logout` | `{}`; 현재 세션 철회 |
| POST | `/api/accounts/oauth` | `purpose: link` 또는 `manage` |
| GET | `/oauth/huggingface/callback` | provider의 `code`, `state` |
| POST | `/api/accounts/connect` | `token`, `sharing: personal|project`, `resources` |
| POST | `/api/accounts/disconnect` | `connection_id` |
| GET | `/api/accounts/repos` | `connection_id`, `repo_type`은 dataset 또는 model; `learning.publish`와 기록된 `read-repos` |
| POST | `/api/accounts/repos/create` | `connection_id`, `repo_type`, `repo_id`; `learning.publish`와 기록된 `write-repos`. 비공개만 만든다 |
| POST | `/api/accounts/repos/delete` | `connection_id`, `repo_type`, `repo_id`, `confirm`; `confirm`은 `repo_id`와 같다. `learning.publish`와 기록된 `manage-repos`. 조회 결과가 비공개일 때만 지운다 |
| GET | `/api/learning/imports` | 현재 프로젝트 작업 목록 |
| POST | `/api/learning/imports/create` | `connection_id`, `repo_type: dataset|model`, `repo_id`, `revision`, `files`, `rights` |
| POST | `/api/learning/imports/retry` | `id`; 동일 고정 입력 재시도 |
| POST | `/api/learning/imports/cancel` | `id`; 요청자 작업 중단 |

`rights`는 `internal_use: true`와 비어 있지 않은 `evidence`를 요구한다. gated 팀 이용은 `gated_team_use: true`, `team_use_evidence`를 별도로 기록한다. 사용자 선언은 검수·학습 권리 승인으로 승격되지 않는다. 기존 검수 version 충돌은 409, 인증·권한 실패는 401/403, 입력 오류는 400이다.

데이터 연결 해제는 해당 토큰을 철회하며 이미 연결된 HF 로그인 신원까지 제거하지 않는다. 내부 사용자 탈퇴·권한 변경은 private 설정에서 관리하고 로그인 수단 제거는 별도 신원 절차로 처리한다.

계정 화면은 현재 권한에 맞춰 연결·가져오기·해제 버튼을 표시한다. 프로젝트 연결 해제는 관리자, 작업 취소·재시도는 가져오기 권한을 가진 요청자에게만 표시하며 서버에서도 같은 조건을 검사한다. 세션 만료·철회가 다음 요청이나 상태 조회에서 확인되면 사용자·작업 목록과 입력 중인 토큰·자료 요청을 지우고 로그인 화면으로 돌아간다. 서버의 일시적 오류는 로그아웃으로 처리하지 않으며 `최신 상태 확인`으로 재시도한다.

OAuth 사용 시 `public_origin`과 `redirect_uri`의 `/oauth/huggingface/callback` 주소가 정확히 일치해야 한다. 누락·다른 호스트·다른 경로·HTTP callback은 작업공간에 협업 바인딩을 기록하기 전에 시작을 거부한다. 설정을 고친 뒤 다시 시작한다.

### 수집·저장 현황과 공간 점검

학습 화면의 `수집·저장 공간`은 등록한 프로젝트 폴더를 읽고 공간을 추정한다. 설정이 없으면 미설정으로 표시한다. `learning-storage.example.json`을 Git 밖의 private `learning-storage.json`으로 복사해 `--storage-config <private-json>`을 기존 시작 명령에 추가한다. 협업 모드는 project_id, 단독 모드는 해당 workspace metadata의 workspace_id를 쓴다. 관리자는 이 프로젝트가 소유한 데이터 디렉터리만 등록한다. 경로·project 변경은 재시작 후 적용한다.

root는 id, label, role(raw/derived/cache/pending), 절대 path를 가진다. history DB가 있는 폴더·중첩 root·심볼릭 링크 root는 거부한다. Linux/POSIX 모델 PC에서 디렉터리 descriptor와 no-follow로 부모부터 탐색한다. 지원하지 않는 호스트나 읽을 수 없는 폴더는 미확인으로 표시한다. 한 스캔은 항목 사이에 경과 5초·100000항목·깊이64를 검사하고 60초 캐시한다. 이미 대기 중인 네트워크 파일시스템 호출 자체를 중단하는 시간 제한은 아니다. 상한 초과, 내부 링크·특수 파일, 읽기 오류가 있으면 전체 합계를 null로 남긴다. 사용자에게 실제 경로·파일명을 반환하지 않는다.

논리 bytes는 파일 이름별 크기 합, file_bytes는 root 안의 inode 중복을 제외한 크기, allocated_bytes는 해당 파일들의 할당 블록 합이다. 재인코딩·동일 내용 복사·reflink를 내용 해시 중복 제거한 수치가 아니다. root 간 하드링크와 공유 볼륨의 여유 공간을 합산하지 않는다. `.part`, `.partial`, `.tmp` 이름의 파일과 `.partial` 디렉터리 안의 파일을 미완료로 별도 집계한다. 이것은 recorder 종료나 영상 품질의 증명이 아니다. pending 용도는 관리자가 완료된 전송 대기 자료만 놓는 폴더이며, 미완료 이름의 파일을 제외한다. pending root가 없으면 전송 대기량은 미확인이다.

하루 증가량은 같은 프로젝트·설정·root의 최근 30일 측정 중 24시간 이상 떨어진 두 값을 비교한다. 축적 근거가 없거나 감소/동일하면 증가량과 잔여 일수를 미확인으로 표시한다. 설정이 바뀌면 과거 추세를 섞지 않는다. 예상 잔여 일수는 그 폴더의 증가율과 현재 파일시스템 여유분 기준이며 다른 작업이 쓰는 공간까지 예측하지 않는다. 일별 집계는 기존 workspace DB에 저장하고 오래된 집계만 정리한다. 수집 원본에는 쓰지 않는다.

공간 사전 점검은 목적지 ID와 다운로드·임시 복사·변환 추가 공간·업로드 예상 크기를 받는다. 로컬 세 항목은 같은 목적지 볼륨에 존재하는 사본으로 합산하고 reserve_bytes를 더한다. 공간을 예약하거나 전송하지 않는다. 실제 작업 시작 시 자원 재검사가 필요하다. 웹 경로 입력, 삭제, 외부 게시와 유료 증설을 제공하지 않는다.

원격 quota는 미확인이 기본이다. 공식 quota API를 호출하지 않는다. 관리자가 수동 확인한 경우에만 remote_quota에 remaining_bytes, source(공개해도 되는 근거 설명), measured_at, expires_at(UTC epoch 초 정수)을 기록한다. 측정 전/만료 후에는 보류한다. 한 설정의 한 대상 quota이며 여러 계정 용량을 더하지 않는다. 업로드 요구량이 0이면 원격 quota는 점검하지 않는다. 최신 상태는 HTTP 401/403·오류가 발생하면 화면에서 지우고 재시도를 제공한다.
# AI 실행과 저장 버전 조회 (D-764)

객체/픽셀 화면의 **AI 초안과 확인**에서 저장된 사진 revision으로 새 초안을 요청한다.
실행 상태와 요청자·모델이 표시되며 완료 후 **AI 결과 목록 조회**로 후보 또는 참고 의견을
불러온다. 조회·실행은 라벨 적용이나 승인이 아니다. 미저장 획·선택 영역은 먼저 저장하거나
버린 뒤 요청한다. 실패 후 같은 실행 버튼으로 현재 revision의 새 작업을 만들 수 있다.
**이 AI 작업 취소**는 결과 등록을 막고 worker를 중지한다. 이미 모델 서버가 받은 연산은
종료될 때까지 남을 수 있다. 새 기능은 Tab 또는 Ctrl+K 기능 검색으로 접근한다.

**전체 이력 · 이전 버전 비교**는 20건씩 과거 이력을 조회한다. 버전을 선택하면 작업자·상태와
저장된 박스/마스크를 현재 화면과 비교할 수 있다. 과거 스냅샷이 없는 기록은 비교 불가로
표시한다. 과거 기록 조회로 현재 검수 revision은 바뀌지 않는다.

관리자는 모델 PC의 검증된 Python 환경과 기존 Qwen/SAM 설치를 사용해 private JSON을 만든다.
`--review-ai-config <private-config>`로 지정하거나 설치 도구가 읽는 state의 `review-ai.json`에
둔다. 설정이 없으면 실행 버튼에 이유가 표시되고 기존 검수는 계속 사용할 수 있다.
등록값 예시는 다음과 같다(실제 주소·경로·계정은 공개 저장소에 넣지 않는다).

```json
{
  "workspace_id": "<current-workspace-id>",
  "python": "/absolute/model-venv/bin/python",
  "model_digest": "<64-lowercase-hex-sha256>",
  "sam_checkpoint": "/absolute/models/sam3.pt",
  "sam_checkpoint_sha256": "<64-lowercase-hex-sha256>"
}
```

SAM 두 필드는 픽셀 보완에만 필요하다. Qwen 모델 이름과 loopback endpoint는 기존 adapter의
고정값을 사용한다. digest가 다르면 결과를 등록하지 않는다. 임의 명령·모델 URL·Python 경로를
웹에서 입력할 수 없다. 작업공간마다 실행 하나만 허용하며 서버 재시작 시 미완료 작업은 실패로
기록한다. 구버전 release로 돌아갈 때 설치 도구는 지원하지 않는 AI 옵션을 제거한다.
객체 초안은 기존 adapter의 7클래스(robot/obstacle_box/cone/traffic_light/sign/person/obstacle)
작업공간만 지원한다. 기존 6클래스 자료를 재해석하지 않는다. 새 자료는 별도 작업공간을 처음
만들 때 `--object-classes learning/curation/perception/classes/object_review_obstacle_v1.yaml`로
등록한다. 픽셀 보완·검사는 차선 내부 의미 체계만 지원하며 road_surface/1은 차단한다.
협업 모드는 edit 권한으로 요청·취소하고 타인 작업 취소는 manage도 필요하다. 등록 직전에
세션·권한을 다시 확인한다. 로컬 비협업 작업은 미인증 로컬 작업자로 표시한다.

관련 HTTP 계약은 API reference D-764 부록, 시험은 `test_review_ai_jobs.py`,
`test_review_ai_http.py`, `test_review_versions.py`, `test_review_ai_browser.py`다.
pytest는 canonical 원격 실행기로 실행한다. 브라우저 시험은 ROSY_RUN_BROWSER_TESTS=1이
필요하다. 모의 모델 연결 시험은 실제 GPU 모델 실행이나 정답 기반 정확도를 증명하지 않는다.

## 로봇 학습센터의 OMX 어댑터

`/learning`은 로봇·과제별 자료와 학습을 연결하는 기존 Learning 프로젝트의 공통 진입점이며, `/learning/omx`는 첫 로봇암 어댑터다. Model PC와 AI PC는 같은 프로젝트의 계산 호스트이며 새 OMX 전용 프로젝트를 만들지 않는다. 다른 로봇의 학습에는 해당 어댑터와 실행기 준비가 필요하다.

`--omx-center-config <private.json>`은 `/learning/omx`의 호스트 전용 오프라인·지속 학습을 활성화한다. 설정은 `schema=rosy.omx.center-config/1`, 소스·검수 상태와 겹치지 않는 절대 `root`, `python={act:<실행 파일>,hilserl:<실행 파일>}`다. 운영 설치·업데이트는 기존 보호된 검수 서비스의 `deploy/model_pc/install_review_release.py` 경로를 따른다. private 설정을 기존 `state/omx-center.json`에 두면 설치기가 대상 소스의 CLI 지원을 확인해 연결하며, 지원하지 않는 보관 릴리스로 전환할 때 플래그를 제거한다. 중앙 Account 협업 설정·loopback·HTTPS 보호와 기존 계정·라벨 DB는 유지한다. 처음 연결한 검수 프로젝트를 학습 root에 영속 바인딩하며 다른 프로젝트로 같은 root를 열면 거절한다.

| 경로 | 계약 |
|---|---|
| GET `/api/learning/omx/center` | 데이터·실제 작업·실행기 상태. 미설정이면 `not_configured`. |
| POST `…/upload` | UUID `upload_id`, 평면 `name`, 연속 `offset`, 256 KiB 이하 base64 `data`. 같은 offset/bytes의 재전송은 같은 끝 offset 반환, 다른 겹침은 거절. 부분 write의 일치 prefix 뒤만 append. 파일·디렉터리 sync 후 응답. 폴더당 512 MiB/1000개 파일 제한. 게시 후에는 같은 바이트 확인만 허용. |
| POST `…/publish` | `upload_id`, 표시 `name`. 데이터 해시·배열·분할 검증 후 등록. 이동 후 SQL 전 중단은 재검증해 복구하며 이동 디렉터리 sync 후 commit. 같은 identity 재시도는 기존 등록을 반환하되 실제 폴더 누락은 거절. |
| GET `…/profiles` | 현재 프로젝트 학습 root에 저장된 불변 팔·카메라 프로필 버전 목록. |
| GET `…/profile/<UUID>` | 저장 당시의 정확한 프로필 JSON 다운로드. |
| POST `…/profile` | 검증할 `profile`, 멱등 UUID `request_id`, 선택적 `parent_id`. 작성 신원은 서버가 바인딩하며 기존 버전을 수정하지 않음. |
| POST `…/export` | 등록된 OMX `prepared_id`(32자리 소문자 hex), `name`, `profile` 객체, 멱등 UUID `request_id`, 선택적 `review_id`, `profile_id`. 저장 선택 시 같은 입력인지 확인하고 서버의 정확한 저장 JSON 사용. 등록 root와 선택한 불변 검토 버전만 해석해 고정 native 변환 worker를 실행. 생산 검토·원본 해시·단위/카메라 매핑이 맞아야 함. |
| GET `…/review/<prepared-id>` | 원본 지문·episode identity·현재 검토 버전·판정·생산 학습 가능 여부. 원본 판정 파일은 변경하지 않음. |
| GET `…/review-frame/<prepared-id>/<source-revision>/<episode>/<frame>/<camera-index>` | 현재 원본에 묶인 실제 RGB JPEG. episode 경계와 공식 reader 행 identity를 검증하고 변경·대체 프레임은 거절. |
| GET `…/review-frame-set/<prepared-id>/<source-revision>/<episode>/<frame>/<camera-indices>` | 쉼표로 나열한 서로 다른 1~8개 카메라를 공식 reader의 한 기록 행에서 읽음. prepared_id/source_revision/episode_index/frame_index/index/timestamp_seconds/fps와 frames(camera_index,camera_key,jpeg_base64,width,height) 반환. 총 16M pixels/8MiB JPEG 제한, 누락·변경·잘못된 시각 거절. |
| POST `…/review` | `prepared_id`, `source_revision`, 전체 episode 순서의 `decisions`(`episode_index,outcome,split,object_result,reason`), `reviewer`, `confirmed=true`, 멱등 `request_id`. 인증 모드 reviewer는 서버 신원으로 대체. 미완성 분할은 draft로 보존하며 학습 가능으로 표시하지 않음. |
| POST `…/run` | `dataset_id`, `method=act\|hilserl`, `steps=1..100000`, `batch_size=1..64`, `device=cpu`, `seed`, 멱등 `request_id`, 선택적 `profile_id`, `arm_id`. 저장 프로필은 원래 전체 데이터와 비교. 독립 다중 팔은 `arm_id` 필수이며 선택 팔 정책을 학습, 공동 모드는 단일 팔 선택 거절. 고정된 worker만 실행. |
| POST `…/online-run` | 같은 요청 형식, `method=hilserl`만 허용. schema 2의 고정 관절별 행동 범위 필요. `steps`는 입력 하나당 업데이트 예산이며 새 경험을 기다리는 같은 worker를 유지. |
| POST `…/experience` | 실행 중 작업의 `id`, 등록된 `dataset_id`, 멱등 UUID `request_id`. 서버 경로·명령은 받지 않음. 영속 예약 후 연속 번호 큐로 전달. |
| POST `…/stop` | `id`. 저장한 Linux 프로세스 시작 시각·boot·명령 인자를 확인한 소유 그룹만 중단. |
| GET `…/artifact/<run-id>` | 완료·weights 해시를 검증한 모델·프로필·정규화·평가 ZIP. 지속 작업은 실행 중에도 마지막으로 완료한 immutable 버전을 제공. |

POST는 기존 Host/Origin·토큰·본문 크기 검사를, 협업 모드는 `manage` 권한을 거친다. 데이터 업로드 출처는 사용자가 선언하며 합성 시험은 `synthetic_smoke`로 보존한다. 실제 팔 제어·운영 모델 승격·현장 경험 생성은 이 API에 없다. 실패한 작업은 새 요청 identity로 재요청하며 같은 요청 identity의 재시도는 같은 기록을 돌려준다. 지속 작업 화면은 대기/학습·정책 버전·입력별 queued/consumed/rejected를 표시한다. 최초 train 정규화와 eval을 고정하고 새 입력의 프로필·원본 분할·해시를 재검증한다. 누출·변경·중복 입력은 추가 업데이트를 일으키지 않는다.

Native export는 `execution_mode=native_export`로 학습과 구분한다. 화면에서 등록 세트와 프로필 파일을 선택하고 실제 progress phase·오류·중단·완료 데이터 ID를 본다. 성공 시 배열과 변환 revision을 검증한 데이터만 자동 등록하며 이동 후 SQL commit 전 장애도 복원한다. 변환 결과에는 모델 ZIP이나 학습 평가가 없다. 현재 단일 native 팔을 요구하며 카메라는 원본 metadata의 정확한 키·크기와 프로필을 대조해 추가 키도 보존한다. raw-session 준비는 연결하지 않았다.

검수 열기는 원본 지문과 세션/cycle·frame/camera를 표시하며 원래 판정을 기본값으로 유지한다. 저장은 별도 `reviews/<UUID>/decisions.json,review.json` 및 DB의 불변 버전을 만들고 기존 원본을 덮어쓰지 않는다. 로컬 이름은 `local_unverified`, 인증된 사용자는 `authenticated`로 구분한다. 최종 파일은 완성된 임시 파일에서 원자적으로 게시해 부분 쓰기 실패 후 같은 요청으로 복구한다. 원본이 바뀌면 다시 불러와야 한다. 일반 새로고침은 작성 중 판정을 지우지 않는다. 저장한 검토를 변환에 쓸 때 체크박스로 명시 선택하며, worker는 원본 지문·스냅샷 해시·생산 분할을 다시 검증한다. Fixture 자료는 볼 수 있어도 production 학습용으로 변환할 수 없다. 프레임 확인/명시 체크박스가 실제 사람의 전체 관찰이나 실물 성공을 자동 증명하지 않는다.

여러 카메라 보기는 같은 원본·시도·프레임·기록 시각의 묶음을 한 번에 표시한다. 카메라가 8개를 넘으면 선택 카메라를 포함한 묶음으로 이동하며 원래 영상 비율을 유지한다. 자동 프레임 넘김은 직전 조회가 끝난 뒤 다음 행을 읽고 오류·마지막 프레임·자료/시도/보기 변경에서 멈춘다. 실제 재생 속도는 읽기 시간의 영향을 받는다. 표시 시각은 episode 상대 기록 행의 timestamp이며 촬영 장치의 물리 동기화 증거는 별도다. 검토 재생이 사람의 결과·교정 라벨을 자동 작성하지 않는다.
## SIM 실험 (D-834 Proposed)

SIM 웹 어댑터와 화면은 조건 확인·실행 요청을 위한 준비 경로다. 현재 공개 소스에는 실행에 필요한 `learning/envs/isaac/run_control.py`가 포함되어 있지 않다. 운영자가 검증된 외부 실행 소스·SDK·workspace binding을 준비하기 전에는 실행 연결 미설정으로 표시하고 실행을 허용하지 않는다. 이 화면의 추가나 모의 실행 시험을 실제 SIM 실행·로봇 학습 수용 근거로 쓰지 않는다.

작업 목록의 **SIM 실험**에서 조건 확인·실행·목록·상세·중지 요청·새 run 재실행을 사용한다. 기존 isaac 결과 폴더 연결과 `state.json`/`summary.json`·JPG 열람은 유지한다. 같은 모델 PC의 CLI와 불변 입력·run ID·결과·보고서를 공유한다. 모델 검사 통과를 물리 팔레타이징·학습 수용으로 표시하지 않는다. 혼합 적층·회수·협응 복구는 선행 검증 사유와 함께 비활성이다.

서버는 선택적 `--sim-config PRIVATE.json`을 사용한다. 설정이 없으면 SIM 연결 미설정으로 응답하고 기존 검수는 계속 동작한다. 이 파일은 현재 계정 소유·0600이며 검수 state의 workspace_id와 결속한다.

```json
{
  "workspace_id": "CURRENT_REVIEW_WORKSPACE_ID",
  "source_sha": "FULL_COMMITTED_SHA",
  "source_root": "/ABSOLUTE/PINNED/ISAAC_SOURCE",
  "binding_file": "/ABSOLUTE/OPERATOR/ISAAC_BINDING.json",
  "binding_sha256": "SHA256_OF_COMPLETE_OPERATOR_BINDING_BYTES",
  "entry_sha256": "SHA256_OF_SOURCE_learning/envs/isaac/run_control.py"
}
```

웹 프로세스는 외부 source에서 모듈이나 SDK를 import하지 않는다. 고정 entrypoint를 별도 `/usr/bin/python3`로 실행해 bounded JSON 요청을 전달하며 source·binding 지문을 대조한다. 동일 workspace binding은 모델 PC CLI가 사용하는 외부 run root를 가리킨다. 기존 Isaac SDK 준비는 [Isaac 환경 안내](../../../envs/isaac/README.md)를 참고하되, 웹 실행용 외부 소스와 binding은 별도 검증해야 한다. 서명된 웹 payload에는 `sim_web.py`·SIM HTML/JS를 포함해야 한다.

조회는 view, check/start/stop은 manage 권한과 기존 CSRF·Origin 검사가 필요하다. 로컬 비협업 검수에서는 실행·중지를 허용하지 않는다. 브라우저는 accountFetch로 다른 탭의 신원 변경 뒤 응답 적용을 막는다. 응답이 유실되면 같은 start 요청을 sessionStorage에 보존하고 자동 재시작하지 않는다. 조건을 다시 확인한 뒤 같은 요청을 재전송하거나 목록의 run을 조회한다. **새 실험으로 다시 실행**은 새 요청/run과 parent_run_id를 만들고 원본을 보존한다.

원시 SDK 로그·환경변수·private 경로는 웹으로 보내지 않는다. 최종 모델 검사 JSON만 manifest의 해시·크기를 확인해 제공하며 기본 검사는 영상이 없음을 표시한다. UNKNOWN·중지 요청·실제 종료·모델 검사 결과를 구분한다. `test_sim_web.py`, 명시적 `ROSY_RUN_BROWSER_TESTS=1`의 `test_sim_browser.py`와 공통 셸·서명 payload 누락 거절 시험으로 검증한다. 실제 SDK 실행은 별도 증거다.

## 공통 로봇·과제 학습 (D-840)

`/learning/tasks`는 학습 대상 등록 → 과제·참여 구성 → 자료·방법·실행 → 결과를 연결한다.
등록은 기존 device ID에 대한 학습 참조이며 실제 장치 연결·보정·실행 권한을 만들지 않는다.
여러 종류를 등록할 수 있고, 현재 실행 어댑터는 OMX다. 미지원 종류는 준비 사유를 표시한다.
리더·게임패드, 여러 팔·카메라의 설정은 기존 OMX 프로필 화면에서 준비한다.

| 경로 | 계약 |
|---|---|
| GET `/api/learning/tasks` | 현재 프로젝트의 robots/tasks, 저장 프로필, 자료, 작업, 실행기 가용 상태, 서버 `host_id`, CSRF token. |
| POST `/api/learning/robots` | `request_id` UUID, `name`, `kind`, `model_revision`, `device_id`. 불변 학습 대상이며 `device_verified=false`. |
| POST `/api/learning/tasks` | `request_id`, `name`, `objective`, `success`, `failure`, `reset`, `mode`, `adapter`, 순서 있는 `participants=[{robot_id,component_id,role}]`. OMX에는 서버가 읽을 `profile_id`가 필요하다. |
| GET `/api/learning/tasks/export?id=<UUID>` | 같은 프로젝트 안에서 전달할 과제·참여 로봇·프로필 메타데이터. 단일 identity만 허용한다. |
| POST `/api/learning/tasks/import` | `rosy.learning.task-transfer/1` 패키지. 프로젝트·과제 revision·실제 OMX 프로필 스키마·참여 구성을 검증한 뒤 원자적으로 반영한다. |

조회는 기존 view, 생성·가져오기는 manage 권한을 요구한다. POST는 기존 세션·CSRF·Origin과
1 MiB 본문 제한을 사용하며 작성자는 서버 신원이다. 비협업 loopback 작업은 `local_unverified`다.
다른 사용자·프로젝트 신원, 실행 명령·소스 경로·자격을 입력해 권위를 만들 수 없다.
전달 파일은 계정·세션·HF 연결·키를 포함하지 않으며 가져온 관리자의 로컬 신원을 기록한다.

계산 호스트는 불변 과제가 아닌 각 실행의 속성이다. private `omx-center.json`의 선택적
`host_id`를 `model` 또는 `ai`로 설정한다. 미설정이면 기존 과거 OMX 경로는 유지하되
과제 결속 실행은 거절한다. 같은 과제를 다른 호스트에서 사용하려면 먼저 같은 프로젝트의
보호된 원본에 과제 메타데이터와 검증된 자료를 명시적으로 전달한다. 자동 동기화는 없다.

기존 run/online-run 요청에 `task_id`와 `compute_host`를 함께 넣으면 서버가 실제 호스트,
전체 프로필 revision, 로봇/device/component/role 순서와 선택 팔을 검증한다. 자료 ID와
revision은 한 과제에 결속하며 다른 참여 그룹으로 암묵적으로 재사용하지 않는다. 과거 자료를
처음 연결할 때는 `historical_dataset_attachment`로 기록하며 원래 과제별 촬영 증거로 표시하지 않는다.
같은 과제에서 ACT와 HIL-SERL을 비교하거나 독립 팔별로 학습하는 것은 허용한다.
지속 경험의 추가 자료에도 같은 검사를 적용한다. 작업별 경험 추가와 중지는 host worker에만
적용하며 저장된 결과를 보존한다. 실물 로봇 actor·사람 개입·보상·초기화 연결은 별도 수용이다.

worker request, run, 평가 결과에 같은 과제 snapshot을 남긴다. 완료 모델 ZIP의
`learning-task.json`은 과제·참여 구성·실제 호스트와 평가 파일 SHA256을 포함한다.
평가·요청·완료 결과의 snapshot이 다르면 다운로드를 거절한다. 과제 없는 기존 작업은 그대로 읽는다.
코드 전환 전에는 새 실행·추가 경험 게시를 중단하고 활성 학습 작업을 끝내거나 중지한다.
공식 설치기는 활성 작업·손상된 학습 상태를 사전 검사하며, 이 검사가 동시 요청에 대한
배포 잠금을 대신하지는 않는다. 구버전 rollback 중에는 과제 결속 지속 작업을 재개하지 않는다.

## VLM 판단 (D-853 Proposed)

정답 메뉴의 **VLM 판단**(`/learning/vlm`)에서 닫힌 VLM 질문(`tools/vlm_question_bench.py`)의 정답을 다룬다(T1, `docs/plans/2026-10-23-vlm-fast-judge-design.md`).

**정답 두 단계(D-857 §4–5).** 사진×질문의 정답은 **임시**(모델 합의)와 **확정**(사람)이다. 사람이 단 답과 점검에서 「맞음」·「고침」으로 저장한 답이 확정이다. 임시 정답은 저장하지 않고 읽을 때마다 모델 답에서 만든다. 합의 규칙(시작값, `vlm_judge.py` 맨 위 상수): 서로 다른 모델 2개 이상이 같은 답을 내고 각각 p ≥ 0.8이며, 답을 낸 어떤 모델도 다른 답을 내지 않아야 한다. 같은 모델의 Ollama·transformers 런타임과 `@<px>` 크기는 한 모델로 세고 가장 확신 높은 런타임을 쓴다. 합의는 승인·승격이 아니다(D-514 §5, D-853 §3).

사람은 대기열만 본다. 평가셋은 한 번 끝내는 일이고, 의견 갈림·점검은 계속 들어오는 일이다(의견 갈림은 보기마다 오래된 사진부터 50장까지만 열고 나머지는 「대기」로 센다. 점검은 열린 의견 갈림+점검이 50건 미만일 때만 더한다).

| 종류 | 고르는 법 | 화면 |
|---|---|---|
| 평가셋 | 보기(front·top·wrist)마다 최대 **30장**이고 그 사진의 모든 질문에 답한다. 처음 고를 때 보기와 sha256으로 정한 순서에서 합의 모양(질문별 임시 정답, 합의 없음은 빈칸)마다 번갈아 뽑아 `vlm_eval_set`에 고정한다. 모델이 더해져도 바뀌지 않고, 제외로 30장보다 줄 때만 새 사진을 채운다. 화면은 「평가셋 12/30」처럼 진행을 따로 보인다 | 모델 답 비표시 |
| 의견 갈림 | 평가셋 밖에서 어떤 질문이든 합의가 없는 사진 | 모델 답 비표시 |
| 점검 | 평가셋 밖에서 모든 질문이 합의된 사진 중 ISO 주마다 보기당 최대 10장(주와 sha256으로 정한 순서). 열린 의견 갈림+점검이 50을 넘으면 더 넣지 않는다 | 임시 정답과 큰 「맞음 A」·「고침 E」. 고침은 선택지를 열고 임시 정답을 미리 고른다 |

**모델 토론(D-857 §4).** 의견이 갈린 질문은 모델 PC에서 오프라인 토론 한 판으로 다시 물을 수 있다. 웹앱은 모델을 부르지 않는다(D-459).

```bash
python learning/curation/perception/vlm_judge.py export-disputes --state <VLM_STATE> --out debate.jsonl
python tools/vlm_question_bench.py --debate-input debate.jsonl --debate-as <가져온 모델 이름> --model <HF id> [--quant 4bit] [--long-side 448] [--debate-rounds 2] [--ollama <loopback Ollama URL>] --out <dir>
python learning/curation/perception/vlm_judge.py import --state <VLM_STATE> --rows <dir>/rows.jsonl --questions <questions.json> --model <같은 모델 이름>
```

`export-disputes`는 대기 중이고 평가셋 밖이며 멈추지 않은 질문 중 합의가 없는 (사진, 질문)마다 상태 안 사진 경로, 보기, question_set, 질문 id·문장·선택지와 모든 모델의 지금 의견(모델, 런타임, 답, p)을 한 줄로 쓴다. 벤치의 토론 모드는 같은 사진과 닫힌 질문에 다른 모델의 답과 확률을 「model A/B」로 익명화한 짧은 메모를 붙여 다시 묻고, 선택지 확률은 지금처럼 읽는다(transformers prefix/suffix 또는 Ollama top_logprobs). 이 모델이 전에 답한 질문만 묻는다. 결과 행은 `frame`·`view`·`long_side`와 `debate:{질문: {answer, p}}`를 가진다. 기본 한 판, `--debate-rounds 2`는 둘째 판에 자기 첫 판 답을 보이고, 다른 모델의 토론 답은 다시 내보낸 `debate.jsonl`에서 「after debate」로 보인다. 가져오기는 이를 같은 모델 이름의 런타임 `debate`로 저장하고 뒤 판이 앞 판을 바꾼다. 그 모델이 그 질문에 답한 적이 없으면 거절한다. 합의에서 토론 답은 그 모델의 다른 런타임 답을 대신하므로 모델 수가 늘지 않는다. 토론 답이 `none_in_top`(선택지 없음)이면 그 모델의 그 질문은 「답 없음」으로 바뀌어 합의를 막고, 앞 런타임의 답은 다시 세지 않는다. 토론 답도 임시 정답이며 점검·멈춤 규칙을 그대로 따르고, 평가 탭은 토론으로 합의한 임시 정답 수를 따로 센다.

**질문 세트 v3.** v2 토론이 하나도 정하지 못한 세 질문은 뜻이 모호했다. v3는 `front.lane_tape`를 화면 왼쪽·오른쪽 절반의 테이프 `front.tape_left`·`front.tape_right`로, `front.lane_obstruction`을 화면 아래쪽 절반의 두 테이프 사이 물체 `front.object_between_tapes`로, `top.robots_close`를 `top.robot_count`(zero·one·two·many)로 바꾼다. 천장 프레임에는 프레임마다 ArUco 세계 좌표 하나(`poses.jsonl`)만 있고 로봇별 화면 위치가 없어, 설계의 로봇별 잘라 묻기(`top.robot_adjacent`·`top.ahead_space`)는 로봇별 위치가 생긴 뒤로 미룬다. 질문 문장이 바뀌면 새 question_set이므로 v3 정답은 새 state(`state-v3`)에 둔다. 손목 질문은 같아 v2 손목 행을 그대로 가져온다.

점검 저장은 `vlm_audits`에 질문마다 임시 정답과 사람 답을 남긴다. 한 질문의 점검이 5건 이상이고 틀린 비율이 10%를 넘으면 그 질문의 임시 정답을 멈춘다(대기열·평가 탭에 표시, 범위·내보내기·점검에서 뺀다. 의견 갈림으로 보내지는 않는다). 질문과 모델을 고친 뒤 관리자가 서버에서 `python learning/curation/perception/vlm_judge.py unpause --state <VLM_STATE> --question <질문 id> --actor <이름>` 또는 `POST /api/learning/vlm/unpause {question}`(협업은 manage)으로 다시 켠다. 누가·언제 켰는지 `vlm_unpauses`에 남고, 그 질문의 점검 수는 그 뒤 점검부터 다시 센다(이전 `vlm_audits`는 이력으로 남는다). 대기열 밖의 합의된 사진은 정답 달기에 나오지 않는다. 대기열 고르기의 「정답 있음」으로 확정 정답을 다시 열어 고칠 수 있다. 평가 탭은 확정 정답만으로 모델·런타임·질문별 n, 일치율, balanced accuracy, 혼동표, 모순 답 수(`wrist.object_in_gripper=yes`와 `wrist.gripper_empty=yes`), 사람 `unclear` 비율을 계산한다. 같은 비교를 고정 평가셋만으로도 따로 보인다(`eval_set`). 평가셋은 모델 답 없이 달았고, 점검은 임시 정답을 보고 달았기 때문이다. 또 질문별 임시 정답 범위(대기 사진 중 임시 정답이 있는 비율), 점검 오류율, 멈춘 질문을 보인다. 일치율은 측정값이며 승인이 아니다. 이 정답은 평가용이며 객체·픽셀 검수, export, 학습 자료로 들어가지 않는다.

운영 검수 state와 섞지 않도록 별도 state를 만든다(D-853 §4). 가져오기·정답 저장·다시 켜기는 `--empty-eval`이 만든 state(`metadata.workspace_kind=evaluation`)에서만 되고 다른 state에서는 거절한다. 읽기는 VLM 표가 없으면 빈 결과를 주고 표를 만들지 않는다. 센터(학습 검수 인스턴스)를 `--vlm-eval-url <https://…/learning/vlm>`으로 띄우면 평가·승격 화면과 홈의 VLM 줄이 그 별도 인스턴스로 가는 링크를 보인다(링크만, 자료를 읽지 않는다. http(s)·자격 증명 없는 주소만 받는다).

```bash
python learning/curation/perception/review_app.py --state <VLM_STATE> --empty-eval --host <tailscale-ip> --port <port>   # 첫 시작
python tools/vlm_question_bench.py --dump-questions <questions.json>
python learning/curation/perception/vlm_judge.py import --state <VLM_STATE> --rows <bench-out>/rows.jsonl --questions <questions.json> --model <model>
```

두 번째 시작부터는 `--state`만 준다. 가져오기는 로컬 모드의 **가져오기** 탭이나 위 CLI로 한다. 협업 모드는 `/api/import`처럼 서버 파일 경로 가져오기를 거절하므로 서버에서 CLI를 쓴다. rows에는 모델 이름이 없으므로 `--model`로 준다. `long_side`가 0이 아닌 행은 `<model>@<px>`로 구분한다. 같은 사진(sha256·view·question_set)은 다시 만들지 않고 새 모델 답만 더하며 사람 정답은 건드리지 않는다. 같은 question_set에 다른 질문 문장이 오면 거절하므로 문장을 바꾸면 새 version을 쓴다. Ollama의 `none_in_top`은 모델 답 없음으로 세고 선택지로 바꾸지 않는다.

| 경로 | 내용 |
|---|---|
| `GET /api/learning/vlm/summary` | view·상태별 수, question set, 정답 단 사람, POST용 token |
| `GET /api/learning/vlm/queue?view=` | 사람 확인 대기열 `{items:[{id, view, image_name, question_set, kind}], counts:{view:{eval, disputed, audit, eval_size, eval_done, disputed_waiting}}, paused, week, cap}`. 첫 읽기가 평가셋을 고정한다 |
| `GET /api/learning/vlm/items?view=&status=` | 사진 목록(질문·모델 답 없음) |
| `GET /api/learning/vlm/items/<id>` | 질문과 현재 사람 정답, `version`, 대기열 `kind`. `kind=audit`일 때만 `provisional`(임시 정답)을 더한다 |
| `GET /api/learning/vlm/images/<id>` | 매 요청 sha256 재확인 후 원본, ETag `no-cache`(D-469) |
| `GET /api/learning/vlm/evaluation` | 확정 정답만의 비교, 고정 평가셋만의 비교 `eval_set`, `provisional`(범위), `audits`, `paused` |
| `GET /api/learning/vlm/export` | JSONL과 그 sha256. `labelled`·`excluded` 사진(답 `tier` `confirmed`)과, 고정 평가셋 밖에서 멈추지 않은 모든 질문이 합의된 대기 사진(`status`·`tier` `provisional`). 평가셋·의견 갈림 사진은 사람이 정할 때까지 빠진다(블라인드). 줄마다 `tiers:{질문: confirmed/provisional/null}`. 협업은 manage |
| `POST /api/learning/vlm/items/<id>` | `{version, status, answers}`. `labelled`는 모든 질문 답 필요, `excluded`는 null 허용. 버전이 다르면 409. 점검 사진을 `labelled`로 저장하면 점검 기록이 남는다(서버가 판단) |
| `POST /api/learning/vlm/unpause` | `{question}`. 멈춘 질문을 다시 켠다(협업 manage, actor 기록) |
| `POST /api/learning/vlm/import` | `{rows_path, question_set, questions, model}`. 서버 파일 경로를 읽으므로 로컬 모드 전용(협업 403) |

저장소는 같은 `reviews.sqlite3`의 `vlm_items`, `vlm_model_answers`, `vlm_labels`(현재), `vlm_label_events`(이력), `vlm_audits`(점검), `vlm_eval_set`(고정 평가셋), `vlm_unpauses`(다시 켜기)와 `<state>/vlm/images/<sha256>.<ext>`다. 협업에서는 정답 저장에 edit가 필요하고 actor는 로그인 사용자다. 로컬 비협업 모드는 앱의 다른 저장처럼 actor가 null이다(D-478 bind 규칙). 단축키: `←/→` 이전·다음, `N` 다음 대기, `↑/↓` 질문 이동, `1–9` 선택지, `Enter` 저장하고 다음, `?` 안내, 점검 사진에서 `A`·`Enter` 맞음과 `E` 고침. 입력칸·IME 조합·Ctrl/Alt/Meta 중에는 동작하지 않는다(D-538 §5). 시험은 `test_vlm_judge.py`와 `ROSY_RUN_BROWSER_TESTS=1`의 `test_vlm_judge_browser.py`다. 실제 정답 품질과 모델 PC 운영은 별도 증거다.
