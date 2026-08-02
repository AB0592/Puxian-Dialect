#!/bin/bash
# 莆仙话训练 App 构建脚本
# 使用: bash build.sh

set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
FLUTTER_ZIP="/tmp/flutter.zip"
FLUTTER_DIR="/opt/homebrew/Caskroom/flutter"

echo "============================================"
echo "  莆仙话训练 App 构建工具"
echo "============================================"

# 1. 检查 Flutter
if command -v flutter &>/dev/null; then
    echo "✅ Flutter 已安装: $(flutter --version 2>&1 | head -1)"
elif [ -d "$FLUTTER_DIR" ] && [ -f "$FLUTTER_DIR/bin/flutter" ]; then
    echo "📦 Flutter 目录存在，配置 PATH..."
    export PATH="$FLUTTER_DIR/bin:$PATH"
elif [ -f "$FLUTTER_ZIP" ]; then
    echo "📦 解压 Flutter..."
    sudo mkdir -p /opt/homebrew/Caskroom/flutter
    sudo unzip -q "$FLUTTER_ZIP" -d /opt/homebrew/Caskroom/flutter/
    export PATH="/opt/homebrew/Caskroom/flutter/flutter/bin:$PATH"
    echo "flutter" > /opt/homebrew/Caskroom/flutter/.metadata
else
    echo "❌ Flutter 未安装，请先下载"
    echo "   curl -L -o /tmp/flutter.zip https://storage.flutter-io.cn/..."
    exit 1
fi

# 2. 检查项目
if [ ! -d "$APP_DIR" ]; then
    echo "❌ 项目目录不存在: $APP_DIR"
    exit 1
fi

# 3. 检查 Xcode
if command -v xcodebuild &>/dev/null; then
    echo "✅ Xcode 已安装"
else
    echo "⚠️  Xcode 未安装，只能构建 Android 版本"
    echo "   安装 Xcode: xcode-select --install (CLI) 或 App Store 安装完整 Xcode"
fi

# 4. 进入项目目录
cd "$APP_DIR"

# 5. 获取依赖
echo ""
echo "📦 获取依赖..."
flutter pub get

# 6. 选择平台
echo ""
echo "============================================"
echo "  选择构建平台:"
echo "  1) iOS (需 Xcode)"
echo "  2) Android (需 Android Studio)"
echo "  3) macOS (桌面调试)"
echo "============================================"
read -p "请输入 [1-3]: " CHOICE

case $CHOICE in
    1)
        echo "🏗️  构建 iOS 版本..."
        flutter build ios --release
        echo "✅ iOS 构建完成"
        echo "用 Xcode 打开 ios/Runner.xcworkspace 安装到设备"
        ;;
    2)
        echo "🏗️  构建 Android 版本..."
        flutter build apk --release
        echo "✅ APK: build/app/outputs/flutter-apk/app-release.apk"
        ;;
    3)
        echo "🏗️  运行 macOS 调试..."
        flutter run -d macos
        ;;
    *)
        echo "❌ 无效选择"
        exit 1
        ;;
esac
