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
python learning/training/perception/dataset/review_app.py --state X:/DevTemp/pinky-review-state --port 8768 --host 100.98.162.71
```

검수자는 `http://100.98.162.71:8768/pixels`를 연다. 받는 값은 loopback·사설(RFC1918)·link-local·Tailscale(100.64.0.0/10) 리터럴 IPv4뿐이다. `0.0.0.0`, 공인 주소, 호스트 이름은 시작 때 거부된다. HTTP만 쓰며 tailnet 구간은 이미 암호화된다.

위험: 사용자 인증이 없다. 그 주소에 닿는 누구나 사진을 보고 수정하고 승인할 수 있고, 검수자 신원은 증명되지 않는다. 신뢰한 tailnet/LAN에서 필요한 동안만 켠다. 쓰기 token과 Host/Origin 검사는 그대로다.

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
python learning/training/perception/dataset/review_quality.py --state X:/DevTemp/<name>/state --threshold 0.15 > X:/DevTemp/<name>/exposure-preview.json
```

모델 PC에서 로컬 Qwen 영상 모델의 **참고 의견**을 만들려면 다음을 실행한다.
원본 사진·현재 indexed mask의 SHA를 검증하고 255 픽셀 수와 프레임별 시각 의견을
새 보고서 폴더에 기록한다. 전체 실행이 끝나고 검수 결정 세대가 유지됐을 때만
`<state>/vlm-feedback.json`을 갱신한다. `/pixels`는 해당 사진의 원본·마스크 SHA가
보고서와 같을 때만 최신 의견으로 표시한다. 다른 사진의 변경은 이미 검사한 사진의
의견을 숨기지 않으며, 해당 마스크가 바뀌면 오래된 의견으로 표시한다.

```bash
python learning/training/perception/dataset/vlm_mask_feedback.py \
  --state <review-state> --out <new-report-directory>
```

Ollama `qwen3-vl:8b-instruct`는 모델 PC의 `127.0.0.1:11434`에서만 사용한다.
`--limit N`은 시험용 부분 보고서이며 앱에 게시하지 않는다. AI는 승인·제외·학습 자격을
바꾸지 않는다. `no_obvious_concern`도 검수 완료가 아니다. 255가 남으면 사람 픽셀
승인이 거절되며, VLM이 판단을 보류하거나 잘못 읽을 수 있으므로 원본을 직접 확인한다.

### 클래스셋 (D-485)

객체 클래스는 첫 실행의 `--object-classes <data.yaml>`로 정한다. 파일은 Ultralytics `data.yaml`의 `names`(목록 또는 번호 사전)를 읽고, 선택 항목 `display`(이름별 표시 문구)와 `colors`(이름별 `[r, g, b]`)를 받는다. 생략하면 D-423의 기본 6개 클래스다. 한 작업 공간은 객체 클래스셋 하나와 픽셀 클래스셋 하나에 묶인다. 다른 모델의 클래스로 검수하려면 다른 `--state`로 새 작업 공간을 만든다.

```powershell
python learning/training/perception/dataset/review_app.py --state X:/DevTemp/<name>/state --source <source.jsonl> --human <human.jsonl> --images <image-root> --object-classes <data.yaml> --port 8767
```

픽셀 `classes.yaml`은 항목마다 선택 항목 `display`를 둘 수 있다. 차선 모델(왼쪽/오른쪽 차선, 횡단보도, 과속방지턱)용 파일은 `learning/training/perception/classes/lane_lr5.yaml`이다. 카탈로그 가져오기(`/api/import`) 요청 본문의 `classes`에 이 파일 경로를 넣는다. 비우면 초안 마스크 zip 옆이나 카탈로그 옆의 `classes.yaml`을 찾는다.

주행 가능 영역을 검수할 때는 `learning/training/perception/classes/lane_lr6_drivable.yaml`을 **새 `--state` 작업 공간**의 `/api/import` `classes`로 지정한다. 기존 0~4번은 그대로이고 5번 `drivable`이 추가된다. v12 작업 공간에 이 파일을 다시 바인딩하면 마스크의 뜻을 바꾸게 되므로 서버가 거절한다. 새 작업 공간에는 원본 검증 카탈로그를 다시 가져오고, 기존 픽셀 승인이나 초안을 승인 상태로 복사하지 않는다. 새 마스크는 검수 대기에서 시작하며 저장·전체 확인·픽셀 승인을 거쳐야 학습 입력으로 내보낼 수 있다. `drivable`은 D-475의 화면에 보이는 흰 경계선 안쪽 도로 바닥 전체이며, 차선 칠·도로 밖 바닥·장애물에 가린 화소와 구분한다. 기존 5채널 모델의 클래스 순서를 그대로 둔 채 6클래스 정답으로 학습하거나 승격하지 않는다.

모델 PC에서 `.pt`의 클래스 이름을 `data.yaml`로 뽑는다. 검수 앱은 모델을 열지 않는다.

```powershell
python learning/training/perception/model/export_class_names.py best.pt --out data.yaml
```

클래스셋 sha(`object_class_set_sha256`)는 `review-contract.json`과 `/api/workspace`에 있고 `/api/decisions`에는 없다.

단축키 (입력 칸에 포커스가 없을 때, 한글 입력 상태에서도 같은 키):

| 키 | 동작 |
|---|---|
| `1`-`9` | 클래스 선택 (선택한 박스에 지정) |
| `A` | 승인 (전체 확인 체크 후에만, 픽셀 검수는 기본 배경 확인 체크도 필요) |
| `X` | 제외 (검수 대기 사진만) |
| `←` / `→` | 이전 / 다음 사진 |
