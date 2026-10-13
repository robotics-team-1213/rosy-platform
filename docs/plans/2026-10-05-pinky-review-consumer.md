# Pinky 검수 현재 결정의 학습 PC 전달

GUI owner의 `rosy.pinky-review-decisions/1`과 `rosy.pinky-review-export/2`를 소비한다.
기존 object-review COMPLETE는 과거 검수 증거이며 최신 승인 권한이 아니다.

## 설계

- GUI는 일관된 SQLite snapshot, 클래스·이미지·마스크 binding과 이중 봉인을 만든다.
- 소비 verifier는 workspace pin, 명시 generation/digest, 전체 결정 일치 및 파일 해시를 확인한다.
- bridge는 Windows localhost의 현재 결정을 조회하고 승인된 SSH peer로 전달한다.
  모델 PC가 자기 localhost에서 GUI를 찾도록 하지 않는다.
- v2 전송은 AUTHORITY_COMPLETE를 기다리고 legacy manifest 대신 contract SHA로 중복을 판단한다.
  두 봉인과 그 파일 합집합을 전달한다. legacy-only 전송은 계속 검수 증거로만 남긴다.
- 현재 결정은 remote reviews의 `.authority/current.json`으로 atomic replace 한다.
  모델 PC는 고정 workspace와 설정된 최대 나이로 검증한다. 조회 실패는 unavailable로 전달하고,
  전송도 실패하면 기존 확인의 TTL이 끝나 새 자격 부여를 막는다.
- 반복 학습기는 현재 결정과 일치하는 v2 export만 현재 검수 큐에 넣는다.
  객체 승인·마스크 승인·dataset build 자격·모델 수용은 서로 별개이다.
  이번 단계는 mask를 자동 학습 자료로 변환하거나 READY/주행 권한을 만들지 않는다.

서명 없는 임의 파일이나 export 디렉터리의 도착 순서를 현재 권한으로 사용하지 않는다.
workspace가 바뀌거나 generation이 후퇴하거나 같은 generation의 digest가 다르면 보류한다.
현재 결정 전달이 지연된 동안에는 과거 확인으로 새 검수 자격을 부여하지 않는다.

## 소유권과 검증

GUI producer는 기존 review-cycle owner가 수정한다. root는 bridge/cycle/문서 및 그 테스트,
policy reviewer는 신규 review_authority.py와 그 테스트를 소유한다.
격리된 fixture로 mask-only revision, 제외·철회, out-of-order, same-generation conflict,
partial seals, 현재 조회/전송 장애, 원격 atomic replace와 해시를 검증한다.
실제 GUI export/browser 근거 도착 후 독립 연결 검증한다. 로컬 pytest는 현장 수용을 대신하지 않는다.
