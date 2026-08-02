#!/usr/bin/env python3
"""HTTPS server for Flutter Web build - serves on port 8523 with SSL"""
import http.server
import ssl
import sys
import os

PORT = 8523
WEB_DIR = "/Users/sagaai/.hermes/profiles/dialect-bot/puxian_app/build/web"
CERT_DIR = "/Users/sagaai/.hermes/profiles/dialect-bot/scripts"
CERT_FILE = os.path.join(CERT_DIR, "cert.pem")
KEY_FILE = os.path.join(CERT_DIR, "key.pem")

os.chdir(WEB_DIR)
handler = http.server.SimpleHTTPRequestHandler

httpd = http.server.HTTPServer(('0.0.0.0', PORT), handler)
httpd.socket = ssl.wrap_socket(httpd.socket,
                               keyfile=KEY_FILE,
                               certfile=CERT_FILE,
                               server_side=True)

print(f"HTTPS Flutter Web Server: https://0.0.0.0:{PORT}")
sys.stdout.flush()
httpd.serve_forever()
