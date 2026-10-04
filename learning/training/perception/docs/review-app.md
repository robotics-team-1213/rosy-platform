# Pinky 학습 검수 웹앱

결정은 [D-456](../../../../docs/adr/D-456-pinky-persistent-label-review-application.md)이다. 이 앱은 PC에서 실행하는 영속 객체 라벨 검수 도구다. 로봇·모델 API를 호출하지 않는다.

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
