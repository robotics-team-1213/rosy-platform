"""Generated Python wire check; run only in the same-SHA ROS build overlay."""
from interfaces.srv import MapAdoption
from rclpy.serialization import deserialize_message, serialize_message
from rosidl_runtime_py.utilities import get_service


def main():
    assert get_service('interfaces/srv/MapAdoption') is MapAdoption
    request = MapAdoption.Request(challenge=list(range(1, 17)))
    copy = deserialize_message(serialize_message(request), MapAdoption.Request)
    assert copy == request
    response = MapAdoption.Response(
        contract_version=MapAdoption.Response.CONTRACT_VERSION,
        challenge=request.challenge,
        active=False, adopted=False, reason='wire_fixture_not_native_adoption')
    copy = deserialize_message(serialize_message(response), MapAdoption.Response)
    assert copy == response and copy.contract_version == 1
    assert not copy.active and not copy.adopted
    fields = MapAdoption.Response.get_fields_and_field_types()
    for name, bound in (
        ('reason', 64), ('role', 32), ('node_fqn', 256), ('build_id', 64),
        ('config_digest', 64), ('grid_digest', 64), ('frame_id', 128),
    ):
        # Generated Jazzy metadata uses string<N>, unlike .srv string<=N.
        assert fields[name] == f'string<{bound}>', (name, fields[name])
    print('native_map_wire_python: request and closed response round trips passed')


if __name__ == '__main__':
    main()
