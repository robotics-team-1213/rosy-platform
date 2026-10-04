# D-427 wave5 후속 서명·오프라인 검증 기록

이 기록은 [앞선 unsigned 산출물 검증](wave5-arm64-artifact-verification-2026-10-04.md) 이후 확인한 증거다. 산출물 소스는 `1722ca6ec6d7`, 후보 릴리스는 `2026.10.04-035`다. 앞선 dispatch·unsigned 기록은 당시 결과를 보존한다.

## 네이티브 릴리스 서명

기존 prepare 도구의 실제 ABI 검사가 성공한 뒤 tar에서 추출·서명·pack을 완료했다. 확인된 site PC를 경유한 SSH는 원래 로봇의 키와 pinned known-host identity를 유지했고 실제 응답을 그대로 검사했다. `--skip-abi`를 사용하지 않았다. 비교한 공통 ROS 패키지 314개는 버전이 일치했고 불일치는 0개, 후보에만 있는 패키지는 28개다. 후보의 342개 패키지가 모두 현재 로봇에 설치됐다는 뜻은 아니다.

서명된 tar는 49,550,746 bytes, 2,879 members이며 SHA256은 `b6aa5192f84cfd4c02c6510c5b67a021c613943c87086fb02b84dc5bf8802df4`다. 독립 검토는 신뢰된 공개키로 실제 Ed25519 서명을 확인하고 2,548 checksum·2,547 manifest 파일 해시를 전부 검사했다. unsigned tar의 모든 기존 bytes와 Linux mode가 유지됐고 추가된 항목은 signature 파일 하나다. 로컬 서명·pack 검증이며 발행·활성화·기기 수용은 미완료다.

## SD 이미지 실제 내부 파일 검증

같은 이미지의 root partition 12,331,898,880 bytes 전체 Windows SHA256 검사는 통과했다. SHA256은 `8b8cb1d88c2d5e06a57a6fed60c5ba53abc5434f8a860eb6d8ecacea84b51161`다. 최초 GNU hash 작업은 실제 ENOMEM 오류로 종료했다. 그 실패를 보존하고 전체 bytes 검사 후 read-only debugfs로 새 디렉터리에 factory release를 추출했으며 실제 exit 0으로 종료했다. diagnostics에는 debugfs version 외 오류가 없었다. 추출한 실제 파일 2,547개 manifest 해시와 2,548개 SHA256SUMS 항목 전부를 검사했다. exported manifest·SHA256SUMS bytes가 같고 누락·추가·symlink·special 파일이 없다. native와 SD의 설치된 Python·JS 파일 743개도 실제 bytes가 같다. 646개 manifest 해시 차이는 기존 기록과 같다. SD는 unsigned이며 모든 ARM 실행 파일의 동등성·부팅·DEVICE/FIELD 수용을 증명하지 않는다. 독립 검토도 실제 bytes 전체 해시와 743개 Python·JS 일치를 재검사해 APPROVE했다.

## 사이트 PC와 발행 경계

private inventory와 실제 SSH hostname으로 의도한 site PC를 확인했다. 기존 installer·wrapper·service·timer·watcher 5개 파일은 검증 소스와 해시가 같고 실제 installer dry-run은 exit 0이었다. timer는 not-found/inactive이며 기본 config와 설치 디렉터리는 실제 stat의 ENOENT로 부재를 확인했다. 비대화식 sudo는 인증이 필요하다는 이유로 거절되어 재설치는 NOT_RUN이다. 다른 세션이 준비한 관리자 script와 기존 자격증명은 보존했다. dry-run은 설치·timer 동작·journal 수용을 대신하지 않는다.

서명 전 읽기 전용 조회는 현재 033 release와 CORE·IO active, 035 디렉터리 부재를 확인했다. 후속 자동 업데이트 상태 조회 한 번은 SSH banner exchange timeout(exit 255)으로 끝났다. 이후 독립 검토를 통과한 실제 SSH 경로에서 hostname·자동 업데이트 상태 조회가 모두 exit 0이었다. 현재 release는 033, candidate는 null, updater phase는 idle이며 no newer release를 보고했다. 이 상태는 사람의 로봇 사용 확인을 대신하지 않으며, 발행 직전 현재 상태와 guard는 다시 확인해야 한다. 원격 035 tag는 후속 조회에서도 없었다. 로봇 사용 세션 조율과 현재 guard 확인이 남아 있으며 발행·자동 활성화는 실행하지 않았다. peer 안내는 실제 Rosy 전달 채널이 없어 NOT_SENT다. 펌웨어 S7은 다음 개정이며 flash·motion·E-Stop reset을 실행하지 않았다.

## 로컬 증거 위치

일회성 검증 자료는 `X:/DevTemp/rosy-d427/resume/`에 보존했다. `wave5-signed-payload-result.json`, `wave5-signed-native-independent-review.md`, `wave5-rootfs-windows-full-sha256.json`, `wave5-sd-factory-readback-result.json`, `wave5-sd-offline-actual-independent-review.md`, `wave5-publisher-transport-independent-review.md`, `wave5-sitepc-model-watch-readiness.json`에 각 범위의 결과가 있다. private SSH 원문은 공개 저장소에 넣지 않았다.
