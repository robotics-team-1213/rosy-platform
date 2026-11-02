"""Standalone TLS Account service using an existing activated authority database."""
import argparse
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('config', 'db', 'web-root', 'web-common', 'tls-cert', 'tls-key'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8098)
    args = parser.parse_args(argv)
    from .app import create_app
    import uvicorn
    app = create_app(config=args.config, db=args.db, web_root=args.web_root, web_common=args.web_common)
    uvicorn.run(app, host=args.host, port=args.port,
                ssl_certfile=str(args.tls_cert), ssl_keyfile=str(args.tls_key))


if __name__ == '__main__':
    main()
