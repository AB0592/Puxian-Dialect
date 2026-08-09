# 莆仙话（莆田方言）语音训练系统

基于 Whisper 微调和三层匹配策略的莆田方言节目名语音识别系统。让阿嬷用莆仙话说出节目名，系统自动识别并播放。

## 功能

- **语音点播** - 用莆仙话说节目名，自动识别并播放
- **ASR 识别** - 支持本地微调模型和 DashScope 云端识别
- **三层匹配** - 文字映射 + 拼音模糊 + 音频 DTW 对比
- **录音训练** - 录制莆仙话语料，微调 Whisper 模型
- **数据集管理** - 录音标注、数据集导出、多格式训练数据
- **口音适配** - 莆仙方言发音规则纠正（c/ch、z/zh、f/h 等）
- **多用户支持** - 每用户独立录音和数据隔离
- **手机访问** - 同 WiFi 下手机浏览器直接使用

## 架构

```
阿嬷的频道前端 (ama-channel/, 端口 8080)
    │  HTTP
    ▼
FastAPI 后端 (scripts/api_server.py, 端口 8520)
    ├── api_v1.py           # ASR v1 API 路由
    ├── asr/
    │   ├── service.py      # ASR 服务层（三层匹配编排）
    │   ├── providers.py    # 识别引擎（Local Whisper / DashScope / Mock）
    │   ├── normalize.py    # 拼音模糊匹配 + 误识别纠正
    │   ├── audio_matcher.py# DTW 音频匹配（39维 HTK 特征）
    │   ├── accent_adapter.py # 口音适配层
    │   ├── schemas.py      # Pydantic 数据模型
    │   ├── recording_store.py # 录音存储管理
    │   ├── dataset_store.py   # 训练数据集管理
    │   └── program_vocab.json # 节目名词表 + 误识别映射
    ├── local_model_manager.py # 本地模型管理
    ├── dialect_asr.py      # ASR 识别（多层降级链）
    ├── dialect_map.py      # 方言映射库
    ├── user_manager.py     # 用户档案
    ├── auth.py             # JWT 认证
    └── train/              # 模型微调
        ├── finetune_whisper.py  # Whisper LoRA 微调
        ├── run_training.py      # 训练入口
        └── requirements.txt     # 训练依赖
```

## 快速开始

### 1. 安装依赖

```bash
cd scripts
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置 API Key（可选，用于 DashScope 识别）

```bash
cp asr_config.example.env asr_config.env
# 编辑 asr_config.env，填入 DashScope API Key
```

### 3. 启动服务

```bash
# 启动 API 服务（端口 8520，手机同 WiFi 可访问）
python3 api_server.py
```

### 4. 启动前端

前端代码在单独的仓库：[ama-channel-demo](https://github.com/AB0592/ama-channel-demo)

```bash
cd ama-channel
python3 -m http.server 8080
```

### 5. 手机访问

手机连上和电脑同一个 WiFi，浏览器打开：
- 点播页面：`http://<电脑IP>:8080/index.html`
- 录音页面：`http://<电脑IP>:8080/record.html`

## 三层匹配策略

系统对 ASR 识别结果采用三层匹配，逐步降级：

| 层级 | 方法 | 说明 |
|------|------|------|
| 第一层 | 文字映射 | `program_vocab.json` 中 `common_misrecognition` 精确映射（如"乾杯"→"江梅妃"） |
| 第二层 | 拼音模糊 | 莆仙方言声母合并规则（c→ch, z→zh, s→sh, d→t, b→p, g→k, f→h, n→l），65%声母 + 35%韵母 |
| 第三层 | DTW 音频对比 | 39维 HTK 特征（13 MFCC + 13 delta + 13 delta-delta），CMVN 归一化，Sakoe-Chiba 约束 |

匹配流程：ASR 文字 → 误识别映射 → 子串/编辑距离 → 拼音模糊 → DTW 音频匹配

## 模型训练

### 安装训练依赖

```bash
cd scripts
pip install -r train/requirements.txt
```

### 使用录音训练

1. 在 `record.html` 页面录制莆仙话节目名
2. 录够 3 条以上后点击"开始训练模型"
3. 或手动运行训练脚本：

```bash
python3 train/run_training.py --dataset_id ds-xxxx --activate
```

训练使用 Whisper LoRA 微调（r=16, alpha=32），支持 MPS 加速。训练时需设置离线模式：

```bash
export TRANSFORMERS_OFFLINE=1
export HF_HUB_OFFLINE=1
export HF_DATASETS_OFFLINE=1
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/asr/transcribe` | 语音识别（上传音频） |
| GET | `/api/v1/asr/capabilities` | 查看支持的引擎和配置 |
| GET | `/api/v1/recordings` | 获取录音列表 |
| DELETE | `/api/v1/recordings/{id}` | 删除录音 |
| POST | `/api/v1/recordings/{id}/label` | 标注录音节目名 |
| GET | `/api/v1/datasets` | 列出数据集 |
| POST | `/api/v1/datasets` | 创建数据集 |
| POST | `/api/v1/datasets/{id}/samples` | 添加训练样本 |
| POST | `/api/v1/datasets/{id}/export` | 导出训练数据 |
| POST | `/api/v1/model/finetune/train` | 启动模型训练 |
| GET | `/api/v1/model/finetune/train/status` | 查询训练状态 |
| GET | `/api/v1/model/local/models` | 列出本地模型 |
| POST | `/api/v1/model/local/activate` | 激活模型 |

完整 API 文档见 `scripts/ASR_V1_API.md`，启动服务后访问 `http://localhost:8520/docs` 查看交互式文档。

## 配置

| 配置 | 位置 | 说明 |
|------|------|------|
| DashScope API Key | `scripts/asr_config.env` | 阿里云语音识别（不入库） |
| ASR 引擎选择 | API 请求 `provider` 参数 | `local`（本地模型）或 `thirdparty`（DashScope） |
| 前端超时 | `index.html` | 30 秒 |
| 训练模式 | 环境变量 | 离线模式，使用缓存模型 |

## 数据说明

- 词典数据来自 [hinghwa.cn](https://hinghwa.cn)，词条 61,290 条
- 发音音频 1,289 个 MP3，覆盖莆田/仙游多地区口音
- 用户录音存储在 `user_data/` 目录（不入库，隐私保护）

## 相关项目

- 前端网页：[ama-channel-demo](https://github.com/AB0592/ama-channel-demo) - 阿嬷的频道

## License

MIT
