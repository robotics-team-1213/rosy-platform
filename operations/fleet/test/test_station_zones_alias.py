from fleet.pipeline.station_zones import load_station_zones, resolve_site_alias


def test_alias_table():
    assert resolve_site_alias("EXP_S1") == "stand:r1-s1"
    assert resolve_site_alias("EXP_S5_PALLET") == "stand:r1-s1"
    assert resolve_site_alias("EXP_S3_BELT") == "not_places:belt"
    assert resolve_site_alias("STG_C2") is None
    assert resolve_site_alias("STG_S3_WAIT") is None
    assert resolve_site_alias("nope") is None


def test_every_yaml_zone_is_aliased_and_yaml_unchanged():
    zones = load_station_zones()
    for zid in zones["zones_by_id"]:
        assert zid in ("EXP_S1", "EXP_S5_PALLET", "EXP_S3_BELT", "STG_C2", "STG_S3_WAIT")
    assert zones["schema"] == "rosy.station-zones.v1"
