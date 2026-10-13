"""Read-only loopback authority and paired review-server lifecycle."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import review_evidence


def make_decisions_server(store, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            allowed = self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',
                                                   f'localhost:{self.server.server_port}')
            code = 403 if not allowed else (200 if self.path == '/api/decisions' else 404)
            raw = json.dumps(review_evidence.decisions(store) if code == 200 else {'error': 'read-only decisions endpoint'}).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            self.send_error(405)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def serve_review(server, store, decisions_port):
    readback = None
    try:
        if decisions_port is not None:
            readback = make_decisions_server(store, decisions_port)
            threading.Thread(target=readback.serve_forever, daemon=True).start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if readback:
            readback.shutdown()
            readback.server_close()
