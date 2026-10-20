"""Run the Fleet application without installing its operational backend."""
import argparse
from pathlib import Path
import sys
import ssl

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['sample', 'connected'], default='sample')
    parser.add_argument('--scenario', default='normal')
    parser.add_argument('--port', type=int, default=4173)
    parser.add_argument('--check', action='store_true', help='validate sample assets and imports, then exit')
    parser.add_argument('--origin', help='explicit HTTPS loopback origin for connected mode')
    parser.add_argument('--upstream', help='single HTTPS Fleet origin')
    parser.add_argument('--cert', help='private local HTTPS certificate')
    parser.add_argument('--key', help='private local HTTPS key')
    parser.add_argument('--ca', help='private upstream CA, otherwise system trust')
    args = parser.parse_args(argv)
    from http_host import ASSETS, make_server
    if args.mode == 'sample':
        if any((args.origin, args.upstream, args.cert, args.key, args.ca)):
            parser.error('sample mode does not accept upstream or TLS settings')
        from sample.engine import SampleEngine
        provider = SampleEngine(args.scenario)
        origin = f'http://localhost:{args.port}'
    else:
        if not all((args.origin, args.upstream, args.cert, args.key)) or args.check:
            parser.error('connected mode requires --origin --upstream --cert --key')
        from connected import ConnectedAPI
        provider = ConnectedAPI(args.upstream, ssl.create_default_context(cafile=args.ca), args.origin)
        origin = args.origin
    if args.check:
        assert len(ASSETS['pages']) == 8
        assert not any(name.split('.')[0] in ('fleet', 'rclpy') for name in sys.modules)
        print('sample ready: 8 pages; no Fleet or ROS imports')
        return
    with make_server(provider, origin) as server:
        if args.mode == 'connected':
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(args.cert, args.key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
        print(f'Fleet {args.mode}: {origin}/console', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
