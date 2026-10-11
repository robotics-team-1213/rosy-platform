"""Isolated loopback HTTP relay to the single host-owned Unix gateway."""
import http.client
import http.server
import socket
from contextlib import closing

LIMIT = 16384


class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/gateway.sock')


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.connection.settimeout(30)
        try:
            if (self.path != '/v1/chat/completions'
                    or self.headers.get('Transfer-Encoding')
                    or sum(len(k) + len(v) for k, v in self.headers.items()) > 8192):
                raise ValueError('RELAY_REQUEST_REFUSED')
            size = int(self.headers.get('Content-Length', '-1'))
            if not 0 < size <= LIMIT:
                raise ValueError('RELAY_REQUEST_REFUSED')
            body = self.rfile.read(size)
            if len(body) != size:
                raise ValueError('RELAY_REQUEST_REFUSED')
            with closing(UnixConnection('localhost', timeout=30)) as upstream:
                upstream.request('POST', '/v1/chat/completions', body, {'Content-Type': 'application/json'})
                response = upstream.getresponse()
                raw = response.read(LIMIT + 1)
                if len(raw) > LIMIT:
                    raise ValueError('RELAY_OUTPUT_EXCEEDED')
                self.send_response(response.status)
                self.send_header('Content-Type', response.getheader('Content-Type', 'application/json'))
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        except Exception:
            self.send_error(400, 'RELAY_REQUEST_FAILED')


if __name__ == '__main__':
    http.server.HTTPServer(('127.0.0.1', 18081), Handler).serve_forever()
