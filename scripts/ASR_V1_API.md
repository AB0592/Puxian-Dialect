# ASR v1 API — 莆仙话语音识别接口文档

## 这个文档讲什么？

这个文档记录了"莆仙方言训练系统"第一阶段（Phase 1）做的所有事情。
主要工作是：给"阿嬷的频道"做一个统一的语音识别接口，让阿嬷说话就能找到节目。

---

## 一、做了哪些事情？

### Step 1：语音识别抽象层
做了一个"中间层"，让不同的语音识别引擎都能用同一套接口。

- `asr/providers.py` — 三个引擎的代码：
  - **Mock**（假识别）：测试用，固定返回"春草"
  - **ThirdParty**（第三方）：接阿里云语音识别（第二阶段才用）
  - **Local**（本地模型）：以后用自己的莆仙话模型（第六阶段才做）

### Step 2：节目词表 + 规范化
做了一个节目名词典，让语音识别的结果能自动匹配到正确的节目名。

- `asr/program_vocab.json` — 55 个节目名，每个都有别名和常见误识别
  - 比如说"春草"，能自动匹配到"春草闯堂"
- `asr/normalize.py` — 三层匹配：
  1. 精确匹配（完全一样）
  2. 子串匹配（包含关系）
  3. 模糊匹配（差一两个字也能匹配到）
- `asr/service.py` — 统一服务层，负责：
  - 检查文件大小（不超过 50MB）
  - 检查文件格式（wav/mp3/webm/m4a/ogg）
  - 调用识别引擎
  - 做节目名规范化

### Step 3：三个 API 端点
做了三个网络接口，让"阿嬷的频道"能调用。

| 接口 | 方法 | 作用 |
|------|------|------|
| `/api/v1/asr/transcribe` | POST | 上传录音，返回识别结果 |
| `/api/v1/asr/capabilities` | GET | 查看系统支持什么 |
| `/api/v1/health` | GET | 检查服务是否正常 |

- `api_v1.py` — 三个端点的代码
- `api_server.py` — 修改了，把新的 v1 路由加进去

### Step 4：配置模板 + 接口契约 + 测试
- `asr_config.example.env` — 配置模板，复制后修改就能用
- `openapi_v1.json` / `openapi_v1.yaml` — 接口契约文档
- 写了 74 个测试，全部通过

### Step 5：阿嬷的频道接入
修改了"阿嬷的频道"的 `index.html`：

- 加了新的识别层（第 0 层），优先调用 v1 API
- 如果 v1 API 不可用，自动降级到阿里云 FC → FunASR → Google
- 识别结果会自动填入搜索框并搜索
- **高置信度 + 单一匹配时自动播放**，不需要点确认按钮

### Step 6：这个文档

---

## 二、文件清单

### 新建的文件

| 文件 | 位置 | 说明 |
|------|------|------|
| `__init__.py` | scripts/asr/ | ASR 包初始化 |
| `schemas.py` | scripts/asr/ | 数据模型定义 |
| `providers.py` | scripts/asr/ | 三个识别引擎 |
| `program_vocab.json` | scripts/asr/ | 55 个节目名词表 |
| `normalize.py` | scripts/asr/ | 节目名规范化 |
| `service.py` | scripts/asr/ | 统一服务层 |
| `recording_store.py` | scripts/asr/ | 录音存储与回放（Phase 3） |
| `accent_rules.json` | scripts/asr/ | 口音纠错规则库（Phase 4） |
| `accent_adapter.py` | scripts/asr/ | 口音适配模块（Phase 4） |
| `dataset_store.py` | scripts/asr/ | 数据集存储与管理（Phase 5） |
| `export_formats.py` | scripts/asr/ | 多格式导出模块（Phase 5） |
| `local_model_manager.py` | scripts/asr/ | 本地模型管理器（Phase 6） |
| `api_v1.py` | scripts/ | API 端点（37 个） |
| `asr_config.example.env` | scripts/ | 配置模板 |
| `openapi_v1.json` | scripts/ | 接口契约（JSON） |
| `openapi_v1.yaml` | scripts/ | 接口契约（YAML） |
| `ASR_V1_API.md` | scripts/ | 本文档 |

### 修改的文件

| 文件 | 修改内容 |
|------|----------|
| `api_server.py` | 加了 v1 路由导入和挂载 |
| `ama-channel/index.html` | 加了 v1 API 调用层 + 自动播放逻辑 |

---

## 三、API 接口说明

### POST /api/v1/asr/transcribe

上传录音文件，返回识别结果。

**请求**：multipart/form-data

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| audio | 文件 | 是 | — | 录音文件（wav/mp3/webm/m4a/ogg） |
| provider | 文本 | 否 | thirdparty | 识别引擎：mock/thirdparty/local |
| language | 文本 | 否 | auto | 语言：auto/putian/xianyou/mandarin |
| scene | 文本 | 否 | 无 | 场景：program_search 时启用节目名规范化 |
| enable_candidates | 布尔 | 否 | false | 是否返回多个候选结果 |
| request_id | 文本 | 否 | 自动生成 | 请求追踪 ID |
| save_recording | 布尔 | 否 | false | 是否保存录音（Phase 3，需 consent=true） |
| consent | 布尔 | 否 | false | 用户同意录音数据处理 |
| accent | 文本 | 否 | 无 | 口音标注：putian/xianyou/mandarin/auto（Phase 4） |
| user_id | 文本 | 否 | 无 | 用户 ID（用于口音档案关联，Phase 4） |

**成功响应**：

```json
{
  "success": true,
  "request_id": "req-abc123",
  "text": "春草闯堂",
  "normalized_text": "春草闯堂",
  "candidates": [
    {"text": "春草闯堂", "confidence": 0.95, "matched_canonical": "春草闯堂"}
  ],
  "duration_ms": 1000,
  "processing_ms": 15,
  "model_version": "mock-v1",
  "provider": "mock",
  "needs_confirmation": false,
  "recording_id": "rec-abc123",
  "recording_saved": true,
  "accent": "putian",
  "accent_adapted": true,
  "accent_corrections": [
    {"original": "春操", "corrected": "春草", "source": "global", "reason": "莆田口音平翘舌不分"}
  ]
}
```

> `recording_id` 和 `recording_saved` 仅在 `save_recording=true` + `consent=true` 时返回。
>
> `accent`、`accent_adapted`、`accent_corrections` 仅在口音纠错实际应用时返回（Phase 4）。

**错误响应**：

```json
{
  "success": false,
  "request_id": "req-abc123",
  "error": {
    "code": "AUDIO_FORMAT_UNSUPPORTED",
    "message": "不支持的音频格式",
    "retryable": false
  }
}
```

**错误码对应 HTTP 状态码**：

| 错误码 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| AUDIO_EMPTY | 400 | 文件为空 |
| AUDIO_TOO_LARGE | 413 | 文件超过 50MB |
| AUDIO_FORMAT_UNSUPPORTED | 415 | 不支持的格式 |
| AUDIO_TOO_LONG | 413 | 音频超过 30 秒 |
| PROVIDER_ERROR | 502 | 识别引擎出错 |
| INTERNAL_ERROR | 500 | 内部错误 |

### GET /api/v1/asr/capabilities

返回系统支持的功能。

```json
{
  "providers": ["mock", "thirdparty", "local"],
  "default_provider": "mock",
  "languages": ["auto", "putian", "xianyou", "mandarin"],
  "scenes": ["program_search", "training", "general"],
  "max_duration_seconds": 30,
  "max_file_size_mb": 50,
  "supported_formats": ["wav", "mp3", "webm", "m4a", "ogg"]
}
```

### GET /api/v1/health

健康检查。

```
{
  "status": "ok",
  "version": "v1",
  "timestamp": "2026-08-09T08:00:00+00:00"
}
```

### GET /api/v1/recordings

获取录音列表（分页）。

**查询参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| user_id | 文本 | "" | 用户 ID（空表示匿名用户） |
| page | 整数 | 1 | 页码（从 1 开始） |
| page_size | 整数 | 20 | 每页数量（1-100） |

**响应**：

```json
{
  "recordings": [
    {
      "recording_id": "rec-abc123",
      "user_id": "anonymous",
      "timestamp": "2026-08-09T12:00:00+00:00",
      "audio_filename": "rec-abc123.webm",
      "audio_format": "webm",
      "audio_size": 12345,
      "duration_ms": 4000,
      "text": "春草",
      "normalized_text": "春草闯堂",
      "provider": "thirdparty",
      "processing_ms": 1500,
      "needs_confirmation": false,
      "request_id": "req-xyz",
      "model_version": "paraformer-realtime-v2"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

### GET /api/v1/recordings/stats

获取录音统计信息。

**查询参数**：`user_id`（同上）

**响应**：

```json
{
  "total": 10,
  "total_size_bytes": 123456,
  "oldest_timestamp": "2026-08-01T00:00:00+00:00",
  "newest_timestamp": "2026-08-09T12:00:00+00:00"
}
```

### GET /api/v1/recordings/{recording_id}

获取单条录音详情。

**查询参数**：`user_id`（同上）

**响应**：

```json
{
  "recording": {
    "recording_id": "rec-abc123",
    "user_id": "anonymous",
    "timestamp": "2026-08-09T12:00:00+00:00",
    "audio_filename": "rec-abc123.webm",
    "audio_format": "webm",
    "audio_size": 12345,
    "duration_ms": 4000,
    "text": "春草",
    "normalized_text": "春草闯堂",
    "provider": "thirdparty",
    "processing_ms": 1500,
    "needs_confirmation": false,
    "request_id": "req-xyz",
    "model_version": "paraformer-realtime-v2"
  }
}
```

### GET /api/v1/recordings/{recording_id}/audio

下载/回放录音音频文件。浏览器可直接播放。

**查询参数**：`user_id`（同上）

**响应**：音频文件（`audio/webm`、`audio/wav` 等，根据格式自动设置 Content-Type）

### DELETE /api/v1/recordings/{recording_id}

删除一条录音（音频文件 + 元数据）。

**查询参数**：`user_id`（同上）

**响应**：

```json
{
  "ok": true,
  "deleted": "rec-abc123"
}
```

---

## Phase 4：口音适配 API

### GET /api/v1/accent/accents

获取可用的口音类型列表。

**响应**：

```json
{
  "accents": [
    {"code": "putian", "description": "莆田口音"},
    {"code": "xianyou", "description": "仙游口音"},
    {"code": "mandarin", "description": "标准普通话"},
    {"code": "auto", "description": "自动检测（不做口音修正）"}
  ]
}
```

### GET /api/v1/accent/profile

获取用户口音档案。

**查询参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| user_id | 文本 | "" | 用户 ID（空表示匿名用户） |

**响应**：

```json
{
  "user_id": "user_abc123",
  "accent": "putian",
  "custom_corrections": [
    {"original": "我的误识", "corrected": "我的正确", "count": 3, "last_used": "2026-08-09T12:00:00+00:00"}
  ],
  "stats": {
    "total_corrections_added": 5,
    "corrections_applied": 12
  }
}
```

### POST /api/v1/accent/profile/{user_id}

设置用户口音类型。设置后，后续语音识别会自动应用该口音的纠错规则。

**请求体**：

```json
{"accent": "putian"}
```

支持的口音代码：`auto`、`putian`、`xianyou`、`mandarin`

**响应**：同 GET /accent/profile

### GET /api/v1/accent/corrections

获取用户自定义纠错规则列表。

**查询参数**：`user_id`（同上）

**响应**：

```json
{
  "corrections": [
    {"original": "春操", "corrected": "春草", "count": 3, "last_used": "2026-08-09T12:00:00+00:00"}
  ],
  "total": 1
}
```

### POST /api/v1/accent/corrections/{user_id}

添加一条用户自定义纠错规则。如果已存在相同 original，则更新 corrected 和计数。

**请求体**：

```json
{"original": "春操", "corrected": "春草"}
```

**响应**：

```json
{
  "ok": true,
  "corrections": [
    {"original": "春操", "corrected": "春草", "count": 1, "last_used": "2026-08-09T12:00:00+00:00"}
  ]
}
```

### DELETE /api/v1/accent/corrections/{user_id}

删除一条用户自定义纠错规则。

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| original | 文本 | 是 | 要删除的纠错规则原始文本 |

**响应**：

```json
{"ok": true, "deleted": "春操"}
```

---

## Phase 5：模型微调数据管线 API

### POST /api/v1/datasets

创建一个新的训练数据集。

**请求体**：

```json
{"name": "莆仙话节目名识别-初始集", "description": "第一批训练数据"}
```

**响应**：

```json
{
  "dataset_id": "ds-abc123def456",
  "name": "莆仙话节目名识别-初始集",
  "description": "第一批训练数据",
  "status": "draft",
  "created_at": "2026-08-09T12:00:00+00:00",
  "updated_at": "2026-08-09T12:00:00+00:00",
  "sample_count": 0
}
```

### GET /api/v1/datasets

列出所有数据集。

**响应**：

```json
{
  "datasets": [
    {
      "dataset_id": "ds-abc123def456",
      "name": "莆仙话节目名识别-初始集",
      "status": "draft",
      "sample_count": 15,
      "updated_at": "2026-08-09T12:00:00+00:00"
    }
  ]
}
```

### GET /api/v1/datasets/{dataset_id}

获取数据集详情。

**响应**：同 POST /datasets 响应格式

### DELETE /api/v1/datasets/{dataset_id}

删除数据集（元数据 + 样本 + 导出文件）。

**响应**：`{"ok": true, "deleted": "ds-abc123def456"}`

### PATCH /api/v1/datasets/{dataset_id}/status

更新数据集状态。

**请求体**：`{"status": "locked"}`

支持的状态：`draft`（草稿）/ `locked`（锁定，不可添加样本）/ `exported`（已导出）

**响应**：更新后的数据集详情

### GET /api/v1/datasets/{dataset_id}/stats

获取数据集统计信息。

**响应**：

```json
{
  "total_samples": 15,
  "pending": 5,
  "annotated": 7,
  "verified": 3,
  "total_duration_ms": 45000,
  "total_audio_size": 120000,
  "avg_confidence": 0.82,
  "providers": {"thirdparty": 10, "mock": 5},
  "accents": {"putian": 8, "xianyou": 4, "unknown": 3}
}
```

### GET /api/v1/datasets/{dataset_id}/samples

获取样本列表（分页 + 过滤）。

**查询参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| page | 整数 | 1 | 页码 |
| page_size | 整数 | 50 | 每页数量（1-200） |
| status | 文本 | 无 | 按标注状态过滤：pending/annotated/verified |
| min_confidence | 浮点 | 无 | 最低置信度过滤 |

**响应**：

```json
{
  "samples": [
    {
      "sample_id": "smp-xxx",
      "recording_id": "rec-xxx",
      "user_id": "user123",
      "audio_path": "user_data/user123/recordings/rec-xxx.webm",
      "audio_format": "webm",
      "audio_size": 12345,
      "duration_ms": 4000,
      "original_text": "春操",
      "normalized_text": "春草闯堂",
      "corrected_text": "春草闯堂",
      "annotation_status": "verified",
      "confidence": 0.9,
      "provider": "thirdparty",
      "model_version": "paraformer-realtime-v2",
      "accent": "putian",
      "added_at": "2026-08-09T12:00:00+00:00",
      "annotated_at": "2026-08-09T12:05:00+00:00"
    }
  ],
  "total": 15,
  "page": 1,
  "page_size": 50,
  "total_pages": 1
}
```

### POST /api/v1/datasets/{dataset_id}/samples

从录音添加一个训练样本到数据集。

**请求体**：

```json
{
  "recording_id": "rec-xxx",
  "user_id": "user123",
  "corrected_text": "春草闯堂"
}
```

（`corrected_text` 可选，提供则标注状态为 annotated）

**响应**：`{"ok": true, "sample": {...}}`

### PATCH /api/v1/datasets/{dataset_id}/samples/{sample_id}

更新样本的标注文本和状态。

**请求体**：

```json
{
  "corrected_text": "修正后的文本",
  "annotation_status": "annotated"
}
```

支持的状态：`pending` / `annotated` / `verified`

**响应**：`{"ok": true, "sample": {...}}`

### DELETE /api/v1/datasets/{dataset_id}/samples/{sample_id}

从数据集移除一个样本。

**响应**：`{"ok": true, "deleted": "smp-xxx"}`

### POST /api/v1/datasets/{dataset_id}/import

批量从用户录音导入样本到数据集。已存在的录音自动跳过（按 recording_id 去重）。

**请求体**：`{"user_id": "user123"}`

**响应**：

```json
{
  "ok": true,
  "added": 10,
  "skipped": 3,
  "errors": 0
}
```

### POST /api/v1/datasets/{dataset_id}/export

导出数据集为指定格式。

**请求体**：

```json
{
  "format": "jsonl",
  "copy_audio": false,
  "status_filter": "verified",
  "min_confidence": 0.8
}
```

支持的格式：
- `jsonl` — 每行一个 JSON 对象（通用 SFT 格式）
- `csv` — CSV 表格
- `manifest` — DashScope 微调 manifest 格式
- `kaldi` — Kaldi 风格（wav.scp + text 文件）

**响应**：

```json
{
  "export_id": "exp-xxx",
  "format": "jsonl",
  "path": "training_data/exports/ds-xxx/exp-xxx",
  "sample_count": 10,
  "audio_copied": 0,
  "created_at": "2026-08-09T12:00:00+00:00"
}
```

### GET /api/v1/datasets/{dataset_id}/exports

列出数据集的所有导出记录。

**响应**：

```json
{
  "exports": [
    {
      "export_id": "exp-xxx",
      "dataset_id": "ds-xxx",
      "dataset_name": "训练数据集",
      "format": "jsonl",
      "sample_count": 10,
      "audio_copied": 0,
      "created_at": "2026-08-09T12:00:00+00:00"
    }
  ],
  "total": 1
}
```

---

## Phase 6：本地莆仙话模型 API

Phase 6 新增本地 ASR 模型管理功能，包括引擎状态检测、配置管理、微调模型管理和微调数据导出。

### 1. GET /api/v1/model/status — 获取模型状态

返回所有本地 ASR 引擎的安装情况、模型文件状态、当前活跃引擎和微调模型列表。

```bash
curl http://localhost:8520/api/v1/model/status
```

响应：
```json
{
  "config": {
    "engine": "auto",
    "custom_model_path": null,
    "whisper_model_size": "small"
  },
  "engines": {
    "sensevoice": {
      "available": true,
      "installed": true,
      "model_path": "/Users/.../SenseVoiceSmall",
      "model_size_mb": 893.0,
      "version": "1.0"
    },
    "whisper": {
      "available": false,
      "installed": true,
      "model_path": null,
      "model_size_mb": 0,
      "version": "20231117",
      "model_size": "small"
    }
  },
  "active_engine": "sensevoice",
  "finetune_models": []
}
```

### 2. PUT /api/v1/model/config — 更新模型配置

更新本地模型引擎选择、自定义模型路径或 Whisper 模型大小。

```bash
curl -X PUT http://localhost:8520/api/v1/model/config \
  -H "Content-Type: application/json" \
  -d '{"engine": "sensevoice", "whisper_model_size": "medium"}'
```

请求体（所有字段可选）：
```json
{
  "engine": "auto | sensevoice | whisper",
  "custom_model_path": "/path/to/finetuned/model.pt 或 null",
  "whisper_model_size": "tiny | base | small | medium | large | large-v2 | large-v3"
}
```

响应：
```json
{
  "ok": true,
  "config": {
    "engine": "sensevoice",
    "custom_model_path": null,
    "whisper_model_size": "medium"
  }
}
```

### 3. GET /api/v1/model/finetune/models — 微调模型列表

列出所有已注册的微调模型。

```bash
curl http://localhost:8520/api/v1/model/finetune/models
```

响应：
```json
{
  "models": [
    {
      "model_id": "ft-a1b2c3d4e5f6",
      "name": "莆仙话v1",
      "engine": "sensevoice",
      "model_path": "/path/to/model.pt",
      "description": "第一批微调模型",
      "dataset_id": "ds-xxx",
      "created_at": "2026-08-09T12:00:00+00:00",
      "path": "/path/to/model_dir"
    }
  ],
  "total": 1
}
```

### 4. POST /api/v1/model/finetune/models — 注册微调模型

注册一个训练完成的微调模型到系统中。

```bash
curl -X POST http://localhost:8520/api/v1/model/finetune/models \
  -H "Content-Type: application/json" \
  -d '{
    "name": "莆仙话v1",
    "engine": "sensevoice",
    "model_path": "/path/to/finetuned/model.pt",
    "description": "第一批微调模型",
    "dataset_id": "ds-xxx"
  }'
```

### 5. DELETE /api/v1/model/finetune/models/{model_id} — 删除微调模型

```bash
curl -X DELETE http://localhost:8520/api/v1/model/finetune/models/ft-a1b2c3d4e5f6
```

### 6. POST /api/v1/model/finetune/activate/{model_id} — 激活微调模型

激活后，本地 ASR 引擎会优先使用该微调模型。

```bash
curl -X POST http://localhost:8520/api/v1/model/finetune/activate/ft-a1b2c3d4e5f6
```

响应：
```json
{
  "ok": true,
  "config": {
    "engine": "auto",
    "custom_model_path": "/path/to/finetuned/model.pt",
    "whisper_model_size": "small"
  },
  "active_model_id": "ft-a1b2c3d4e5f6"
}
```

### 7. POST /api/v1/model/finetune/deactivate — 取消微调模型

回退到基础模型。

```bash
curl -X POST http://localhost:8520/api/v1/model/finetune/deactivate
```

### 8. POST /api/v1/model/finetune/export — 导出微调训练数据

将数据集导出为 SenseVoice 或 Whisper 微调训练格式。

```bash
curl -X POST http://localhost:8520/api/v1/model/finetune/export \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "ds-xxx",
    "format": "sensevoice",
    "status_filter": "annotated",
    "min_confidence": 0.8
  }'
```

支持的格式：
- `sensevoice`: SenseVoice 微调 JSONL（含语种/情感/事件标签 + wav.scp + text）
- `whisper`: Whisper 微调 JSONL（含 audio/sentence/language/duration）

响应：
```json
{
  "ok": true,
  "export_id": "ft-exp-a1b2c3d4e5f6",
  "format": "sensevoice",
  "path": "/path/to/export/dir",
  "sample_count": 50,
  "created_at": "2026-08-09T12:00:00+00:00"
}
```

### 9. GET /api/v1/model/finetune/exports/{dataset_id} — 微调导出记录列表

```bash
curl http://localhost:8520/api/v1/model/finetune/exports/ds-xxx
```

---

## 四、阿嬷的频道怎么用这个 API

### 识别降级链（从上到下依次尝试）

```
录音 4 秒（WebM 格式）
  │
  ├─ 第 0 层：v1 API（本地服务，优先）  ← 新加的
  │   └─ POST /api/v1/asr/transcribe
  │   └─ 返回 text + normalized_text
  │
  ├─ 第 1 层：阿里云 FC（百度→讯飞）
  │   └─ PCM base64 发送到云端
  │
  ├─ 第 2 层：FunASR（WebSocket）
  │   └─ PCM 流式发送
  │
  ├─ 第 3 层：Google Web Speech
  │   └─ 浏览器内置语音识别
  │
  └─ 全部失败 → 提示"请打字输入"
```

### 自动播放逻辑

当 v1 API 返回 `needs_confirmation: false`（高置信度）时：
1. 识别结果自动填入搜索框
2. 自动触发搜索
3. 如果只有一个匹配结果 → **直接播放**，不需要点确认按钮
4. 如果有多个匹配 → 显示结果列表，让用户选择

---

## 五、怎么测试

### 运行所有测试

```bash
cd scripts

# Step 1-2 测试（ASR 抽象层 + 规范化 + 服务层）
python3 test_asr.py

# Step 3 测试（API 端点）
python3 /path/to/test_step3.py

# Step 4 测试（配置 + OpenAPI + 集成）
python3 /path/to/test_step4.py

# Phase 3 测试（录音存储）
python3 /path/to/test_phase3.py

# Phase 4 测试（口音适配）
python3 /path/to/test_phase4.py

# Phase 5 测试（微调数据管线）
python3 /path/to/test_phase5.py

# Phase 6 测试（本地莆仙话模型）
python3 /path/to/test_phase6.py
```

### 测试结果

| 测试组 | 测试数 | 结果 |
|--------|--------|------|
| Step 1-2（ASR + 规范化） | 6 | 全部通过 |
| Step 3（API 端点） | 36 | 全部通过 |
| Step 4（集成测试） | 38 | 全部通过 |
| Phase 3（录音存储） | 76 | 全部通过 |
| Phase 4（口音适配） | 220 | 全部通过 |
| Phase 5（微调数据管线） | 201 | 全部通过 |
| Phase 6（本地莆仙话模型） | 217 | 全部通过 |
| **合计** | **794** | **全部通过** |

---

## 六、配置说明

### 配置模板

复制 `asr_config.example.env` 为 `asr_config.env`，按需修改：

```bash
# 阶段 1：用 Mock（不需要 API Key）
ASR_PROVIDER=mock

# 阶段 2+：用阿里云 DashScope
ASR_PROVIDER=thirdparty
DASHSCOPE_API_KEY=你的密钥
```

### 启动服务

```bash
cd scripts
python3 api_server.py
# 服务启动在 http://localhost:8520
# API 文档在 http://localhost:8520/docs
```

---

## 七、后续阶段计划

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | ASR 抽象层 + Mock + API + 接入 | ✅ 完成 |
| Phase 2 | 接入阿里云 DashScope 真实识别 | ✅ 完成 |
| Phase 3 | 录音数据存储与回放 | ✅ 完成 |
| Phase 4 | 口音适配层 | ✅ 完成 |
| Phase 5 | 模型微调数据管线 | ✅ 完成 |
| Phase 6 | 本地莆仙话模型 | ✅ 完成 |

### Phase 6 完成记录

- 新增 `asr/local_model_manager.py` 本地模型管理模块
  - 引擎状态检测：自动检测 SenseVoice（funasr）和 Whisper（openai-whisper）的安装情况和模型文件
  - 配置管理：引擎选择（auto/sensevoice/whisper）、自定义模型路径、Whisper 模型大小
  - 微调模型管理：注册、列表、删除、激活、取消激活
  - 微调数据导出：SenseVoice JSONL 格式（含 wav.scp + text）、Whisper JSONL 格式
  - 导出过滤：按标注状态、按置信度过滤
  - 导出记录管理：列出历史导出
- 修改 `asr/providers.py`：实现 `LocalPuxianASRProvider`
  - 引擎选择逻辑：微调模型 → SenseVoice → Whisper → 抛出错误
  - 语言代码映射：auto/putian/xianyou/mandarin
  - 置信度评分：SenseVoice 0.88、Whisper 0.80
  - 完整的错误处理（文件校验、时长限制、引擎不可用、识别异常）
- 修改 `asr/schemas.py`：新增 5 个 Pydantic 模型（ModelEngineInfo、ModelStatusResponse、UpdateModelConfigRequest、RegisterFinetuneModelRequest、FinetuneExportRequest）
- 修改 `api_v1.py`：新增 9 个 API 端点
  - `GET /api/v1/model/status` — 模型状态
  - `PUT /api/v1/model/config` — 更新配置
  - `GET /api/v1/model/finetune/models` — 微调模型列表
  - `POST /api/v1/model/finetune/models` — 注册微调模型
  - `DELETE /api/v1/model/finetune/models/{id}` — 删除微调模型
  - `POST /api/v1/model/finetune/activate/{id}` — 激活微调模型
  - `POST /api/v1/model/finetune/deactivate` — 取消微调模型
  - `POST /api/v1/model/finetune/export` — 导出微调训练数据
  - `GET /api/v1/model/finetune/exports/{dataset_id}` — 微调导出记录
- 前端新增"本地模型"管理面板：
  - 引擎状态显示（SenseVoice/Whisper 安装情况、模型路径、大小、版本）
  - 当前活跃引擎徽章
  - 引擎配置选择（引擎、Whisper 模型大小）和保存
  - 微调模型列表（注册、激活、删除、取消激活）
  - 微调数据导出（数据集选择、格式选择、导出历史）
- 217 个测试全部通过（Phase 3 回归、Phase 4 回归、Phase 5 回归均通过）
- Git 提交：feature/asr-v1-api（后端）+ feature/asr-v1-integration（前端）

### Phase 5 完成记录

- 新增 `asr/dataset_store.py` 数据集存储与管理模块
  - 数据集 CRUD（创建、查询、列表、删除、状态更新）
  - 样本管理（添加、去重、标注更新、移除、分页查询）
  - 标注状态管理：pending（待标注）→ annotated（已标注）→ verified（已验证）
  - 数据集状态管理：draft（草稿）→ locked（锁定）→ exported（已导出）
  - 锁定保护：locked/exported 状态不允许添加样本
  - 数据集统计：样本数、标注进度、总时长、总大小、平均置信度、按 provider/accent 分布
  - 批量导入：从录音列表批量添加样本，自动去重（recording_id + user_id）
- 新增 `asr/export_formats.py` 多格式导出模块
  - JSONL 格式：通用 SFT 格式，每行一个 JSON 对象
  - CSV 格式：表格形式，含 audio_path/text/duration/confidence 等列
  - DashScope Manifest 格式：阿里云微调所需的 input_audio + output_text 格式
  - Kaldi 格式：wav.scp + text 双文件格式
  - 可选音频文件复制（copy_audio=true 时复制到导出目录）
  - 按标注状态和置信度过滤导出
  - 导出元数据记录（export_metadata.json）
  - 导出历史查询
- 修改 `asr/schemas.py`：新增 10 个 Pydantic 模型（CreateDatasetRequest、DatasetInfo、DatasetDetailResponse、DatasetSample、SampleListResponse、UpdateAnnotationRequest、ExportRequest、ExportResponse、DatasetStatsResponse、BatchImportRequest）
- 修改 `api_v1.py`：新增 13 个 API 端点
  - `POST /api/v1/datasets` — 创建数据集
  - `GET /api/v1/datasets` — 数据集列表
  - `GET /api/v1/datasets/{id}` — 数据集详情
  - `DELETE /api/v1/datasets/{id}` — 删除数据集
  - `PATCH /api/v1/datasets/{id}/status` — 更新数据集状态
  - `GET /api/v1/datasets/{id}/stats` — 数据集统计
  - `GET /api/v1/datasets/{id}/samples` — 样本列表（分页+过滤）
  - `POST /api/v1/datasets/{id}/samples` — 添加样本
  - `PATCH /api/v1/datasets/{id}/samples/{sid}` — 更新标注
  - `DELETE /api/v1/datasets/{id}/samples/{sid}` — 移除样本
  - `POST /api/v1/datasets/{id}/import` — 批量导入录音
  - `POST /api/v1/datasets/{id}/export` — 导出数据集
  - `GET /api/v1/datasets/{id}/exports` — 导出记录列表
- 前端新增"数据集"管理面板：
  - 数据集列表视图（创建、刷新、状态徽章）
  - 数据集详情视图（统计信息、样本列表、分页）
  - 标注界面（修正文本输入、保存标注、验证通过、移除样本）
  - 批量导入（一键从录音导入）
  - 导出对话框（格式选择、状态过滤、置信度过滤、音频复制选项）
  - 数据集锁定/解锁、删除
- 修复 `add_samples_from_recordings` 批量导入去重计数 bug
- 201 个测试全部通过（Phase 3 回归 76 通过、Phase 4 回归 220 通过）
- Git 提交：feature/asr-v1-api（后端）+ feature/asr-v1-integration（前端）

### Phase 4 完成记录

- 新增 `asr/accent_rules.json` 口音纠错规则库
  - 莆田口音：26 条纠错规则（平翘舌、yuan/yen、lv/lu 等系统性误识别）
  - 仙游口音：8 条纠错规则（在莆田基础上增加仙游特有误识别）
  - 标准普通话 / 自动检测：无纠错规则
- 新增 `asr/accent_adapter.py` 口音适配模块
  - 全局规则加载（带缓存）
  - 用户口音档案管理（`user_data/{user_id}/accent_profile.json`）
  - 用户自定义纠错规则 CRUD
  - 核心纠错函数 `adapt_text()`：全局规则 + 用户自定义规则
- 修改 `asr/service.py`：在 ASR 识别和节目名规范化之间插入口音适配
  - 适配管线：ASR Provider → 口音适配 → 节目名规范化 → 返回
- 修改 `asr/schemas.py`：新增 5 个 Pydantic 模型（AccentInfo、AccentListResponse 等）
- 修改 `api_v1.py`：新增 6 个 API 端点
  - `GET /api/v1/accent/accents` — 可用口音列表
  - `GET /api/v1/accent/profile` — 获取用户口音档案
  - `POST /api/v1/accent/profile/{user_id}` — 设置口音类型
  - `GET /api/v1/accent/corrections` — 获取自定义纠错列表
  - `POST /api/v1/accent/corrections/{user_id}` — 添加自定义纠错
  - `DELETE /api/v1/accent/corrections/{user_id}` — 删除自定义纠错
- 修改 `POST /api/v1/asr/transcribe`：新增 `accent` 和 `user_id` 参数
  - 识别结果包含 `accent_adapted`、`accent_corrections` 字段
- 前端新增：
  - 口音选择下拉框（自动/莆田口音/仙游口音/标准普通话）
  - 口音偏好自动加载和保存（通过 localStorage 持久化用户 ID）
  - 口音纠错反馈提示（识别后显示纠错详情，3 秒自动消失）
- 220 个测试全部通过
- Git 提交：feature/asr-v1-api（后端）+ feature/asr-v1-integration（前端）

### Phase 3 完成记录

- 新增 `asr/recording_store.py` 录音存储模块（保存音频文件 + 元数据）
- 录音存储路径：`user_data/{user_id}/recordings/`（音频）+ `recordings.json`（元数据）
- 匿名用户存储在 `user_data/anonymous/recordings/`
- 每用户最多保存 500 条录音，超出自动删除最旧的
- 新增 5 个 API 端点：
  - `GET /api/v1/recordings` — 录音列表（分页）
  - `GET /api/v1/recordings/stats` — 录音统计
  - `GET /api/v1/recordings/{id}` — 录音详情
  - `GET /api/v1/recordings/{id}/audio` — 录音音频下载/回放
  - `DELETE /api/v1/recordings/{id}` — 删除录音
- 修改 `POST /api/v1/asr/transcribe` 端点：新增 `save_recording` + `consent` 参数
  - `save_recording=true` + `consent=true` 时自动保存录音
- 前端新增"录音历史"面板：
  - 点击"历史"按钮展开/收起
  - 显示录音列表（识别文本、时间、时长、引擎）
  - 在线播放录音音频
  - 删除录音
  - 分页浏览
- 76 个测试全部通过
- Git 提交：feature/asr-v1-api（后端）+ feature/asr-v1-integration（前端）

### Phase 2 完成记录

- 修复 SSL 证书问题（certifi 补丁 ssl + aiohttp）
- 修复 DashScope SDK 调用方式（start+send_audio_frame+stop 替代 call(file=)）
- 格式从 wav 改为 pcm（流式发送原始 PCM 数据）
- 默认 provider 从 mock 切换到 thirdparty
- 官方示例音频验证通过：识别出 "阿里巴巴语音实验室"
- 莆仙戏音频无法识别（预期行为：戏曲演唱非普通话语音）
- 24 个测试全部通过
- Git 提交：feature/asr-v1-api + feature/asr-v1-integration
