#!/bin/bash
# 莆田话语音训练系统 — 启动脚本
# 用法: bash start_trainer.sh [port]

PORT=${1:-8501}
cd "$(dirname "$0")"

echo "=========================================="
echo "  🗣️ 莆田话语音训练系统"
echo "=========================================="
echo ""

# 获取本机局域网 IP
IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)

echo "  本机地址: http://localhost:${PORT}"
echo "  手机访问: http://${IP}:${PORT}  (同一WiFi)"
echo ""
echo "  按 Ctrl+C 停止"
echo "=========================================="
echo ""

streamlit run putian_trainer.py \
    --server.port ${PORT} \
    --server.address 0.0.0.0 \
    --browser.gatherUsageStats false
