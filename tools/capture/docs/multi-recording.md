# 여러 카메라·로봇을 함께 녹화

`multi_record.py`는 **관제 PC**에서 실행한다. 선택한 Rosy Cam 소스와 로봇 전방
카메라를 함께 녹화하며, 소스 수에 따라 화면 칸을 늘린다. 많은 소스는 화면을
세로로 늘려 스크롤하고, 합성 영상도 그 높이로 만든다. 기존 Fleet 영상 중계
금지 계약을 유지하며 로봇 영상은 PC가 CORE에서 직접 받는다.

## 실행

CA와 토큰은 기존 등록 절차에서 준비한다. 설정은 공개 저장소 밖에 둔다.
`token_file`·`ca_file`은 실행 위치 기준 경로이므로 절대 경로를 권장한다.
실제 URL은 인증서에 있는 호스트 이름이어야 한다. 이름 해석이 안 되는 PC에서는
`connect_host`에 IP를 별도로 넣는다. 인증서 검증은 URL의 이름으로 그대로 한다.

```json
{
  "site": {
    "url": "https://<site-host>:8443",
    "ca_file": "<site-ca.pem>",
    "token_file": "<site-viewer.token>"
  },
  "sources": [
    {"id": "overhead_north", "kind": "site", "source_id": "<approved-camera-source>"},
    {"id": "front_a", "kind": "robot", "robot_id": "<enrolled-robot-id>",
     "url": "https://<robot-host>:8080", "ca_file": "<robot-ca.pem>",
     "token_file": "<robot-viewer.token>"},
    {"id": "front_b", "kind": "robot", "robot_id": "<another-enrolled-robot-id>",
     "url": "https://<another-robot-host>:8080", "ca_file": "<another-ca.pem>",
     "token_file": "<another-viewer.token>"}
  ]
}
```

他のカメラやロボットは `sources` に行を足す。`id` は表示名と保存先に使う
英数字・`_`・`-` の一意な名前。`robot_id` は既存の登録 ID を使い、別の
ロボットの認証情報と組み合わせない。`site` はロボットだけの場合も指定すると
Fleet の確認済み位置を一緒に保存できる。

```powershell
python tools/capture/multi_record.py record --config <private-config.json> --out X:/DevTemp/<new-session> --duration 60
python tools/capture/multi_record.py render --session X:/DevTemp/<session> --out X:/DevTemp/<combined.mp4>
```

開始時にこの PC の `127.0.0.1` の画面を開く。録画は指定時間または Ctrl+C
で終了する。別 PC に公開しない。終了したセッションの再生・共有には MP4 を使う。
`--no-open` は画面を開かずに記録する。新規セッション・MP4 は既存ファイルを
上書きしない。

## 保存と分析

- 各ソースの `frames/`: API から受け取った原本 JPEG。
- `capture.sqlite3`: `frames`（元時刻・受信時刻・sequence・SHA256・ファイル）、
  `positions`（Fleet tracking の時刻・位置）、`events`（開始・終了・ソース切断）。
- `session.json`: トークン・URLを含まないセッション要約。
- サイトカメラの `calibration.json`: 取得時点の承認済み補正。
- 合成 MP4 と `.mp4.json`: フレーム数・時間範囲・合成方法・SHA256。

これは **PC の分析用 DB** への保存であり、Fleet の `core_event_audit` に
合成セッションを追加する実装ではない。既存のロボットネイティブ録画は別操作で、
その CORE イベントは従来どおり Fleet が保存する。このツールは録画・主行・
E-Stop の変更 API を呼ばない。Viewer 権限で使える。

## 映像・位置の意味

ロボット preview は API 契約の最大 2 FPS。ネイティブ MCAP の高速画像を
代替しない。raw がなければ映像なしを表示し、注釈画像を原本に見せない。
ROS/source clock と受信時刻を両方保存する。UTC と照合できないロボット時刻は
合成に受信時刻を使い `receipt` と表示するため、厳密な同期の証明にはならない。
2 秒を超えたフレームは合成でも空欄にし、位置も古ければ未確認とする。
未割当の検出をロボット位置と推測しない。`NO_POSE` は未確認のまま表示する。
補正レコード・登録・安全状態を変更しない。

一台の切断は他のソースの記録を止めない。保存先ディスクには必要な空きを
用意する。合成には既存の Pillow と `ffmpeg` が必要で、JPEG ハッシュの不一致は
エラーで停止する。セッションには現場映像・位置があるため共有範囲を確認する。
