"""robots.yaml — 오케스트레이터가 아는 로봇 목록. 토큰은 로봇마다 다르다(D-30)."""

import pytest

from fleet.swarm.robots import RobotEndpoint, RobotsFileError, load_robots, write_robots, ws_url


def test_load_reads_every_field_and_strips_the_trailing_slash(tmp_path):
    p = tmp_path / "robots.yaml"
    p.write_text(
        "robots:\n"
        "  - robot_id: rosy_01\n"
        "    base_url: http://10.0.0.11:8080/\n"
        "    token: tok-1\n"
        "  - robot_id: rosy_02\n"
        "    base_url: http://10.0.0.12:8080\n"
        "    token: tok-2\n",
        encoding="utf-8",
    )
    assert load_robots(p) == [
        RobotEndpoint("rosy_01", "http://10.0.0.11:8080", "tok-1"),
        RobotEndpoint("rosy_02", "http://10.0.0.12:8080", "tok-2"),
    ]


def test_write_then_load_round_trips(tmp_path):
    p = tmp_path / "robots.yaml"
    robots = [RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "a"),
              RobotEndpoint("rosy_02", "http://127.0.0.1:8081", "b")]
    write_robots(p, robots)
    assert load_robots(p) == robots


def test_fleet_agent_pairing_secret_round_trips_separately_from_rest_token(tmp_path):
    p = tmp_path / "robots.yaml"
    endpoint = RobotEndpoint("rosy_01", "https://robot.local", "rest-operator",
                             fleet_pairing_token="agent-pairing")

    write_robots(p, [endpoint])

    assert load_robots(p) == [endpoint]
    assert "rest-operator" in p.read_text(encoding="utf-8")
    assert "agent-pairing" in p.read_text(encoding="utf-8")


def test_fleet_pairing_secret_must_not_reuse_the_rest_operator_token(tmp_path):
    p = tmp_path / "robots.yaml"
    with pytest.raises(RobotsFileError, match="must differ"):
        write_robots(p, [RobotEndpoint("rosy_01", "https://robot.local", "same-secret",
                                       fleet_pairing_token="same-secret")])
    assert not p.exists()


@pytest.mark.parametrize("body", [
    "",
    "robots: []\n",
    "robots:\n  - robot_id: rosy_01\n    base_url: http://x:8080\n",           # token 없음
    "robots:\n  - robot_id: rosy_01\n    token: t\n",                          # base_url 없음
    "robots:\n  - base_url: http://x:8080\n    token: t\n",                    # robot_id 없음
    "robots:\n  - {robot_id: a, base_url: http://x, token: t}\n"
    "  - {robot_id: a, base_url: http://y, token: t}\n",                       # 중복
])
def test_malformed_files_are_refused(tmp_path, body):
    p = tmp_path / "robots.yaml"
    p.write_text(body, encoding="utf-8")
    with pytest.raises(RobotsFileError):
        load_robots(p)


def test_a_missing_file_is_a_robots_file_error_not_an_os_error(tmp_path):
    with pytest.raises(RobotsFileError):
        load_robots(tmp_path / "does-not-exist.yaml")


def test_invalid_yaml_is_a_robots_file_error_not_a_yaml_error(tmp_path):
    p = tmp_path / "robots.yaml"
    p.write_text("robots: [\n  - unclosed\n", encoding="utf-8")
    with pytest.raises(RobotsFileError):
        load_robots(p)


def test_ws_url_switches_scheme_and_carries_the_token():
    assert ws_url("http://10.0.0.11:8080", "/ws/swarm/pose", "t") == "ws://10.0.0.11:8080/ws/swarm/pose?token=t"
    assert ws_url("https://rosy-01.local", "/ws/events", "t") == "wss://rosy-01.local/ws/events?token=t"


def test_ws_url_appends_extra_query():
    got = ws_url("http://h:1", "/ws/events", "t", types="nav.*,swarm.*")
    assert got == "ws://h:1/ws/events?token=t&types=nav.%2A%2Cswarm.%2A"


def test_an_undecodable_file_is_a_robots_file_error(tmp_path):
    p = tmp_path / "robots.yaml"
    p.write_bytes(b"robots:\n  - robot_id: \xff\xfe\n")
    with pytest.raises(RobotsFileError):
        load_robots(p)


@pytest.mark.parametrize("body", [
    "robots:\n  - {robot_id: a, base_url: 10.0.0.11:8080, token: t}\n",     # 스킴 없음
    "robots:\n  - {robot_id: a, base_url: 8080, token: t}\n",               # base_url 이 정수
    "robots:\n  - {robot_id: a, base_url: http://x, token: 01234567}\n",    # YAML 8진수 → int
    "robots:\n  - {robot_id: a, base_url: http://x, token: yes}\n",         # YAML bool
])
def test_a_scheme_less_url_or_a_non_string_secret_is_refused(tmp_path, body):
    p = tmp_path / "robots.yaml"
    p.write_text(body, encoding="utf-8")
    with pytest.raises(RobotsFileError):
        load_robots(p)


def test_a_numeric_robot_id_is_accepted_as_text(tmp_path):
    p = tmp_path / "robots.yaml"
    p.write_text("robots:\n  - {robot_id: 7, base_url: http://x, token: t}\n", encoding="utf-8")
    assert load_robots(p)[0].robot_id == "7"


def test_write_refuses_what_load_would_refuse(tmp_path):
    p = tmp_path / "robots.yaml"
    with pytest.raises(RobotsFileError):
        write_robots(p, [RobotEndpoint("", "http://x", "t")])
    with pytest.raises(RobotsFileError):
        write_robots(p, [RobotEndpoint("a", "http://x", "t"), RobotEndpoint("a", "http://y", "t")])
    with pytest.raises(RobotsFileError):
        write_robots(p, [RobotEndpoint("a", "10.0.0.11:8080", "t")])
    with pytest.raises(RobotsFileError):
        write_robots(p, [RobotEndpoint("a", "http://x", 1234)])
    assert not p.exists()


def test_write_normalizes_the_trailing_slash_so_the_round_trip_is_stable(tmp_path):
    p = tmp_path / "robots.yaml"
    write_robots(p, [RobotEndpoint("a", "http://x/", "t")])
    assert load_robots(p) == [RobotEndpoint("a", "http://x", "t")]


def test_ws_url_upper_case_https_is_still_secure_and_unknown_schemes_are_refused():
    assert ws_url("HTTPS://rosy.local", "/ws/events", "t").startswith("wss://")
    with pytest.raises(ValueError):
        ws_url("ftp://rosy.local", "/ws/events", "t")
    with pytest.raises(ValueError):
        ws_url("10.0.0.11:8080", "/ws/events", "t")
