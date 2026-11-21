"""Cross-document contracts for the network topology decision (ADR D-26).

ADR D-26 supersedes D-19: the robot supports two operating network modes,
``SITE_STA`` (default) and ``RELAY_AP_STA`` (per-device opt-in). Three
documents have to agree on that — the ADR log, the CORE SRS and the ROSY OS
v1 image/release design. They drifted apart once already (D-19 declared
AP+STA the standard topology while the v1 design excluded relay from scope),
so the agreement is pinned here rather than left to review.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "reference" / "ROSY ADR Log.md"
SRS = ROOT / "docs" / "spec" / "ROSY CORE SRS.md"
DESIGN = ROOT / "docs" / "plans" / "2026-09-01-rosy-os-v1-image-release-design.md"
IMPLEMENTATION_PLAN = ROOT / "docs" / "plans" / "ROSY Implementation Plan.md"

CONTRACT_DOCS = (ADR, SRS, DESIGN)

SITE_STA = "SITE_STA"
RELAY = "RELAY_AP_STA"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _adr_text() -> str:
    """Read the ADR index and all split ADR bodies as one logical contract."""
    bodies = sorted((ROOT / "docs" / "adr").glob("*.md"))
    return "\n\n".join([_text(ADR), *(_text(path) for path in bodies)])


def _contract_text(path: Path) -> str:
    return _adr_text() if path == ADR else _text(path)


def _section(text: str, heading: str, level: str = "## ") -> str:
    """The body of one heading, ending at the next heading of the same level.

    Splitting to end-of-file made several checks below vacuous: content that
    had moved into a *later* section still satisfied an assertion about this
    one, so reverting NET-002 to relay-only passed.
    """
    assert heading in text, f"missing heading: {heading}"
    body = text.split(heading, 1)[1]
    marker = "\n" + level
    return body.split(marker, 1)[0] if marker in body else body


@pytest.fixture(scope="module")
def adr() -> str:
    return _adr_text()


@pytest.fixture(scope="module")
def srs() -> str:
    return _text(SRS)


@pytest.fixture(scope="module")
def design() -> str:
    return _text(DESIGN)


def test_contract_documents_exist():
    for path in CONTRACT_DOCS:
        assert path.is_file(), f"missing contract document: {path.relative_to(ROOT)}"


# --- ADR governance -------------------------------------------------------


#: Every superseded decision, and what must survive verbatim in it.
#:
#: This was hardcoded to D-19 alone, which meant the governance rule it claims to
#: enforce protected exactly one decision. Superseding D-6 with D-33 would have gone
#: unguarded — a plan review caught that the mitigation named here did not mitigate.
#: Table-driven now, so adding a supersession means adding a row, not a test.
SUPERSESSIONS = {
    "D-19": {
        "heading": "## D-19 접속 토폴로지: 로봇 WiFi 릴레이(AP+STA) 지원",
        "superseded_by": "D-26",
        "decision": (
            "**Decision:** 해당 토폴로지를 표준 배포 시나리오로 수용한다(NET-001~004)."
        ),
        "context": (
            '현장 네트워크 구성이 "로봇이 상위 WiFi에 연결된 채 AP처럼 동작해 무선을 릴레이"하는'
        ),
        "index_row": (
            "| D-19 | 접속 토폴로지: 로봇 WiFi 릴레이(AP+STA) 지원 | Superseded by D-26 |"
        ),
    },
    "D-6": {
        "heading": "## D-6 로봇 간 DDS 차단",
        "superseded_by": "D-33",
        "decision": (
            "**Decision:** 로봇별 고유 `ROS_DOMAIN_ID` + CycloneDDS localhost-only "
            "프로파일로 로봇 간 DDS를 차단한다. 로봇 간 데이터는 Fleet 경유만."
        ),
        "context": (
            "**Context:** 동일 WiFi에서 다수 로봇의 DDS 디스커버리 트래픽은 "
            "불안정의 주 원인이 된다(SRS §33)."
        ),
        "index_row": "| D-6 | 로봇 간 DDS 차단 (도메인 격리) | Superseded by D-33 |",
    },
}


def test_the_adr_log_still_requires_superseding_rather_than_editing(adr):
    """The governance rule this whole test module rests on."""
    assert "기존 ADR을 수정하지 않고" in adr
    assert "`Superseded`" in adr


@pytest.mark.parametrize("decision_id", sorted(SUPERSESSIONS))
def test_superseded_decisions_are_not_edited_in_place(adr, decision_id):
    """The ADR log's own rule: supersede, never rewrite a decision.

    Asserted verbatim so that editing a superseded record fails rather than
    passing quietly — including its index row, which is a second place the
    status can silently drift.
    """
    entry = SUPERSESSIONS[decision_id]
    section = _section(adr, entry["heading"])

    assert f"**Status:** Superseded by {entry['superseded_by']}" in section, (
        f"{decision_id} must carry its supersession in the Status line"
    )
    assert entry["decision"] in section, (
        f"{decision_id}'s original Decision must survive verbatim; the ADR log "
        f"forbids rewriting a superseded record"
    )
    assert entry["context"] in section, (
        f"{decision_id}'s original Context must survive verbatim"
    )
    assert entry["index_row"] in adr, (
        f"{decision_id}'s index row must record the supersession too"
    )


@pytest.mark.parametrize("decision_id", sorted(SUPERSESSIONS))
def test_every_superseding_decision_exists_and_is_complete(adr, decision_id):
    """A supersession that points at a decision nobody wrote is not a supersession."""
    successor = SUPERSESSIONS[decision_id]["superseded_by"]
    section = _section(adr, f"## {successor} ")
    for heading in ("**Context:**", "**Decision:**", "**Consequences:**"):
        assert heading in section, f"{successor} is missing {heading}"


def test_d26_exists_and_replaces_d19(adr):
    d26 = _section(adr, "## D-26")
    assert "D-19 대체" in d26
    assert SITE_STA in d26 and RELAY in d26
    for heading in ("**Context:**", "**Decision:**", "**Consequences:**"):
        assert heading in d26, f"D-26 is missing {heading}"


def _require_log_rows(missing: list[str]) -> None:
    """D-1061: a PR must not write Log rows, the records bot adds them after merge.

    Missing rows are a warning (PR and main pushes) and an error only when
    ROSY_RECORDS_STRICT=1 (the bot/scheduled run).
    """
    import os
    import warnings

    if not missing:
        return
    msg = f"ADR sections absent from the index table: {missing}"
    assert os.environ.get("ROSY_RECORDS_STRICT") != "1", msg
    warnings.warn(f"{msg} (the records bot adds the rows)", stacklevel=2)


def test_missing_log_rows_warn_unless_strict(monkeypatch):
    monkeypatch.delenv("ROSY_RECORDS_STRICT", raising=False)
    with pytest.warns(UserWarning, match=r"D-1062"):
        _require_log_rows(["D-1062"])
    monkeypatch.setenv("ROSY_RECORDS_STRICT", "1")
    with pytest.raises(AssertionError, match=r"D-1062"):
        _require_log_rows(["D-1062"])
    _require_log_rows([])


def test_adr_index_lists_every_decision_section(adr):
    """The index table went stale at D-22 while D-23..D-25 existed in the body."""
    import re

    body_ids = set(re.findall(r"^## (D-\d+) ", adr, flags=re.MULTILINE))
    index_ids = set(re.findall(r"^\| (D-\d+) \|", adr, flags=re.MULTILINE))
    missing = sorted(body_ids - index_ids, key=lambda s: int(s.split("-")[1]))
    _require_log_rows(missing)


# --- the decision itself --------------------------------------------------


def test_relay_is_in_v1_scope_everywhere():
    """No document may still defer the relay to a follow-on capability."""
    deferrals = (
        "상시 AP+STA 릴레이는 v1 기본이 아니며 후속 Capability로 보류한다",
        "상시 AP+STA relay와 도메인별 응용 기능은 이 완료 정의에",
        "v1 기본 요구에서 제외한다",
    )
    for path in CONTRACT_DOCS:
        text = _contract_text(path)
        for phrase in deferrals:
            assert phrase not in text, (
                f"{path.relative_to(ROOT)} still defers the relay out of v1: {phrase!r}"
            )


#: Wording from the superseded contract. Present anywhere outside D-19's own
#: historical record, it means the old decision has crept back in alongside
#: the new one — which is how two contradictory contracts coexist unnoticed.
SUPERSEDED_WORDING = (
    "표준 배포 시나리오",
    "WiFi 릴레이 모드 (AP+STA 동시)",
    "## 3.1 네트워크 접속 (WiFi 릴레이 토폴로지)",
)


def test_the_superseded_contract_does_not_survive_outside_d19(adr, srs, design):
    """Adding the new decision is not enough; the old one has to stop applying."""
    adr_outside_d19 = adr.replace(
        _section(adr, "## D-19 접속 토폴로지: 로봇 WiFi 릴레이(AP+STA) 지원"), ""
    )
    for phrase in SUPERSEDED_WORDING:
        assert phrase not in srs, f"SRS still carries the superseded contract: {phrase!r}"
        assert phrase not in design, f"design still carries the superseded contract: {phrase!r}"
        assert phrase not in adr_outside_d19, (
            f"the superseded contract appears outside D-19's record: {phrase!r}"
        )


def test_the_srs_does_not_declare_relay_the_default(srs):
    section = _section(srs, "## 3.1 ")
    assert "기본값은 `SITE_STA`" in section
    for claim in ("릴레이를 기본으로", "기본은 릴레이", "기본값은 `RELAY_AP_STA`"):
        assert claim not in section, f"SRS contradicts D-26: {claim!r}"


def test_both_modes_named_in_every_contract_document():
    for path in CONTRACT_DOCS:
        text = _contract_text(path)
        assert SITE_STA in text, f"{path.relative_to(ROOT)} does not name {SITE_STA}"
        assert RELAY in text, f"{path.relative_to(ROOT)} does not name {RELAY}"


def test_site_sta_is_declared_the_default(adr, srs, design):
    assert "`SITE_STA` — **기본값.**" in adr
    assert "기본값은 `SITE_STA`이며 릴레이는 장비별로 명시적으로 켠다" in srs
    assert "설정이 없으면 `SITE_STA`로 기동한다" in srs
    assert "운용 네트워크 모드는 `SITE_STA`와 `RELAY_AP_STA` 두 가지이며 기본은 `SITE_STA`다" in design


def test_relay_is_declared_opt_in(adr, srs, design):
    assert "**장비별 옵트인.**" in adr
    assert "장비별 옵트인" in srs
    assert "장비별 옵트인으로 한다" in design


def _flat(text: str) -> str:
    """Collapse whitespace so a neutral reflow does not fail an assertion."""
    return " ".join(text.split())


def test_both_modes_share_the_first_boot_provisioning_ap(adr, srs, design):
    assert "동일한 첫 부팅 설정 AP" in adr
    assert "두 모드 모두 동일한 첫 부팅 설정 AP로 프로비저닝된다" in srs
    assert "두 운용 모드 어느 쪽으로 갈지는 프로비저닝 단계에서 선택" in _flat(design)


def test_provisioning_ap_is_separate_from_the_operating_relay_ap(srs, design):
    """The setup AP and the relay AP are different profiles with different lifetimes."""
    assert "### NET-005" in srs
    net005 = srs.split("### NET-005", 1)[1]
    assert "설정 AP의 자격정보를 재사용해서는 안 된다" in net005
    assert "설정 AP의 자격정보를 운용 AP가 재사용하지 않는다" in design


# --- downstream consistency ----------------------------------------------


def test_net_002_and_003_are_stated_for_both_modes(srs):
    """The acceptance criterion verbatim, and it was not being checked.

    Reverting NET-002 from "두 모드 모두에서" to "릴레이 모드에서" passed every
    assertion in this file, which is the criterion US-001 states outright.
    """
    section = _section(srs, "## 3.1 ")

    net002 = section.split("### NET-002", 1)[1].split("### NET-003", 1)[0]
    assert "두 모드 모두에서" in net002, "NET-002 must hold in both modes, not only the relay"
    assert SITE_STA in net002 and RELAY in net002

    net003 = section.split("### NET-003", 1)[1].split("### NET-004", 1)[0]
    assert SITE_STA in net003 and RELAY in net003, (
        "NET-003 must say where local control holds in each mode; they fail differently"
    )

    net004 = section.split("### NET-004", 1)[1].split("### NET-005", 1)[0]
    assert "릴레이 NAT" in net004 and "사업장 WLAN" in net004, (
        "NET-004 must cover the NAT of both topologies"
    )


def _default_claims(section: str) -> list[str]:
    """Sentences in ``section`` that state which mode is the default.

    A sentence qualifies when it says "기본" and names a mode. Counting these
    is what a denylist of phrases cannot do: a paraphrase of the superseded
    claim matches no listed string, but it is still a second sentence saying
    a different mode is the default.
    """
    import re

    sentences = re.split(r"(?<=[.!?다])\s+|\n\n", section)
    # Not only 기본: a claim can assert a default without the word. "표준
    # 토폴로지로 채택한다" and "자체 AP를 상시 운용한다" both say which mode
    # the device runs by default while avoiding it entirely.
    markers = ("기본", "표준", "항상", "상시")
    return [
        " ".join(s.split())
        for s in sentences
        if any(m in s for m in markers) and (SITE_STA in s or RELAY in s or "릴레이" in s)
    ]


def test_the_srs_states_exactly_one_default_mode(srs):
    """Adding the new decision does not help if the old one is re-added beside it.

    The previous version listed five superseded phrases and checked for their
    absence. A denylist of literals cannot enforce the absence of a claim —
    "릴레이(AP+STA)를 표준 토폴로지로 하며 기본으로 켠다" matches none of them
    and contradicts D-26 just as squarely. Counting default-statements does.
    """
    claims = _default_claims(_section(srs, "## 3.1 "))

    assert claims, "the SRS must state which mode is the default"
    for claim in claims:
        assert SITE_STA in claim, (
            f"a default is claimed for something other than SITE_STA: {claim!r}"
        )


def test_srs_net_requirements_cover_both_modes(srs):
    section = _section(srs, "## 3.1 ").split("### IDN-003", 1)[0]
    for req in ("NET-001", "NET-002", "NET-003", "NET-004", "NET-005"):
        assert f"### {req}" in section, f"{req} missing from SRS 3.1"

    # NET-003 must state where "local stays up" holds in each mode, because the
    # two modes fail differently: relay keeps its own subnet, STA depends on the
    # site router not isolating clients.
    net003 = section.split("### NET-003", 1)[1].split("### NET-004", 1)[0]
    assert "client isolation" in net003
    assert "로봇 AP 서브넷" in net003


def test_design_state_machine_offers_both_operating_modes(design):
    machine = design.split("### 8.1 네트워크 모드", 1)[1].split("### 8.2", 1)[0]
    assert "-> SITE_STA" in machine
    assert "-> RELAY_AP_STA" in machine
    assert "PROVISIONING_AP" in machine


def test_dashboard_network_card_shows_the_relay_mode(design):
    """A mode the runtime can enter but the dashboard cannot name is a blind spot."""
    card = design.split("### 10.2 네트워크", 1)[1].split("### 10.3", 1)[0]
    for mode in ("PROVISIONING_AP", SITE_STA, RELAY, "RECOVERY_AP"):
        assert mode in card, f"dashboard network card omits {mode}"


def test_design_points_at_the_superseding_adr(design):
    assert "ADR D-26" in design
    assert "D-19를 D-26으로 대체" in design


def test_the_implementation_plan_points_at_the_current_decision():
    """A plan still citing D-19 will be executed against the old contract.

    This file is not in CONTRACT_DOCS above because it is a schedule rather
    than a contract, but it names the decision it implements, and that name
    has to be the one still in force.
    """
    text = _text(IMPLEMENTATION_PLAN)
    for line in text.splitlines():
        if "D-19" in line:
            assert "D-26" in line, (
                f"the implementation plan cites D-19 without D-26: {line.strip()!r}"
            )


def test_the_design_header_names_the_decision_in_force(design):
    header = design.split("## 1.", 1)[0]
    assert "D-26" in header, "the design's Related list must name D-26, not only D-19"
