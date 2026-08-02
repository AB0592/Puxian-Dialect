# 莆仙话语音训练 App

基于 Flutter 的莆仙话方言训练 App，连接现有的 FastAPI 后端训练系统。

## 功能

- **朗读模式** — 显示中文 → 录音 → ASR 识别 → 确认保存
- **自由对话** — 随意讲莆仙话 → 识别/翻译 → 学习
- **词库浏览** — 搜索、浏览、删除已录词条
- **进度跟踪** — 实时显示已录/目标数

## 技术栈

| 层 | 技术 |
|------|------|
| 前端 | Flutter 3.27 (Dart) |
| 录音 | record 5.x (原生录制) |
| 网络 | http 1.x |
| 后端 | FastAPI (已有，不修改) |
| 词库 | 29,335 条莆仙话映射 |

## 快速开始

```bash
# 1. 安装 Flutter
# 下载: https://flutter.cn 或使用镜像
# 解压到 ~/flutter，添加 ~/flutter/bin 到 PATH

# 2. 获取依赖
cd puxian_app
flutter pub get

# 3. macOS 调试运行
flutter run -d macos

# 4. 构建 iOS
flutter build ios --release

# 5. 构建 Android
flutter build apk --release
```

## 项目结构

```
puxian_app/
├── lib/
│   ├── main.dart                # App 入口
│   ├── services/
│   │   ├── api_service.dart     # API 客户端（所有后端调用）
│   │   └── audio_service.dart   # 录音服务
│   └── screens/
│       ├── home_screen.dart     # Tab 导航 + 进度条
│       ├── read_tab.dart        # 朗读 Tab（核心）
│       ├── free_tab.dart        # 对话 Tab
│       └── kb_tab.dart          # 词库 Tab
├── android/                     # Android 配置
├── ios/                         # iOS 配置（需 Xcode）
├── pubspec.yaml                 # 依赖声明
└── build.sh                     # 构建脚本
```

## 后端 API

App 连接至 `http://100.101.76.95:8520`（Tailscale 可访问）。
如需修改地址，编辑 `lib/services/api_service.dart` 中的 `_baseUrl`。

## 词库

词库来源于 GitHub 项目 [Yaryou/HinghuaFactory](https://github.com/Yaryou/HinghuaFactory)
（Rime 莆仙话输入方案），参考了《莆田县志》《莆田市志》《莆仙方言简明词汇》等。
