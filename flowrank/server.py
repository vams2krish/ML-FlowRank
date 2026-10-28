import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from .engine import Engine

STATIC = Path(__file__).resolve().parent.parent / 'static'


def create_server(port=8000, path='data/flowrank.db'):
    engine = Engine(path)

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, payload, content_type='application/json'):
            data = json.dumps(payload).encode() if content_type == 'application/json' else payload
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == '/api/feed':
                user = query.get('user', ['demo'])[0]
                if not 1 <= len(user) <= 80:
                    return self.send(400, {'error': 'invalid user'})
                return self.send(200, {'items': engine.feed(user), 'profile': engine.profile(user)})
            if url.path == '/api/stats':
                return self.send(200, engine.stats())
            if url.path == '/health':
                return self.send(200, {'status': 'ok'})
            if url.path == '/':
                return self.send(200, (STATIC / 'index.html').read_bytes(), 'text/html; charset=utf-8')
            self.send(404, {'error': 'not found'})

        def do_POST(self):
            if self.path != '/api/events':
                return self.send(404, {'error': 'not found'})
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 10000:
                    raise ValueError('invalid body size')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('body must be an object')
                engine.event(payload)
                self.send(200, {'ok': True})
            except (ValueError, TypeError, OverflowError) as exc:
                self.send(400, {'error': str(exc)})

    class Server(HTTPServer):
        def server_close(self):
            super().server_close()
            engine.db.close()

    return Server(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    server = create_server(args.port)
    print(f'FlowRank running at http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
