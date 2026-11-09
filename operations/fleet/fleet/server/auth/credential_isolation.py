"""Fleet 서버 구성 시 자격 분리 검사 한 묶음 (D-361 4 · D-341 · D-766 분할).

`create_app` 이 부르는 순서 그대로, 서로 다른 서비스의 비밀이 겹치면 `ValueError` 로 막는다.
검사 규칙 자체는 `site_auth` 와 각 라우트 모듈의 `assert_*` 가 갖고, 여기는 무엇을 무엇과 비교할지만 모은다.
"""

from __future__ import annotations

from fleet.server.site_auth import (
    assert_pairing_sync_token_isolated,
    assert_registry_credential_isolated,
    assert_robot_credential_key_isolated,
)


def assert_credentials_isolated(
        *, console, principals, console_token, discovery_token, vision_lease_secret, robot_credential_key,
        pairing_sync_token, workcell_observations, goal_evidence_service, cell_goal_registry,
        cell_goal_evidence_service, sightings, policy_evidence) -> tuple:
    """Check every configured credential against the others; return the tokens other services must also avoid."""
    other_tokens = (console_token, discovery_token, vision_lease_secret, robot_credential_key, pairing_sync_token)
    if workcell_observations is not None:
        from fleet.server.workcell_observation_routes import assert_workcell_observation_credentials_isolated
        evidence_tokens = tuple(producer.token for registry in (
            goal_evidence_service.registry if goal_evidence_service is not None else None, cell_goal_registry)
            if registry is not None for producer in registry.producers)
        assert_workcell_observation_credentials_isolated(
            workcell_observations, console=console, principals=principals,
            other_tokens=other_tokens + evidence_tokens, other_services=(sightings, policy_evidence))
        other_tokens += workcell_observations.credential_values()
    if cell_goal_evidence_service is not None:
        from fleet.server.cell_goal_evidence_routes import assert_cell_producer_credentials_isolated
        if goal_evidence_service is not None:
            other_tokens += tuple(item.token for item in goal_evidence_service.registry.producers)
        assert_cell_producer_credentials_isolated(
            cell_goal_registry, console=console, principals=principals,
            other_tokens=other_tokens, other_services=(sightings, policy_evidence),
        )
    if principals:
        assert_registry_credential_isolated(console_token, principals)
    if robot_credential_key is not None:
        assert_robot_credential_key_isolated(
            robot_credential_key, console_token=console_token,
            discovery_token=discovery_token, vision_lease_secret=vision_lease_secret,
            console=console, sightings=sightings, policy_evidence=policy_evidence,
            principals=principals)
    if pairing_sync_token is not None:
        assert_pairing_sync_token_isolated(
            pairing_sync_token, console_token=console_token, discovery_token=discovery_token,
            vision_lease_secret=vision_lease_secret, robot_credential_key=robot_credential_key,
            console=console, sightings=sightings, policy_evidence=policy_evidence,
            principals=principals)
    return other_tokens
