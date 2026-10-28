"""Bind selected-route geometry to an exact odom sample and accepted authority."""

from core_common.protocol.lane_route_guide import AuthorityRouteGuide, SelectedRoutePrior


def bind_guide(raw, *, base, exact, leg_id, seq, now, ttl_s, shrink, budget):
    """Return (binding, source budget). Clears never replenish the last source budget."""
    if raw is None or not exact or base is None or seq is None or shrink:
        return None, budget
    try:
        hint = AuthorityRouteGuide.model_validate(raw)
    except ValueError:
        return None, budget
    age = now - base[6]
    if not 0. <= age < hint.max_age_s:
        return None, budget
    expires = min(base[6] + hint.max_age_s, now + ttl_s)
    if budget is not None and budget[0] == base[1]:
        if base[2] < budget[1]:
            return None, budget
        if base[2] == budget[1]:
            expires = min(expires, budget[2])
    budget = (base[1], base[2], expires)
    if now >= expires:
        return None, budget
    source = base[2] / 1e9
    try:
        prior = SelectedRoutePrior(leg_id=leg_id, authority_seq=seq, source_stamp_s=source,
            valid_until_s=min(source + hint.max_age_s, source + (expires - base[6])),
            **hint.model_dump(exclude={'max_age_s'}))
    except ValueError:  # A sub-ULP source lifetime is no usable directional evidence.
        return None, budget
    return dict(prior=prior, expires_at=expires, stamp_ns=base[2]), budget   # D-573 rev 8: the odom sample
