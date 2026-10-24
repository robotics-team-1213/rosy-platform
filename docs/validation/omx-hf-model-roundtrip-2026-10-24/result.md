# OMX 실제 학습 모델의 private HF 전달과 새 ACT 재적재

기존10k-step SIM 모델을 `robotteam/rosy-omx-policy` private 저장소에 전달하고
commit `5c58cf5663f1fc713a393c902a1e0ba4050c676f`의 다운로드본만으로 새 프로세스에서
ACTInference를 재적재했다. 이는 모델 바이트 전달과 숫자 추론 수용이며 정책 task 성공·
장치 실행·승격은 아니다. 정책 품질은 HOLD다.
[데이터 왕복 검증](../omx-hf-private-roundtrip-2026-10-24/result.md) 이후의 별도 기록이다.

## 고정 입력과 실제 결과

소스 commit `73fc8b2b09cbefa6aee22a786ca2b418a8e979b8`의 기존 hub_sync와 ACTInference를
사용했다. 실제 학습5파일45384876bytes와 SIM/research/HOLD를 밝힌595byte 카드를
선택했다. 모델 파일은 재학습·변환하지 않았으며6파일의 해시를 모두 고정했다.
policy revision sha256: `30bba42551e85be5007d45fcef6a7e36268bad711d8bd85905ad383113cc1326`.
이 모델은 native_cycle checkpoint 형식이 아니므로 기존 ACTInference를 소비자로 썼다.

개인 namespace robotteam 인증을 확인하고 named private model repo만 생성했다.
초기 파일 목록은 캡처한40자 commit SHA에서 최대 `.gitattributes`만 허용했다.
실제 create_commit parent를 그 SHA로 제한하고 이후 변경은 Hub CAS로 거절한다.
업로드한 불변 revision의6파일 SHA를 모두 재검사했다. model bundle의
upload_bundle reader_verified는 false다. OMX dataset reader를 실행한 것으로
취급하지 않고 별도 ACTInference child의 실제 재적재 결과를 수용했다.

원래 검증 에피소드 `e30b53c4-ec05-4e94-a010-de2734766043`의 첫 샘플을 썼다.
HF 쓰기 전에 원본 reload proof·첫 sample 행·PNG 파일·복호화 RGB·shape·정규화
결속을 검사했다. child에는 다운로드 readback root만 모델 경로로 전달했다.
child proof의 sample/RGB/정규화 SHA가 원래 proof와 같고, 서로 다른 PID에서
유한한6관절 출력·chunk_index0·consumed_current=true를 확인했다.
RGB frame SHA는 PNG 파일 해시와 다른, 복호화 RGB bytes의 SHA다.
fixture의 합성 시계·lease는 숫자 재적재용이며 실행 owner의 시각·권한 수용을 뜻하지 않는다.
숫자 추론1회, optimizer step·로봇 명령·physics actor는 모두0이다.

## 중단 보존과 직렬화 수정

첫 모델 실행은 Windows에서 검토한 README의14CRLF를 Linux에서14LF로 재생성해
manifest 검사에서 중단됐다. 원래 모델5파일은 일치했다. 카드의 정확한 bytes를
보존한 다음 실행은6파일 전체가 일치했지만 manifest JSON 자체의12CRLF/LF 차이로
중단됐다. 두 실행 모두 preflight·저장소 생성·업로드 전이며 실패·claim·산출물을 보존했다.
문제는 Windows raw preview manifest SHA를 Linux 재생성 manifest SHA와 같다고
가정한 것이다. payload bytes와 manifest JSON 내용의 동일성은 실제 비교해 확인했다.

카드는 write_bytes로 보존하고, 검토한 같은 문서를 UTF8·ensure_ascii=false·indent2·
allow_nan=false·끝 LF로 직렬화한 manifest SHA를 별도로 고정했다. 최상위 키는
repo_id→repo_type→files 순서, files 키는 상대 경로 오름차순으로 고정했다. 모델6파일의
경로·내용·해시는 바꾸지 않았다. 최종 actor-free 검사는 이 문서를 다시 구성해
고정 SHA와 비교한다. assertion 진단에는 예외 본문 대신 basename/line만 남긴다.

카드 byte 보존 절차의 최초 배치 요청은 모델 PC 가용 메모리6.8GiB가8GiB 기준보다 낮아
NOT_SUBMITTED로 끝났다. durable metadata가 없고 실행이 없음을 보존한 뒤,
가용12.8GiB를 확인해 별도1회 placement claim으로 재개했다. 실제 제출된 실패
actor를 재제출한 것이 아니며 추가 실패 원인 확인 후 새로운 고정 프로토콜을 사용했다.

최종 official durable SDK actor는 model8CPU/6GiB/20분 제한에서 PASS/terminal rc0,
private 상태와 scope inactive·빈 cgroup·lock/reservation 해제를 확인했다.
SDK10패키지 버전과 NumPy/PIL/SciPy 실제 import 위치를 검사했다.
실행별 prefix는 OUT/tmp/science에 두어 표준 종료 정리가 회수 전에 제거한다.
공유 venv는 바꾸지 않았다. 실제 HF protocol은 두 독립 검토를 통과했고,
최종 actor-free 검사10개와 launcher 검사7개가 통과했다.
coordinator도 EXIT0으로 끝나 전체 로컬 회수를 완료했다. 회수한 payload/readback
각6파일45385471bytes의 SHA를 다시 비교했다. receipt/result/closure와 child stdout의
proof가 같으며, 입력 해시와6개 출력 수치도 원래 reload proof와 정확히 같다.
이 사후 대조는 추가 추론을 실행하지 않았다.

## 결속 산출물

외부 BASE: `C:/DevTemp/learning-execution-20261023/`.
준비 묶음은 `hf-model-prepare-20261024/`, 초기 실패는 `hf-model-roundtrip-20261024/`,
카드 byte 실행은 `hf-model-roundtrip-bytes-20261024/`, 최종 프로토콜은
`hf-model-roundtrip-canonical-20261024/`에 보존했다.
전체 출력 경로는 각각 `C:/DevTemp/hf-m-20261024/out/`, `hf-m2-20261024/out/`,
최종 `C:/DevTemp/hf-m3-20261024/out/`이다.

| 산출물 | SHA-256 |
|---|---|
| Windows preview manifest 원본 | `56440629fd060fef9a9e11670efc447cb9cffe9bcbf9736c890959fc3351766b` |
| 같은 내용의 canonical manifest | `b6b3268d17669b037e8d6fa1810f1935e60142568a215ebee5c46f3c5f931f19` |
| README 원본 bytes | `4d04bcc44fa19263a3c705476901fc233c724e786474f471954f924ae2ba621e` |
| 원래 별도 프로세스 reload proof | `69bf18578fc09277872c15efc2a31e7bdb700a848746604cc759562c668fcf12` |
| 원래 first sample 행 | `eb7699026b8ecc9846d10bad907b39901cd4ef563425c024eada24a57ea035d6` |
| 원래 decoded RGB frame | `803daa7fe6dcf177c1725c4df85f21e47b64b3def0151ea88c4f50bd701e1ded` |
| normalization.json | `4472c7d3633b8f88830750480a69e2734d83018652ad316144ba53ccc66bc3db` |
| 고정 reload program | `06f2ef27748493d85a9540a1a254b32ac8df17214097ba96345c75d4c5451de8` |
| 최종 worker.py | `d58a7b76105cbe2e6949b7d5581c927cbf23948063d2070a33b0cc3fafe7b391` |
| 최종 run.py | `7c1519985dfe15ce80c707bf4f5f609c6a65af7134bbf22bc28c7829d7f76577` |
| 최종 receipt.json | `9bd88c595902186c02c930786e97a0efd59de06bdc93d09afc0148516ea5443d` |
| 최종 result.json | `113bfce0ca65898f686076c74a34d58c5dc9daf7b9a0ee6091fd3bbed01329c4` |
| 최종 closure.json | `f37676c05f2131134d9a1e93390eae628a724c0e7fff022f1008728014efefbe` |
| 최종 reload.stdout | `bc9f4c65ba57164c138b1c57849a623f53aa0fbd812b9a2d5cbfc315f141a674` |
| 최종 local-verification.json | `5c900f877f1c5dc0b1cfb45dead150de2241c6cbaab3534b4e42820751476c2c` |
| 첫 실패 closure.json | `bb894051ddac754160349ae38c500fb22ba20e8ae7782bd77e1038f846be759d` |
| 첫 실패 manifest-diagnosis.json | `3af4d2c50dd0444bee353707abab32a4592acc97f489c9ee83db6e98881288e3` |

## 수용 한계와 다음 작업

실제 HF 모델 전달·새 숫자 재적재를 확인했다. 독립 SIM task 성공·반복 수용,
12관절 양팔 실행 owner 수용, 사람 라벨·실물 데이터 및 주행 learned adapter의
수용은 남아 있다. 기존 모델의 offline_only 평가와 정책 HOLD를 변경하지 않았다.
새 Learning Center 서비스 배포·GitHub push·로봇 정책 활성화는 하지 않았다.
