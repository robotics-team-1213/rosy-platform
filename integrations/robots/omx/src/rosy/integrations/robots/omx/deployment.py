"""Read-only deployment preparation; this report never grants execution authority."""
import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path


def deployment_report(cfg, *, target):
    from lerobot_robot_rosy_omx import RosyOmx, RosyOmxConfig, validate_record_config

    if target not in ('sim', 'real') or not isinstance(cfg.robot, RosyOmxConfig):
        raise ValueError('explicit sim/real target and rosy_omx Robot required')
    if version('lerobot') != '0.4.4':
        raise ValueError('deployment requires the verified LeRobot 0.4.4 environment')
    validate_record_config(cfg)
    artifacts = {}
    if cfg.policy is not None:
        root = Path(cfg.policy.pretrained_path).resolve(strict=True)
        if not root.is_dir() or not (root/'model.safetensors').is_file() or not (root/'config.json').is_file():
            raise ValueError('a complete local ACT checkpoint is required')
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                raise ValueError('checkpoint links are not deployable immutable files')
            if path.is_file():
                with path.open('rb') as content:
                    artifacts[path.relative_to(root).as_posix()] = hashlib.file_digest(content, 'sha256').hexdigest()
    robot = RosyOmx(cfg.robot)
    blockers = []
    if target == 'real':
        blockers = ['PHYSICAL_POLICY_RUNTIME_CLOSED', 'FLEET_DEVICE_LEASE_NOT_CONNECTED',
                    'D793_APPROVAL_AND_PHYSICAL_ACCEPTANCE_REQUIRED']
    core_ready = False
    try:
        robot.connect()  # GET policy only; disconnect would stop the shared session.
        core_ready = True
    except (OSError, RuntimeError, ValueError, KeyError):
        blockers.append('CORE_ARM_UNAVAILABLE_OR_INCOMPATIBLE')
    return dict(schema='rosy.omx-deployment-preflight.v1', target=target, ready=not blockers,
                policy_revision=cfg.robot.policy_revision, checkpoint_sha256=artifacts,
                blockers=blockers, core_ready=core_ready,
                simulation=robot._client.info['simulation'] if core_ready else None,
                device_execution=False, approval=False, deployment=False,
                scope='configuration and CORE SIM I/O readiness; not policy qualification or physical admission')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, choices=('sim', 'real'))
    parser.add_argument('--config', required=True, type=Path, help='private LeRobot RecordConfig JSON')
    parser.add_argument('--out', required=True, type=Path, help='new private report path')
    args = parser.parse_args(argv)
    try:
        import draccus
        import lerobot_robot_rosy_omx  # Register the optional Robot before decoding.
        from lerobot.scripts.lerobot_record import RecordConfig

        cfg = draccus.decode(RecordConfig, json.loads(args.config.read_text(encoding='utf-8')))
        result = deployment_report(cfg, target=args.target)
        with args.out.open('x', encoding='utf-8') as output:
            json.dump(result, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write('\n')
    except (ValueError, OSError, RuntimeError, ImportError, TypeError) as exc:
        parser.exit(2, f'preflight refused ({type(exc).__name__}); inspect private configuration and CORE state\n')
    print(json.dumps(dict(ready=result['ready'], target=args.target, blockers=result['blockers'])))
    return 0 if result['ready'] else 3


if __name__ == '__main__':
    raise SystemExit(main())
