# Cam LAN 목록의 비활성 사유와 초점

2026-10-29 · `fix/cam-lan-guidance` · 기준 `e56f8e8bc350` · runtime `92650b7d1057` · 최종 시험 `5bd25af46e41`.

## 변경

기존 목록은 주소를 찾지 못했거나 승인 방식을 확인할 수 없는 기기를 비활성화하면서 이유를 표시하지 않았다. 발견 수명은 CameraLanScreen에 그대로 두고 표시만 CameraLanRows로 분리했다. 주소 충돌·주소 미확인·승인 방식 미확인의 이유와 다음 행동을 disabled 버튼 밖의 Text로 표시한다. 기존 MaterialTheme의 onSurfaceVariant/bodyMedium, RosyMetrics.Space2, 공용 버튼 padding/shape/48dp를 사용한다.

재정렬 시 위치가 다른 기기를 가리키지 않도록 serviceName/tlsHost/port를 Compose key로 사용한다. enabled의 기존 식, conflict 판정, onSelect(record), 발견 map·기억된 연결·승인·trust·촬영은 그대로다. 새 의존성이나 설정·명령 API는 없다. 주소는 합성 TEST-NET 값만 사용하고 실제 기기에는 접근하지 않았다.

## 커밋별 실제 증거

원본 scratch는 `C:/DevTemp/rosy-ui-standardization/`이다. reports.sha256은 로그·receipt·JVM XML·최종 semantics97개, captures.sha256은 최종 PNG24개의 SHA256을 보존한다. 앞선 캡처는 최종 수에 합산하지 않는다.

| SHA / 원본 경로 | 결과 | 판단 |
|---|---|---|
| `cb623e7429`, cam-lan-evidence/red/cam-lan-red/instrumentation.txt | 3 run/3 failures | 이유 노드 부재2건은 제품 반례. 나머지1건은 재정렬 전 최초 RequestFocus 실패이므로 fixture 문제 |
| `92650b7d10`, cam-lan-evidence/green-build-failed/build.log | BUILD FAILED | keyboard 시험 API opt-in 누락. native 제품 동작 결과가 아님 |
| `92650b7d10`, cam-lan-affected/run-1.txt | 517 passed/47 warnings, NEW0 | 공식 affected Python 계약. native 실행과 구분 |
| `976aefc0c7`, cam-lan-evidence/cam-lan-green/instrumentation.txt | 4 run/2 failures | 이유2건은 통과. 최초 input focus/Tab Invalid rect는 fixture 입력 모드 문제. 전체 합격으로 세지 않음 |
| `814930a6cd` / repro `3abd0f2da1`, keyboard-build-failed / key-red-build-failed/build.log | BUILD FAILED | input mode API의 별도 opt-in 누락. 각 실패 로그를 보존 |
| `c77e6697a9`, cam-lan-evidence/cam-lan-key-red/instrumentation.txt | 4 run/2 failures | 올바른 Keyboard fixture에서 key만 제거한 반례. 최초 초점은 성공하고 재정렬 후 두 검사가 실패. 이유2건은 통과 |
| `5bd25af46e`, cam-lan-evidence/final-build/build.log 및 testDebugUnitTest/ | BUILD SUCCESSFUL, JVM443 passed/0 failures/errors/skips, 57 suites | SDK35 실제 JVM/debug APK/androidTest APK 빌드 |
| `5bd25af46e`, cam-lan-evidence/cam-lan-final/instrumentation.txt | 4 passed/0 failed | 320·800dp/글꼴1.3, density160, AVD1280×1000 |
| `5bd25af46e`, cam-lan-evidence/cam-lan-final-density240/instrumentation.txt | 4 passed/0 failed | 같은4개 시험, density240, AVD1280×1600 |

재현 ref `fix/cam-lan-guidance-red`는 비교 전용이며 제품 통합 대상이 아니다. 최종 runtime은 이후 시험 커밋에서도 동일하다. 중간23ec 시험의4pass 반복과 최종4pass를 합산하지 않는다. adb am instrument의 exit0만으로 판단하지 않고 JUnit 실패 수와 unit 실제 종료를 확인했다.

최종 시험은 비활성 버튼 터치가 callback을 호출하지 않는지, 두 승인 방식(peerApproval/pairable)이 정확한 record를 전달하는지 검사한다. 이유는 실제로 표시되고 화면 폭 안에 있어야 한다. 유효 버튼은 스크롤 후 전체 화면 경계 안·최소48dp·displayed/enabled여야 하며 클릭 전에 촬영한다. 최초 input focus와 실제 Tab 이동 후 재정렬에서 동일 endpoint 초점과 선택 callback0회를 검사한다. Keyboard 모드를 명시해 touch 모드의 시험 실패를 제품 결함으로 오인하지 않는다.

## 렌더와 독립 검토

최종 각 phase/captures에12개 PNG와12개 semantics가 있다. 각 밀도에서 주소 없음·승인 방식 미확인·충돌의 두 폭6장, 유효 peer/legacy의 두 폭4장, 재정렬 초점2장이다. Compose captureToImage는 실제 앱 theme background가 있는 화면을 촬영한다. 초기 투명 배경6장과 선택 대상이 화면 밖인 이전8장 묶음은 최종 수용 근거로 혼합하지 않는다.

A는 runtime과 최종 시험을 독립 검토해 추가 P1/P2를 찾지 못했다. B는 최종24장을 모두 직접 보고 두 밀도의 비활성 사유·좁은 폭의 유효 peer/legacy 전체 가시성·재정렬/Tab 초점 채움을 확인했으며 추가 P1/P2는 없었다. 대비 비율은 계측하지 않았다. Root도 density160의 좁은 폭 legacy와 density240의 충돌 사유를 직접 확인했다. 실제 발견·승인·촬영·MainActivity 전체 로비를 시작하지 않은 합성 표시 fixture의 증거다. Cam의 등록된 native dark만 검사했으며 밝은 테마·음성 TalkBack·실물 연결 수용으로 확대하지 않는다.

승인된 시험 PC의 기존 SDK35·시스템 이미지·Java21·KVM을 사용했다. SHA별 Git archive와 별도 build/cache, hard resource limit와 기존 admission을 사용했다. 소유 AVD의 serial/AVD/qemu/boot를 확인한 뒤 해당 앱만 설치했다. 캡처는 다음 uninstall 전 host에 회수하고 로컬 복사까지 확인했다. 자기 emulator stop은 timeout/ExecMainStatus15·MainPID0·failed로 실제 종료했고 정상 종료로 바꾸어 기록하지 않았다. 다른 장치나 공유 adb 서버는 종료하지 않았다.

## 게이트와 CE

소스 UI·debug 빌드·합성 에뮬레이터 근거다. 서명 release·실제 기기·촬영/송신·실제 승인·ARTIFACT/DEVICE/FIELD·배포·착지·공개 push/merge는 수용하지 않았다. 다른 Cam 상태·SIM·LCD·전체 이행표·최종 통합 검증은 남아 있다.

CE: 해당 없음 — disabled 사유·Compose identity와 입력 모드 fixture 경계는 코드·회귀·이 기록에서 복원된다. 실제 장치·운영 장애 해결을 주장하지 않는다.
