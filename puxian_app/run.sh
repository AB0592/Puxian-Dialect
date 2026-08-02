#!/bin/bash
# 莆仙话 App 快速启动脚本
# 设置中国镜像加速
export FLUTTER_STORAGE_BASE_URL=https://storage.flutter-io.cn
export PUB_HOSTED_URL=https://pub.flutter-io.cn
export PATH="/opt/homebrew/flutter/bin:$PATH"

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

case "${1:-help}" in
  get)
    echo "📦 获取依赖..."
    flutter pub get
    ;;
  analyze)
    echo "🔍 代码分析..."
    dart analyze lib/
    ;;
  macos)
    echo "🚀 运行 macOS 版本..."
    flutter run -d macos
    ;;
  ios)
    echo "🏗️  构建 iOS..."
    flutter build ios --release
    ;;
  apk)
    echo "🏗️  构建 Android APK..."
    flutter build apk --release
    ;;
  fix)
    echo "🔧 自动修复代码风格..."
    dart fix --apply
    ;;
  *)
    echo "用法: ./run.sh [command]"
    echo ""
    echo "命令:"
    echo "  get       获取依赖"
    echo "  analyze   代码分析"
    echo "  macos     运行 macOS 版"
    echo "  ios       构建 iOS"
    echo "  apk       构建 Android"
    echo "  fix       修复代码风格"
    ;;
esac
