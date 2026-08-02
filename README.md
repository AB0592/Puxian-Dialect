# 莆仙话（莆田方言）语音训练系统

基于个人口音引擎的莆田方言训练系统。核心理念：**中文为共同文字，各人可有独立的口语发音体系**。系统通过录音训练记住每个用户的发音特征，并能模拟用户的语音风格。

## 功能

- **四级训练素材** — 字 → 词 → 句 → 文章，对齐中国语保工程标准（1000 字 / 1200 词 / 50 句）
- **多用户档案** — 每用户独立 profile + 个人发音覆盖层（overlay）
- **方言语系模板** — 内置莆仙话（29K 条 HinghuaFactory 词典），可扩展粤语 / 闽南语 / 自定义语系
- **朗读模式** — 显示中文 → 录音 → ASR 识别 → 确认保存
- **自由对话** — 随意讲莆仙话 → 识别 / 翻译 → 学习
- **词库浏览** — 搜索、浏览、删除已录词条（词典 61,290 条）
- **声纹注册** — 可选，用于多用户区分
- **语音库采集** — 8 角色交叉录制网页端（阿豪 / 阿嬷 / 阿爸 / 阿母 / 阿叔 / 阿姑 / 阿舅 / 阿婶）

## 架构

```
Flutter Web 前端 (puxian_app/)
    │  HTTP
    ▼
FastAPI 后端 (scripts/api_server.py, 端口 8520)
    ├── dialect_map.py      # 方言映射库 (dialect_map.json)
    ├── dialect_asr.py      # ASR 识别（多层降级链）
    ├── dialect_tts.py      # TTS 合成
    ├── user_manager.py     # 用户档案 + 口音覆盖层
    ├── auth.py             # JWT 认证
    └── putian_trainer.py   # Streamlit 调参台 (端口 8501)
```

## 快速开始

### 后端

```bash
cd scripts
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # fastapi uvicorn pydantic 等

# 启动 API 服务（手机同 WiFi 访问 http://<IP>:8520）
python3 api_server.py

# 启动 Streamlit 训练台
python3 -m streamlit run putian_trainer.py --server.port 8501
```

### 前端（Flutter Web）

```bash
cd puxian_app
flutter pub get

# 本地调试
flutter run -d macos
# 或 Web 构建
flutter build web
```

## 项目结构

```
Putian-Dialect/
├── puxian_app/          # Flutter Web 前端
│   └── lib/
│       ├── main.dart
│       ├── models/      # 数据模型
│       ├── screens/     # 登录/注册/朗读/自由对话/词库
│       ├── services/    # API 客户端、录音、TTS
│       └── widgets/     # 通用组件
├── scripts/             # Python 后端
│   ├── api_server.py    # FastAPI 主服务 (8520)
│   ├── putian_trainer.py# Streamlit 训练台 (8501)
│   ├── dialect_asr*.py  # ASR 方案（DashScope/GLM/降级链）
│   ├── dialect_tts*.py  # TTS 方案
│   ├── dialect_map.py   # 方言映射库
│   ├── user_manager.py  # 用户档案
│   ├── auth.py          # JWT 认证
│   ├── scrape_hinghwa.py# hinghwa.cn 词典抓取
│   └── templates/       # 语音采集网页端
└── data/
    ├── hinghwa/         # 莆仙话词典 JSON（61,290 条词条，音频不随仓库分发）
    └── voice_collection/ # 语音采集任务配置
```

## 配置

所有 API 密钥通过环境变量或 `~/.hermes/profiles/dialect-bot/.env` 提供（不入库）：

- `DASHSCOPE_API_KEY` — 阿里云 DashScope（ASR/TTS 主方案）
- `DEEPSEEK_API_KEY` — DeepSeek（GLM 备选方案）
- `KIMI_API_KEY` — Kimi（备选）

## 数据说明

- 词典数据来自 [hinghwa.cn](https://hinghwa.cn)（api.pxm.edialect.top），词条 61,290 条
- 发音音频（576+ 个 MP3）约 17M，不随仓库分发；需要时运行 `scrape_hinghwa.py` 抓取或本地放置到 `data/hinghwa/audio/`
- ASR 现状：DashScope paraformer-realtime-v2 支持粤/闽/吴/客家，**暂不支持莆仙话**；莆仙话训练当前以听读对照为主

## License

MIT
