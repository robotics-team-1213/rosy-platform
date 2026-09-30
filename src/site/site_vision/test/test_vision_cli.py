from overhead.cli import parse_args


def test_vision_command_requires_explicit_camera_config_and_defaults_to_site_ingress():
    args = parse_args(["vision", "--config", "site-cameras.yaml"])

    assert args.command == "vision"
    assert args.config.name == "site-cameras.yaml"
    assert (args.host, args.port) == ("0.0.0.0", 8095)
