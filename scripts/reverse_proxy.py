#!/usr/bin/env python3
"""
Simple reverse proxy that combines frontend (8080) and API (8520) on one port.
Routes /api/* to localhost:8520, everything else to localhost:8080.
Used with localtunnel to expose both services via a single public URL.
"""
import http.server
import urllib.request
import urllib.error
import ssl
import io
import sys

FRONTEND_HOST = "localhost"
FRONTEND_PORT = 8080
API_HOST = "localhost"
API_PORT = 8520
PROXY_PORT = 9090

# MIME types for common file extensions
MIME_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.htm': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.wav': 'audio/wav',
    '.mp3': 'audio/mpeg',
    '.mp4': 'video/mp4',
    '.webm': 'audio/webm',
    '.ogg': 'audio/ogg',
    '.ttf': 'font/ttf',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.txt': 'text/plain; charset=utf-8',
    '.pdf': 'application/pdf',
}


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    """Reverse proxy handler."""

    def _get_target(self):
        """Determine target host/port based on path."""
        path = self.path
        if path.startswith('/api/') or path.startswith('/docs') or path.startswith('/openapi'):
            return API_HOST, API_PORT
        return FRONTEND_HOST, FRONTEND_PORT

    def _forward(self, method):
        """Forward request to target server."""
        host, port = self._get_target()

        # Read request body
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        # Build target URL
        url = f"http://{host}:{port}{self.path}"

        # Prepare headers (remove host header to avoid conflicts)
        headers = {}
        for key, val in self.headers.items():
            if key.lower() not in ('host', 'transfer-encoding'):
                headers[key] = val

        # Create request
        req = urllib.request.Request(url, data=body, method=method, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                # Send response status
                self.send_response(resp.status)

                # Send headers
                for key, val in resp.headers.items():
                    if key.lower() not in ('transfer-encoding', 'connection'):
                        self.send_header(key, val)

                # Ensure content type for common files
                if not any(k.lower() == 'content-type' for k in resp.headers.keys()):
                    import os
                    ext = os.path.splitext(self.path.split('?')[0])[1].lower()
                    if ext in MIME_TYPES:
                        self.send_header('Content-Type', MIME_TYPES[ext])

                self.end_headers()

                # Send body
                self.wfile.write(resp.read())

        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for key, val in e.headers.items():
                if key.lower() not in ('transfer-encoding', 'connection'):
                    self.send_header(key, val)
            self.end_headers()
            self.wfile.write(e.read())

        except urllib.error.URLError as e:
            self.send_response(502)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"Backend unavailable: {str(e)}"}).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            import json
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_GET(self):
        self._forward('GET')

    def do_POST(self):
        self._forward('POST')

    def do_PUT(self):
        self._forward('PUT')

    def do_DELETE(self):
        self._forward('DELETE')

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def log_message(self, format, *args):
        """Simple logging."""
        sys.stderr.write(f"[proxy] {self.address_string()} - {format % args}\n")


def main():
    import json  # needed in _forward error handler
    import os

    server = http.server.HTTPServer(('0.0.0.0', PROXY_PORT), ProxyHandler)
    print(f"反向代理已启动: http://localhost:{PROXY_PORT}")
    print(f"  前端 (静态文件) -> localhost:{FRONTEND_PORT}")
    print(f"  API (/api/*)     -> localhost:{API_PORT}")
    print(f"\n用 localtunnel 隧道此端口:")
    print(f"  npx localtunnel --port {PROXY_PORT}")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n代理已停止")
        server.server_close()


if __name__ == '__main__':
    main()
