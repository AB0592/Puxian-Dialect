#!/usr/bin/env python3
"""
Serveo 公网隧道 — 让手机从任何网络访问训练系统

用法:  python3 tunnel.py [端口]
默认端口: 8520
"""
import sys
import os
import subprocess
import socket

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8520

# 获取本机 IP
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("8.8.8.8", 80))
    local_ip = s.getsockname()[0]
except:
    local_ip = "127.0.0.1"
finally:
    s.close()

print(f"\n{'='*50}")
print(f"  🌐 启动公网隧道")
print(f"{'='*50}")
print(f"  本地端口: {PORT}")
print(f"  本机地址: http://localhost:{PORT}")
print(f"  局域网:   http://{local_ip}:{PORT}")
print(f"\n  正在连接 Serveo 服务器...")
print(f"  成功后会出现: Forwarding HTTP traffic from https://xxx.serveousercontent.com")
print(f"  手机直接打开那个地址即可")
print(f"{'='*50}\n")

subprocess.run([
    "ssh", "-o", "StrictHostKeyChecking=no",
    "-o", "ServerAliveInterval=30",
    "-R", f"80:localhost:{PORT}",
    "serveo.net"
])
