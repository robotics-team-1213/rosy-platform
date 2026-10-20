# 실제 전역 StaticLayer의 원본 지도 적용 확인

전체 스테이션 목표는 ACTIVE다. 이번 구현은 전역 static contribution의 원본 지도 적용을 확인하는 기본 OFF native opt-in이다. CORE의 최종 이동 권한 경로, 전체 충전 주기, ARM64와 DEVICE/FIELD는 완료하지 않았다.

## 구현 범위

[승인된 R3 계획](../../plans/2026-10-17-native-map-adoption.md), D-783과 기존 [AMCL 검증](../station-native-map-amcl-2026-10-17/result.md)을 잇는다. `VerifiedStaticLayer`는 실제 Nav2 StaticLayer를 상속하고 Costmap2DROS가 제공한 private callback group에 최초 map subscription과 readback service를 만든다. base onInitialize로 우회 구독을 만들지 않는다. immutable 원본 검증/hash는 native 잠금 밖에서 수행하고, 실제 master→layer 순서로 잠근 뒤 upstream processMap을 한 번 호출한다.

수신·native buffer 처리만으로 채택을 응답하지 않는다. 실제 parent ACTIVE, fresh updateBounds, 일치하는 전체 master geometry/window에서 실제 base updateCosts가 원본 cells를 적용한 뒤에만 applied generation을 만든다. parent의 ACTIVATING 중 첫 update가 발생하는 경우에는 full bounds를 다시 요구한다. 확인은 이후 obstacle/inflation 처리 전 이 layer의 기여를 뜻한다. 최종 master checksum, localization 수렴, 로봇 geometry나 운행 허가가 아니다.

정확한 반복은 재처리·generation 갱신을 하지 않는다. raw 또는 원본 시각 변경은 native map 처리 전에 기존 증거를 영구 폐기한다. 외부 LayeredCostmap resize는 master를 먼저 바꾼 뒤 matchSize를 호출하며, 그 master lock 안에서 layer resize 전에 기존 증거를 폐기한다. reset/ClearEntire는 기존 applied generation을 무효화하고 fresh bounds와 새 full application을 요구한다. rolling/maximum/incremental/volatile/footprint-clearing/disabled/filter profile은 지원하지 않으며, native conversion params를 검증하고 전체 mixed parameter transaction을 inherited callback 전에 거절한다. footprint topic의 통지는 clearing=false인 static cells를 변경하지 않지만 geometry 수용 증거가 되지는 않는다.

plugin destructor는 parent 포인터를 역참조하지 않는다. 정상 parent lifecycle의 callback executor join 뒤 plugin이 해제되는 경로와, 정리 전 실제 callback이 진행 중인 경우를 시험하도록 했다. 잘못된 직접 active destruction이나 rejected configure 뒤 무조건 parent 파괴가 안전하다고 주장하지 않는다. upstream BSD 고지·설치 license와 opt-in plugin 등록을 보존했다. 독립 검토는 source/lock/lifecycle 범위 scoped PASS였으며 실제 실행 수용과 구분한다.

## Revision별 실제 실행

| Revision | 관측 |
|---|---|
| `86c0e72da7` | 시험 전용 RED. 승인 AI 시험 PC에서 같은 SHA interfaces/native navigation 빌드, grid6+AMCL10 및 설치 AMCL smoke PASS. static target/XML 부재로 exit1. static 실제 동작 0건 |
| `00945893a5` | 실제 plugin compile/link/load, 기존16건/설치 smoke PASS. static 앞9건 OK 뒤 disabled profile을 거절하고 부분 구성 parent 파괴 중 CTest180초 timeout. XML은 synthetic missing_result 1 error이며 실제14건 통과가 아님 |
| `f05023d376` | production은 이전 revision과 동일. fixture가 rejected UNCONFIGURED parent의 실제 protected on_cleanup을 호출하고 layered map/plugin 해제를 확인하도록 수정. 자원 기준으로2회 미실행 후 승인 AI에서 실제 실행. 기존16건/설치 smoke PASS, static 앞9건 OK. disabled/rolling 거절·cleanup·destruction은 진행했으나 다음 maximum profile 거절 뒤 cleanup에서 다시180초 timeout. XML missing_result 1 error, exit1 |
| `83db3b1da4` | 실제 고유 TF 수신을 확인하는 fixture 조건만 추가. 같은 SHA interfaces/native navigation 생성·compile/link와 실제 gtest grid6+AMCL10+static14 = **30 PASS/0 FAIL/0 ERROR/0 SKIP**, 설치 standalone AMCL 초기 graph/정상 종료도 별도 PASS, exit0 |

초기 두 실패 revision의 첫9건은 미수신/비활성 buffered original 거절, latched original의 실제 parent full application과 graph, reset 후 fresh bounds/full window, repeat no-renewal, 동일하게 변환되는 다른 raw 거절, 원본 시간 변경, 실제 ClearEntire service, 외부 master resize, mixed parameter 부작용 거절이다. 그 두 revision은 CTest stdout의 개별 OK만 있으며 전체 static XML이 없어14건이나30건 PASS로 계산하지 않는다.

최종 `83db3b1da4ef17ee493fa9849c4a1b87277dd7f5`에서는 source-sha/exit-code와 세 gtest XML을 직접 확인했다. static14건이 정상 종료했으며 거절 profile8개와 부분 구성 정리, 실제 footprint topic, 진행 중 private callback 및 queued readback 뒤 실제 parent cleanup/해제, 새 instance identity, nontrinary/unknown conversion도 포함한다. partial/full/reset의 controlled native 호출은 실제 parent worker를 pause/quiesce한 뒤 수행하며, 별도 activation 시험은 실제 parent update loop의 full application을 사용한다. synthetic TF/map 입력을 현재 로봇 pose/정밀도 수용으로 계산하지 않는다.

부분 구성 실패 뒤 parent의 정리를 건너뛴 fixture 경로는 실제 source/member 순서와 맞았고 첫 수정으로 앞 두 profile의 정리가 진행됐다. 두 번째 timeout은 그 수정만으로 hang 전체가 해결되지 않았다는 증거다. 같은 SHA의 gdb-started 단독 거절 시험은 실제1건 PASS 후 정상 종료해 hang을 재현하지 못했다. 이어 debugger 없이 시작한 자기 child가 멈춘 뒤 같은 parent PID에서 gdb로 attach한 bounded 진단에서는 cleanup의 TransformListener destructor→thread.join과 해당 worker의 Executor::wait_for_work/SingleThreadedExecutor::spin 대기를 확인했다. 그 진단 child만 종료했으며 ptrace 정책은 바꾸지 않았다. 진단 exit0는 시험 수용이 아니다.

`83db3b1da`는 실제 고유 TF가 parent buffer에 수신됐음을 확인한 뒤 정리하도록 fixture만 동기화했다. 고정 sleep·native flag 쓰기나 가짜 callback은 없다. cancel-before-spin의 정확한 발생 순서는 stack만으로 입증하지 않았다. fixture 정리와 동기화 helper는 운영 실패 처리 구현이 아니다. 실제 factory/launch 활성화 전 rejected configure의 자원 정리도 별도로 검증해야 한다.

정확한 SHA의 interfaces 생성/IDL·include provenance, pinned Nav2 1.3.13/rclcpp 28.1.22 및6개 SDK header, source/compiler/build fingerprint를 검사했다. 기존16건과 설치 standalone 초기 graph는 static 결과와 구분한다. 설치 smoke는 추가 gtest가 아니다. 실패 artifact를 EXIT trap에서 보존했다.

원본은 저장소 밖 `C:/DevTemp/station-charge/`의 `native-map-static-86c0e72da7-attempt-1/`, `native-map-static-00945893a5-attempt-1/`, `native-map-static-f05023d376-attempt-3/`, `native-map-static-hang-f05023d376-4/`, `native-map-static-hang-attach-f05023d376-1/`, `native-map-static-83db3b1da4-attempt-1/`에 있다. source-sha/exit-code와 `Testing/Temporary/LastTest_*.log`를 직접 확인했다. 진단의 child stdout·전체 thread backtrace·실제 listener SDK header도 보존했다. 단순 LastTest.log는 마지막 test-result 요약이라 상세 실행 log와 다르다. 자원 기준 미달 요청은 실행 수에 넣지 않는다.

## 남은 검증

`00945893a5` source guard9대상은 208건 중207 PASS/1 FAIL/0 SKIP, known-failure 비교 NEW1이다. 실패는 이전 branch baseline에서도 재현된 safety exception ancestry 한 건이며 현재 main 비교는 이전 검증에서 PASS였다. 테스트/검증기를 약화하지 않았고 전체 guard GREEN이나 main의 기존 실패로 분류하지 않는다. package manifest 변경은 FULL selection이며 FULL CI는 남아 있다.

native14건과 별도로 운영 실패 정리, CORE typed bridge/원본 관측 객체 identity·두 instance/generation·one-use nonce·불변 parent/expiry의 실제 final writer 거절을 연결해야 한다. 승인 Fleet map/좌표 변환, geometry/localization과 지속적인 frame loss 정지, 원본 pack energy/SOC/SOH·reserve, 실제 HTTP/native tickets와 CLOSED factory, 전체3회 복귀·충전·재투입 및 station relocation도 남아 있다.

현장 담당자는 나중에 확인 가능하다. 상부 카메라 시야/extrinsics, 현재 이동 로봇 위치, 착좌/접점, 충전기/BMS 및 watchdog/제동 지연을 아직 수용하지 않았다. 현장 장치 재탐색·이동·토크·서비스 재시작·배포·landing·push는 수행하지 않았다.
