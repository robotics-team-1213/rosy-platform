"""TLS health probe with the site's CA and Fleet SAN, including hostname verification."""
import argparse
import socket
import ssl


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ca', default='/run/secrets/site_ca')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8098)
    parser.add_argument('--server-name', default='fleet')
    args = parser.parse_args(argv)
    context = ssl.create_default_context(cafile=args.ca)
    with socket.create_connection((args.host, args.port), timeout=3) as raw:
        with context.wrap_socket(raw, server_hostname=args.server_name) as connection:
            connection.sendall(b'GET /healthz HTTP/1.1\r\nHost: fleet\r\nConnection: close\r\n\r\n')
            status = connection.makefile('rb').readline(1024).split()
            if len(status) < 2 or status[1] != b'200':
                raise SystemExit('Account health check failed')


if __name__ == '__main__':
    main()
