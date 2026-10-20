"""Run the Fleet application without installing its operational backend."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['sample'], default='sample')
    parser.add_argument('--scenario', default='normal')
    parser.add_argument('--port', type=int, default=4173)
    parser.add_argument('--check', action='store_true', help='validate sample assets and imports, then exit')
    args = parser.parse_args(argv)
    from sample.engine import SampleEngine
    from http_host import ASSETS, make_server
    provider = SampleEngine(args.scenario)
    if args.check:
        assert len(ASSETS['pages']) == 8
        assert not any(name.split('.')[0] in ('fleet', 'rclpy') for name in sys.modules)
        print('sample ready: 8 pages; no Fleet or ROS imports')
        return
    origin = f'http://localhost:{args.port}'
    with make_server(provider, origin) as server:
        print(f'Fleet sample: {origin}/console (sample / sample-password)', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
