"""ASR v1 API 路由模块。

提供端点：
  POST /api/v1/asr/transcribe         — 语音转写（multipart/form-data 上传音频）
  GET  /api/v1/asr/capabilities       — 返回系统能力描述
  GET  /api/v1/health                 — 健康检查

  Phase 3 录音存储与回放：
  GET    /api/v1/recordings           — 录音列表（分页）
  GET    /api/v1/recordings/stats     — 录音统计
  GET    /api/v1/recordings/{id}      — 录音详情
  GET    /api/v1/recordings/{id}/audio — 录音音频下载/回放
  DELETE /api/v1/recordings/{id}      — 删除录音

  Phase 4 口音适配：
  GET    /api/v1/accent/accents       — 可用口音列表
  GET    /api/v1/accent/profile       — 用户口音档案
  POST   /api/v1/accent/profile/{uid} — 设置口音
  GET    /api/v1/accent/corrections   — 自定义纠错列表
  POST   /api/v1/accent/corrections/{uid}  — 添加纠错
  DELETE /api/v1/accent/corrections/{uid}  — 删除纠错

  Phase 5 模型微调数据管线：
  POST   /api/v1/datasets             — 创建数据集
  GET    /api/v1/datasets             — 数据集列表
  GET    /api/v1/datasets/{id}        — 数据集详情
  DELETE /api/v1/datasets/{id}        — 删除数据集
  PATCH  /api/v1/datasets/{id}/status — 更新数据集状态
  GET    /api/v1/datasets/{id}/stats  — 数据集统计
  GET    /api/v1/datasets/{id}/samples — 样本列表
  POST   /api/v1/datasets/{id}/samples — 添加样本
  PATCH  /api/v1/datasets/{id}/samples/{sid} — 更新标注
  DELETE /api/v1/datasets/{id}/samples/{sid} — 移除样本
  POST   /api/v1/datasets/{id}/import — 批量导入录音
  POST   /api/v1/datasets/{id}/export — 导出数据集
  GET    /api/v1/datasets/{id}/exports — 导出记录列表

  Phase 6 本地莆仙话模型：
  GET    /api/v1/model/status              — 模型状态（引擎可用性、活跃引擎）
  PUT    /api/v1/model/config              — 更新模型配置
  GET    /api/v1/model/finetune/models     — 微调模型列表
  POST   /api/v1/model/finetune/models     — 注册微调模型
  DELETE /api/v1/model/finetune/models/{id} — 删除微调模型
  POST   /api/v1/model/finetune/activate/{id} — 激活微调模型
  POST   /api/v1/model/finetune/deactivate   — 取消微调模型
  POST   /api/v1/model/finetune/export       — 导出微调训练数据
  GET    /api/v1/model/finetune/exports/{ds_id} — 微调导出记录列表

通过 FastAPI APIRouter 挂载到主应用，与现有 /api/* 路由共存。
"""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, Form, HTTPException, Query
from fastapi.responses import FileResponse
from typing import Optional

from asr.service import transcribe as asr_transcribe, MAX_FILE_SIZE, MAX_DURATION_SECONDS
from asr.schemas import (
    TranscribeResponse,
    ErrorResponse,
    CapabilitiesResponse,
    HealthResponse,
    RecordingListResponse,
    RecordingDetailResponse,
    RecordingStatsResponse,
    RecordingMetadata,
    AccentInfo,
    AccentListResponse,
    AccentProfileResponse,
    SetAccentRequest,
    AddCorrectionRequest,
    CreateDatasetRequest,
    DatasetInfo,
    DatasetListResponse,
    DatasetDetailResponse,
    DatasetSample,
    SampleListResponse,
    UpdateAnnotationRequest,
    ExportRequest,
    ExportResponse,
    DatasetStatsResponse,
    BatchImportRequest,
    ModelStatusResponse,
    UpdateModelConfigRequest,
    RegisterFinetuneModelRequest,
    FinetuneExportRequest,
)
from asr.recording_store import (
    save_recording as store_save_recording,
    list_recordings as store_list_recordings,
    get_recording as store_get_recording,
    get_audio_path as store_get_audio_path,
    delete_recording as store_delete_recording,
    get_recording_stats as store_get_recording_stats,
    label_recording as store_label_recording,
)
from asr.accent_adapter import (
    get_available_accents as accent_list,
    get_accent_profile as accent_get_profile,
    set_user_accent as accent_set,
    add_user_correction as accent_add_correction,
    delete_user_correction as accent_delete_correction,
    list_user_corrections as accent_list_corrections,
    SUPPORTED_ACCENTS,
)
from asr.dataset_store import (
    create_dataset as ds_create,
    get_dataset as ds_get,
    list_datasets as ds_list,
    delete_dataset as ds_delete,
    update_dataset_status as ds_update_status,
    add_sample as ds_add_sample,
    update_sample_annotation as ds_update_annotation,
    remove_sample as ds_remove_sample,
    list_samples as ds_list_samples,
    get_sample as ds_get_sample,
    get_dataset_stats as ds_get_stats,
    add_samples_from_recordings as ds_batch_import,
    VALID_DATASET_STATUSES,
    VALID_STATUSES,
)
from asr.export_formats import (
    export_dataset as exp_export,
    list_exports as exp_list,
    get_export_path as exp_get_path,
    SUPPORTED_FORMATS,
)
from asr.local_model_manager import (
    get_model_status as lm_get_status,
    get_config as lm_get_config,
    save_config as lm_save_config,
    list_finetune_models as lm_list_models,
    register_finetune_model as lm_register_model,
    delete_finetune_model as lm_delete_model,
    set_active_finetune_model as lm_activate_model,
    clear_active_finetune_model as lm_deactivate_model,
    export_finetune_data as lm_export_finetune,
    list_finetune_exports as lm_list_exports,
    VALID_ENGINES,
    VALID_WHISPER_SIZES,
)

router = APIRouter(prefix="/api/v1", tags=["ASR v1"])

# ============================================================
# 常量
# ============================================================

_AVAILABLE_PROVIDERS = ["mock", "thirdparty", "local"]
_DEFAULT_PROVIDER = "thirdparty"
_SUPPORTED_LANGUAGES = ["auto", "putian", "xianyou", "mandarin"]
_SUPPORTED_SCENES = ["program_search", "training", "general"]
_SUPPORTED_FORMATS = ["wav", "mp3", "webm", "m4a", "ogg"]


# ============================================================
# POST /api/v1/asr/transcribe
# ============================================================

@router.post("/asr/transcribe", response_model=TranscribeResponse | ErrorResponse)
async def transcribe(
    audio: UploadFile = File(..., description="音频文件（wav/mp3/webm/m4a/ogg）"),
    language: str = Form("auto", description="语言代码"),
    scene: Optional[str] = Form(None, description="场景标识"),
    user_id: Optional[str] = Form(None, description="用户 ID"),
    request_id: Optional[str] = Form(None, description="请求追踪 ID"),
    accent: Optional[str] = Form(None, description="口音标注"),
    enable_candidates: bool = Form(False, description="是否返回候选"),
    consent: bool = Form(False, description="用户同意标志"),
    provider: str = Form("thirdparty", description="ASR 提供方"),
    save_recording: bool = Form(False, description="是否保存录音（Phase 3）"),
):
    """
    语音转写端点。

    接收音频文件（multipart/form-data）和可选参数，
    调用 ASR 服务层完成识别 + 场景规范化，
    返回结构化的 TranscribeResponse 或 ErrorResponse。

    阶段 2：默认使用 ThirdParty Provider（DashScope paraformer-realtime-v2）。
    阶段 3：save_recording=true 时自动保存录音音频 + 元数据。
    """
    # 1. 读取音频字节
    audio_bytes = await audio.read()

    if not audio_bytes:
        raise HTTPException(
            status_code=400,
            detail="音频文件为空",
        )

    # 莆仙话自动使用本地 ASR 引擎（LoRA 优先 → SenseVoice 回退）
    if language == 'putian':
        provider = 'local'

    # 2. 构造选项字典
    opts = {
        "provider": provider,
        "language": language,
        "scene": scene,
        "accent": accent,
        "user_id": user_id,
        "request_id": request_id,
        "enable_candidates": enable_candidates,
        "consent": consent,
    }

    # 3. 调用服务层
    filename = audio.filename or "audio.webm"
    result = asr_transcribe(audio_bytes, filename, opts)

    # 4. 返回结果
    if result.get("success"):
        # Phase 3: 保存录音
        if save_recording and consent:
            # 推断音频格式
            ext = Path(filename).suffix.lower().lstrip(".")
            if ext not in _SUPPORTED_FORMATS:
                ext = "webm"

            rec_meta = store_save_recording(
                user_id or "",
                audio_bytes,
                ext,
                result,
            )
            if rec_meta:
                result["recording_id"] = rec_meta["recording_id"]
                result["recording_saved"] = True
            else:
                result["recording_saved"] = False

        return result
    else:
        # 错误响应：根据错误码设置 HTTP 状态码
        error = result.get("error", {})
        code = error.get("code", "INTERNAL_ERROR")

        status_map = {
            "AUDIO_EMPTY": 400,
            "AUDIO_TOO_LARGE": 413,
            "AUDIO_FORMAT_UNSUPPORTED": 415,
            "AUDIO_TOO_LONG": 413,
            "PROVIDER_ERROR": 502,
            "INTERNAL_ERROR": 500,
        }
        status_code = status_map.get(code, 500)

        # 返回 ErrorResponse，HTTP 状态码反映错误类型
        raise HTTPException(
            status_code=status_code,
            detail=result,
        )


# ============================================================
# GET /api/v1/asr/capabilities
# ============================================================

@router.get("/asr/capabilities", response_model=CapabilitiesResponse)
async def capabilities():
    """
    返回 ASR 系统能力描述。

    前端可用此端点判断：
      - 当前可用的 provider 列表
      - 支持的语言和场景
      - 文件大小和时长限制
      - 支持的音频格式
    """
    return CapabilitiesResponse(
        providers=_AVAILABLE_PROVIDERS,
        default_provider=_DEFAULT_PROVIDER,
        languages=_SUPPORTED_LANGUAGES,
        scenes=_SUPPORTED_SCENES,
        max_duration_seconds=MAX_DURATION_SECONDS,
        max_file_size_mb=MAX_FILE_SIZE // (1024 * 1024),
        supported_formats=_SUPPORTED_FORMATS,
    )


# ============================================================
# GET /api/v1/health
# ============================================================

@router.get("/health", response_model=HealthResponse)
async def health():
    """
    健康检查端点。

    用于负载均衡器、监控系统判断服务是否存活。
    返回 ISO 8601 格式的当前时间戳。
    """
    return HealthResponse(
        status="ok",
        version="v1",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ============================================================
# Phase 3: 录音数据存储与回放
# ============================================================

# 音频 MIME 类型映射
_AUDIO_MIME_TYPES = {
    "webm": "audio/webm",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
}


@router.get("/recordings", response_model=RecordingListResponse)
async def list_recordings(
    user_id: str = Query("", description="用户 ID（空表示匿名用户）"),
    page: int = Query(1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
):
    """
    获取录音列表（分页）。

    返回用户的所有录音元数据，按时间倒序排列（最新在前）。
    """
    result = store_list_recordings(user_id, page, page_size)
    return RecordingListResponse(**result)


@router.get("/recordings/stats", response_model=RecordingStatsResponse)
async def recording_stats(
    user_id: str = Query("", description="用户 ID（空表示匿名用户）"),
):
    """
    获取录音统计信息。

    返回录音总数、总大小、最早和最新录音时间。
    """
    stats = store_get_recording_stats(user_id)
    return RecordingStatsResponse(**stats)


@router.get("/recordings/{recording_id}", response_model=RecordingDetailResponse)
async def get_recording_detail(
    recording_id: str,
    user_id: str = Query("", description="用户 ID（空表示匿名用户）"),
):
    """
    获取单条录音详情。

    返回指定录音的完整元数据。
    """
    rec = store_get_recording(user_id, recording_id)
    if not rec:
        raise HTTPException(status_code=404, detail="录音不存在")

    return RecordingDetailResponse(recording=RecordingMetadata(**rec))


@router.get("/recordings/{recording_id}/audio")
async def get_recording_audio(
    recording_id: str,
    user_id: str = Query("", description="用户 ID（空表示匿名用户）"),
):
    """
    下载/回放录音音频文件。

    返回原始音频文件，浏览器可直接播放。
    """
    audio_path = store_get_audio_path(user_id, recording_id)
    if not audio_path:
        raise HTTPException(status_code=404, detail="录音音频文件不存在")

    # 获取元数据以确定 MIME 类型
    rec = store_get_recording(user_id, recording_id)
    audio_format = rec.get("audio_format", "webm") if rec else "webm"
    media_type = _AUDIO_MIME_TYPES.get(audio_format, "application/octet-stream")

    return FileResponse(
        path=str(audio_path),
        media_type=media_type,
        filename=rec.get("audio_filename", f"{recording_id}.{audio_format}") if rec else f"{recording_id}.{audio_format}",
    )


@router.delete("/recordings/{recording_id}")
async def delete_recording(
    recording_id: str,
    user_id: str = Query("", description="用户 ID（空表示匿名用户）"),
):
    """
    删除一条录音（音频文件 + 元数据）。

    删除后不可恢复。
    """
    success = store_delete_recording(user_id, recording_id)
    if not success:
        raise HTTPException(status_code=404, detail="录音不存在")

    return {"ok": True, "deleted": recording_id}


@router.post("/recordings/{recording_id}/label")
async def label_recording(
    recording_id: str,
    data: dict,
    user_id: str = Query("", description="用户 ID（空表示匿名用户）"),
):
    """
    标注一条录音的正确节目名。

    用于用户手动纠正 ASR 匹配结果。标注后的录音会被音频匹配器
    动态参考库自动收录，提升后续匹配准确率。

    请求体：{"normalized_text": "江梅妃"}
    """
    normalized_text = data.get("normalized_text", "").strip()
    if not normalized_text:
        raise HTTPException(status_code=400, detail="需要 normalized_text 字段")

    updated = store_label_recording(user_id, recording_id, normalized_text)
    if updated is None:
        raise HTTPException(status_code=404, detail="录音不存在")

    # 清除音频匹配器缓存，使新标注的录音立即生效
    from asr import audio_matcher
    audio_matcher._REFERENCE_CACHE = None

    return {"ok": True, "recording": updated}


# ============================================================
# 节目名清单 + DTW 训练闭环
# ============================================================

@router.get("/programs")
async def list_programs(recordable_only: bool = Query(True, description="仅返回有媒体的节目名（35个可录制）")):
    """
    返回节目名清单（数据源：program_vocab.json）。

    - recordable_only=true（默认）：仅返回有 media 字段的 35 个节目名（可录制）
    - recordable_only=false：返回全部 57 个词条（含仅 ASR 文本匹配的 22 个）

    同时扫描所有 recordings.json 统计每个节目名的录音条数，
    用于录音页面显示进度和待录制提醒。
    """
    import json
    from pathlib import Path

    vocab_path = Path(__file__).parent / "asr" / "program_vocab.json"
    if not vocab_path.exists():
        raise HTTPException(404, "program_vocab.json 不存在")

    try:
        with open(vocab_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 筛选：recordable_only=true 时只返回有 media 字段的条目
        entries = data.get("entries", [])
        if recordable_only:
            entries = [e for e in entries if e.get("media")]
        # 去重保序
        seen = set()
        unique = []
        for e in entries:
            p = e["canonical"]
            if p not in seen:
                seen.add(p)
                unique.append(e)
    except Exception as e:
        raise HTTPException(500, f"读取词表失败: {e}")

    # 扫描所有 recordings.json，统计每个节目名的录音条数
    from asr.recording_store import USER_DATA_DIR
    counts = {}
    trained = {}
    if USER_DATA_DIR.exists():
        for user_dir in USER_DATA_DIR.iterdir():
            if not user_dir.is_dir():
                continue
            meta_path = user_dir / "recordings.json"
            if not meta_path.exists():
                continue
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    recordings = json.load(f)
                for rec in recordings:
                    norm = rec.get("normalized_text")
                    if norm:
                        counts[norm] = counts.get(norm, 0) + 1
            except Exception:
                continue

    # 查询 DTW 参考库中各节目名的参考条数
    try:
        from asr.audio_matcher import _REFERENCE_CACHE, _build_reference_library
        cache = _REFERENCE_CACHE
        if cache is None:
            cache = _build_reference_library()
        for name, refs in cache.items():
            trained[name] = len(refs)
    except Exception:
        pass

    # 组装返回
    program_list = []
    for e in unique:
        p = e["canonical"]
        program_list.append({
            "name": p,
            "category": e.get("category", ""),
            "recorded_count": counts.get(p, 0),
            "trained_count": trained.get(p, 0),
        })

    recorded_programs = sum(1 for p in program_list if p["recorded_count"] > 0)
    trained_programs = sum(1 for p in program_list if p["trained_count"] > 0)

    return {
        "programs": program_list,
        "total": len(program_list),
        "recorded_programs": recorded_programs,
        "trained_programs": trained_programs,
        "unrecorded": [p["name"] for p in program_list if p["recorded_count"] == 0],
    }


@router.post("/recordings/train")
async def train_reference_library():
    """
    重建 DTW 参考库（热更新，无需重启服务）。

    清空缓存 → 重新扫描 recordings.json → 构建参考库 → 返回统计。

    返回：
    {
        "ok": true,
        "programs": {"春草闯堂": 10, "状元与乞丐": 8, ...},
        "total_programs": 8,
        "total_refs": 60,
        "max_per_program": 10
    }
    """
    from asr.audio_matcher import rebuild_reference_library

    try:
        stats = rebuild_reference_library()
        return {"ok": True, **stats}
    except Exception as e:
        raise HTTPException(500, f"训练失败: {e}")


# ============================================================
# Phase 4: 口音适配层
# ============================================================

@router.get("/accent/accents", response_model=AccentListResponse)
async def list_accents():
    """
    获取可用的口音类型列表。

    返回系统支持的所有口音代码和描述。
    """
    accents = accent_list()
    return AccentListResponse(
        accents=[AccentInfo(**a) for a in accents]
    )


@router.get("/accent/profile", response_model=AccentProfileResponse)
async def get_accent_profile(
    user_id: str = Query("", description="用户 ID（空表示匿名用户）"),
):
    """
    获取用户口音档案。

    返回用户的口音类型、自定义纠错规则和统计信息。
    """
    profile = accent_get_profile(user_id)
    return AccentProfileResponse(**profile)


@router.post("/accent/profile", response_model=AccentProfileResponse)
async def set_accent(
    data: dict,
    user_id: str = Query("", description="用户 ID（空表示匿名用户）"),
):
    """
    设置用户口音类型。

    请求体：{"accent": "putian"}
    设置后，后续语音识别会自动应用该口音的纠错规则。
    """
    accent = data.get("accent", "").strip()
    if accent not in SUPPORTED_ACCENTS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的口音类型: {accent}，支持: {SUPPORTED_ACCENTS}"
        )

    profile = accent_set(user_id, accent)
    return AccentProfileResponse(**profile)


@router.post("/accent/profile/{user_id}", response_model=AccentProfileResponse)
async def set_accent_for_user(
    user_id: str,
    data: dict,
):
    """
    设置指定用户的口音类型。

    请求体：{"accent": "putian"}
    """
    accent = data.get("accent", "").strip()
    if accent not in SUPPORTED_ACCENTS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的口音类型: {accent}，支持: {SUPPORTED_ACCENTS}"
        )

    profile = accent_set(user_id, accent)
    return AccentProfileResponse(**profile)


@router.get("/accent/corrections")
async def list_corrections(
    user_id: str = Query("", description="用户 ID（空表示匿名用户）"),
):
    """
    获取用户自定义纠错规则列表。
    """
    corrections = accent_list_corrections(user_id)
    return {"corrections": corrections, "total": len(corrections)}


@router.post("/accent/corrections/{user_id}")
async def add_correction(
    user_id: str,
    data: dict,
):
    """
    添加一条用户自定义纠错规则。

    请求体：{"original": "春操", "corrected": "春草"}
    """
    original = data.get("original", "").strip()
    corrected = data.get("corrected", "").strip()

    if not original or not corrected:
        raise HTTPException(400, "需要 original 和 corrected 字段")

    try:
        profile = accent_add_correction(user_id, original, corrected)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"ok": True, "corrections": profile.get("custom_corrections", [])}


@router.delete("/accent/corrections/{user_id}")
async def delete_correction(
    user_id: str,
    original: str = Query(..., description="要删除的纠错规则原始文本"),
):
    """
    删除一条用户自定义纠错规则。
    """
    success = accent_delete_correction(user_id, original)
    if not success:
        raise HTTPException(404, "纠错规则不存在")

    return {"ok": True, "deleted": original}


# ============================================================
# Phase 5: 模型微调数据管线
# ============================================================

@router.post("/datasets", response_model=DatasetDetailResponse)
async def create_dataset(data: CreateDatasetRequest):
    """
    创建一个新的训练数据集。

    数据集用于收集和标注录音样本，导出后可用于模型微调。
    """
    if not data.name or not data.name.strip():
        raise HTTPException(400, "数据集名称不能为空")

    metadata = ds_create(data.name, data.description)
    return DatasetDetailResponse(**metadata)


@router.get("/datasets", response_model=DatasetListResponse)
async def list_datasets():
    """
    列出所有数据集。
    """
    datasets = ds_list()
    return DatasetListResponse(
        datasets=[DatasetInfo(**d) for d in datasets]
    )


@router.get("/datasets/{dataset_id}", response_model=DatasetDetailResponse)
async def get_dataset_detail(dataset_id: str):
    """
    获取数据集详情。
    """
    metadata = ds_get(dataset_id)
    if not metadata:
        raise HTTPException(404, "数据集不存在")

    return DatasetDetailResponse(**metadata)


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str):
    """
    删除一个数据集（元数据 + 样本 + 导出文件）。
    """
    success = ds_delete(dataset_id)
    if not success:
        raise HTTPException(404, "数据集不存在")

    return {"ok": True, "deleted": dataset_id}


@router.patch("/datasets/{dataset_id}/status", response_model=DatasetDetailResponse)
async def update_dataset_status(
    dataset_id: str,
    data: dict,
):
    """
    更新数据集状态。

    请求体：{"status": "locked"}
    支持的状态：draft（草稿）/ locked（锁定）/ exported（已导出）
    """
    status = data.get("status", "").strip()
    if status not in VALID_DATASET_STATUSES:
        raise HTTPException(400, f"无效状态: {status}，支持: {VALID_DATASET_STATUSES}")

    try:
        metadata = ds_update_status(dataset_id, status)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not metadata:
        raise HTTPException(404, "数据集不存在")

    return DatasetDetailResponse(**metadata)


@router.get("/datasets/{dataset_id}/stats", response_model=DatasetStatsResponse)
async def get_dataset_stats(dataset_id: str):
    """
    获取数据集统计信息。
    """
    if not ds_get(dataset_id):
        raise HTTPException(404, "数据集不存在")

    stats = ds_get_stats(dataset_id)
    return DatasetStatsResponse(**stats)


@router.get("/datasets/{dataset_id}/samples", response_model=SampleListResponse)
async def list_samples(
    dataset_id: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页数量"),
    status: Optional[str] = Query(None, description="按标注状态过滤"),
    min_confidence: Optional[float] = Query(None, description="最低置信度过滤"),
):
    """
    获取数据集样本列表（分页 + 过滤）。
    """
    if not ds_get(dataset_id):
        raise HTTPException(404, "数据集不存在")

    result = ds_list_samples(dataset_id, page, page_size, status, min_confidence)
    return SampleListResponse(
        samples=[DatasetSample(**s) for s in result["samples"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"],
    )


@router.post("/datasets/{dataset_id}/samples")
async def add_sample(
    dataset_id: str,
    data: dict,
):
    """
    从录音添加一个训练样本到数据集。

    请求体：
    {
        "recording_id": "rec-xxx",
        "user_id": "user123",
        "corrected_text": "春草闯堂"  (可选，提供则状态为 annotated)
    }
    """
    if not ds_get(dataset_id):
        raise HTTPException(404, "数据集不存在")

    recording_id = data.get("recording_id", "").strip()
    user_id = data.get("user_id", "").strip()
    corrected_text = data.get("corrected_text", "").strip() or None

    if not recording_id:
        raise HTTPException(400, "需要 recording_id 字段")

    # 从录音存储获取录音信息
    rec = store_get_recording(user_id, recording_id)
    if not rec:
        raise HTTPException(404, "录音不存在")

    # 获取音频路径
    audio_path = store_get_audio_path(user_id, recording_id)
    audio_path_str = str(audio_path) if audio_path else ""

    try:
        sample = ds_add_sample(
            dataset_id=dataset_id,
            recording_id=recording_id,
            user_id=user_id or "anonymous",
            audio_path=audio_path_str,
            audio_format=rec.get("audio_format", "webm"),
            audio_size=rec.get("audio_size", 0),
            duration_ms=rec.get("duration_ms", 0),
            original_text=rec.get("text", ""),
            normalized_text=rec.get("normalized_text"),
            corrected_text=corrected_text,
            confidence=0.9 if rec.get("needs_confirmation") is False else 0.7,
            provider=rec.get("provider", ""),
            model_version=rec.get("model_version", ""),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not sample:
        raise HTTPException(500, "添加样本失败")

    return {"ok": True, "sample": sample}


@router.patch("/datasets/{dataset_id}/samples/{sample_id}")
async def update_annotation(
    dataset_id: str,
    sample_id: str,
    data: UpdateAnnotationRequest,
):
    """
    更新样本的标注文本和状态。
    """
    annotation_status = data.annotation_status
    if annotation_status not in VALID_STATUSES:
        raise HTTPException(400, f"无效标注状态: {annotation_status}")

    sample = ds_update_annotation(
        dataset_id, sample_id, data.corrected_text, annotation_status
    )
    if not sample:
        raise HTTPException(404, "样本不存在")

    return {"ok": True, "sample": sample}


@router.delete("/datasets/{dataset_id}/samples/{sample_id}")
async def remove_sample(dataset_id: str, sample_id: str):
    """
    从数据集移除一个样本。
    """
    success = ds_remove_sample(dataset_id, sample_id)
    if not success:
        raise HTTPException(404, "样本不存在")

    return {"ok": True, "deleted": sample_id}


@router.post("/datasets/{dataset_id}/import")
async def batch_import_recordings(
    dataset_id: str,
    data: BatchImportRequest,
):
    """
    批量从用户录音导入样本到数据集。

    将指定用户的所有录音添加为训练样本。
    已存在的录音会自动跳过（按 recording_id 去重）。
    """
    if not ds_get(dataset_id):
        raise HTTPException(404, "数据集不存在")

    # 获取用户所有录音
    all_recordings = []
    page = 1
    while True:
        result = store_list_recordings(data.user_id, page, 100)
        all_recordings.extend(result["recordings"])
        if page >= result["total_pages"]:
            break
        page += 1

    if not all_recordings:
        return {"ok": True, "added": 0, "skipped": 0, "errors": 0, "message": "无录音可导入"}

    try:
        result = ds_batch_import(dataset_id, all_recordings, data.user_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"ok": True, **result}


@router.post("/datasets/{dataset_id}/export", response_model=ExportResponse)
async def export_dataset(
    dataset_id: str,
    data: ExportRequest,
):
    """
    导出数据集为指定格式。

    支持格式：jsonl / csv / manifest / kaldi
    """
    if not ds_get(dataset_id):
        raise HTTPException(404, "数据集不存在")

    if data.format not in SUPPORTED_FORMATS:
        raise HTTPException(400, f"不支持的格式: {data.format}，支持: {SUPPORTED_FORMATS}")

    try:
        result = exp_export(
            dataset_id=dataset_id,
            format=data.format,
            copy_audio=data.copy_audio,
            status_filter=data.status_filter,
            min_confidence=data.min_confidence,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    # 更新数据集状态为已导出
    ds_update_status(dataset_id, "exported")

    return ExportResponse(**result)


@router.get("/datasets/{dataset_id}/exports")
async def list_exports(dataset_id: str):
    """
    列出数据集的所有导出记录。
    """
    if not ds_get(dataset_id):
        raise HTTPException(404, "数据集不存在")

    exports = exp_list(dataset_id)
    return {"exports": exports, "total": len(exports)}


# ============================================================
# Phase 6: 本地莆仙话模型
# ============================================================

@router.get("/model/status", response_model=ModelStatusResponse)
async def get_model_status():
    """
    获取本地 ASR 模型状态。

    返回所有引擎（SenseVoice / Whisper）的安装情况、模型文件状态、
    当前活跃引擎和已注册的微调模型列表。
    """
    status = lm_get_status()
    return ModelStatusResponse(**status)


@router.put("/model/config")
async def update_model_config(data: UpdateModelConfigRequest):
    """
    更新本地模型配置。

    可配置项：
      - engine: 引擎选择（auto/sensevoice/whisper）
      - custom_model_path: 自定义微调模型路径
      - whisper_model_size: Whisper 模型大小
    """
    config = lm_get_config()

    if data.engine is not None:
        if data.engine not in VALID_ENGINES:
            raise HTTPException(400, f"无效引擎: {data.engine}，支持: {VALID_ENGINES}")
        config["engine"] = data.engine

    if data.custom_model_path is not None:
        if data.custom_model_path and not Path(data.custom_model_path).exists():
            raise HTTPException(400, f"模型路径不存在: {data.custom_model_path}")
        config["custom_model_path"] = data.custom_model_path if data.custom_model_path else None

    if data.whisper_model_size is not None:
        if data.whisper_model_size not in VALID_WHISPER_SIZES:
            raise HTTPException(400, f"无效 Whisper 模型大小: {data.whisper_model_size}")
        config["whisper_model_size"] = data.whisper_model_size

    try:
        saved = lm_save_config(config)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"ok": True, "config": saved}


@router.get("/model/finetune/models")
async def list_finetune_models():
    """
    列出所有已注册的微调模型。
    """
    models = lm_list_models()
    return {"models": models, "total": len(models)}


@router.post("/model/finetune/models")
async def register_finetune_model(data: RegisterFinetuneModelRequest):
    """
    注册一个微调模型。

    将训练完成的模型注册到系统中，之后可以激活使用。
    """
    if not data.name or not data.name.strip():
        raise HTTPException(400, "模型名称不能为空")

    if data.engine not in ["sensevoice", "whisper"]:
        raise HTTPException(400, f"无效引擎: {data.engine}，支持: sensevoice / whisper")

    try:
        meta = lm_register_model(
            name=data.name,
            engine=data.engine,
            model_path=data.model_path,
            description=data.description,
            dataset_id=data.dataset_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"ok": True, "model": meta}


@router.delete("/model/finetune/models/{model_id}")
async def delete_finetune_model(model_id: str):
    """
    删除一个微调模型注册。
    """
    success = lm_delete_model(model_id)
    if not success:
        raise HTTPException(404, "微调模型不存在")

    return {"ok": True, "deleted": model_id}


@router.post("/model/finetune/activate/{model_id}")
async def activate_finetune_model(model_id: str):
    """
    激活一个微调模型作为当前使用的模型。

    激活后，本地 ASR 引擎会优先使用该微调模型。
    """
    try:
        config = lm_activate_model(model_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

    return {"ok": True, "config": config, "active_model_id": model_id}


@router.post("/model/finetune/deactivate")
async def deactivate_finetune_model():
    """
    取消当前微调模型，回退到基础模型。
    """
    config = lm_deactivate_model()
    return {"ok": True, "config": config}


@router.post("/model/finetune/export")
async def export_finetune_data(data: FinetuneExportRequest):
    """
    导出数据集为微调训练格式。

    支持格式：
      - sensevoice: SenseVoice 微调 JSONL（含语种/情感/事件标签）
      - whisper: Whisper 微调 JSONL（含 audio/sentence/language/duration）
    """
    if data.format not in ["sensevoice", "whisper"]:
        raise HTTPException(400, f"不支持的格式: {data.format}，支持: sensevoice / whisper")

    try:
        result = lm_export_finetune(
            dataset_id=data.dataset_id,
            format=data.format,
            status_filter=data.status_filter,
            min_confidence=data.min_confidence,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"ok": True, **result}


@router.get("/model/finetune/exports/{dataset_id}")
async def list_finetune_exports(dataset_id: str):
    """
    列出数据集的微调数据导出记录。
    """
    exports = lm_list_exports(dataset_id)
    return {"exports": exports, "total": len(exports)}


# ============================================================
# 模型训练（异步）
# ============================================================

import asyncio
import threading

_training_status = {
    "running": False,
    "progress": "",
    "error": None,
    "model_id": None,
    "started_at": None,
    "finished_at": None,
}


def _run_training_thread(dataset_id: str, activate: bool):
    """在后台线程中运行训练脚本。"""
    global _training_status
    import subprocess
    import sys as _sys
    import os as _os

    _training_status["running"] = True
    _training_status["progress"] = "开始训练..."
    _training_status["error"] = None
    _training_status["model_id"] = None
    _training_status["started_at"] = datetime.now(timezone.utc).isoformat()
    _training_status["finished_at"] = None

    scripts_dir = Path(__file__).parent
    train_script = scripts_dir / "train" / "run_training.py"

    cmd = [_sys.executable, str(train_script), "--dataset_id", dataset_id]
    if activate:
        cmd.append("--activate")

    # 设置离线模式，使用已缓存的 HuggingFace 模型
    env = _os.environ.copy()
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
            cwd=str(scripts_dir),
            env=env,
        )

        if result.returncode == 0:
            _training_status["progress"] = "训练完成！"
            # 从输出中提取 model_id
            for line in result.stdout.split("\n"):
                if "ft-" in line and "model_id" in line.lower():
                    import re
                    m = re.search(r'ft-[a-f0-9]+', line)
                    if m:
                        _training_status["model_id"] = m.group(0)
                elif "注册" in line or "激活" in line:
                    _training_status["progress"] = line.strip()
        else:
            _training_status["error"] = result.stderr[-500:] if result.stderr else result.stdout[-500:]
            _training_status["progress"] = f"训练失败: 返回码 {result.returncode}"

    except subprocess.TimeoutExpired:
        _training_status["error"] = "训练超时（超过 60 分钟）"
        _training_status["progress"] = "训练超时"
    except Exception as e:
        _training_status["error"] = str(e)
        _training_status["progress"] = f"训练异常: {e}"
    finally:
        _training_status["running"] = False
        _training_status["finished_at"] = datetime.now(timezone.utc).isoformat()


@router.post("/model/finetune/train")
async def start_training(data: dict):
    """
    启动模型训练（异步，后台运行）。

    请求体：
    {
        "dataset_id": "ds-xxx",
        "activate": true  // 训练完成后自动激活
    }
    """
    if _training_status["running"]:
        raise HTTPException(409, "训练正在进行中，请等待完成")

    dataset_id = data.get("dataset_id", "").strip()
    if not dataset_id:
        raise HTTPException(400, "需要 dataset_id 字段")

    if not ds_get(dataset_id):
        raise HTTPException(404, "数据集不存在")

    activate = data.get("activate", True)

    thread = threading.Thread(
        target=_run_training_thread,
        args=(dataset_id, activate),
        daemon=True,
    )
    thread.start()

    return {"ok": True, "message": "训练已启动", "dataset_id": dataset_id}


@router.get("/model/finetune/train/status")
async def training_status():
    """查询训练状态。"""
    return _training_status


# ============================================================
# Cloudflare Tunnel - 公网访问
# ============================================================

import subprocess
import re as _re
import shutil as _shutil

_tunnel_process = None
_tunnel_status = {
    "running": False,
    "url": None,
    "error": None,
}


def _find_cloudflared() -> str | None:
    """查找 cloudflared 可执行文件路径。"""
    # 1. PATH 中查找
    path = _shutil.which("cloudflared")
    if path:
        return path
    # 2. 常见安装路径
    for candidate in [
        "/usr/local/bin/cloudflared",
        "/opt/homebrew/bin/cloudflared",
        _shutil.expanduser("~/bin/cloudflared"),
    ]:
        if Path(candidate).exists():
            return candidate
    return None


def _run_tunnel_thread(port: int):
    """在后台线程中运行隧道（优先 cloudflared，备选 SSH localhost.run）。"""
    global _tunnel_process, _tunnel_status

    binary = _find_cloudflared()

    if binary:
        # 方案 1: cloudflared
        try:
            _tunnel_process = subprocess.Popen(
                [binary, "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            url_pattern = _re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')
            import time
            deadline = time.time() + 30

            while _tunnel_process.poll() is None and time.time() < deadline:
                line = _tunnel_process.stdout.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                match = url_pattern.search(line)
                if match:
                    _tunnel_status["url"] = match.group(0)
                    _tunnel_status["running"] = True
                    _tunnel_status["error"] = None
                    return

            if _tunnel_process.poll() is not None:
                _tunnel_status["error"] = "cloudflared 进程已退出"
            else:
                _tunnel_status["error"] = "30 秒内未获取到公网 URL"
            _tunnel_status["running"] = False
            return

        except Exception as e:
            _tunnel_status["error"] = f"cloudflared 失败: {e}"

    # 方案 2: SSH 隧道 (localhost.run) - 无需安装任何东西
    try:
        import time
        _tunnel_process = subprocess.Popen(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
             "-R", f"80:localhost:{port}", "nokey@localhost.run"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        url_pattern = _re.compile(r'https://[a-z0-9-]+\.[a-z]+\.[a-z]+')
        deadline = time.time() + 30

        while _tunnel_process.poll() is None and time.time() < deadline:
            line = _tunnel_process.stdout.readline()
            if not line:
                time.sleep(0.5)
                continue
            # localhost.run 输出格式: "xxxx.lhr.life tunneled with tls termination, https://xxxx.lhr.life"
            match = url_pattern.search(line)
            if match and 'tunneled' in line:
                _tunnel_status["url"] = match.group(0)
                _tunnel_status["running"] = True
                _tunnel_status["error"] = None
                return

        if _tunnel_process.poll() is not None:
            _tunnel_status["error"] = "SSH 隧道进程已退出"
        else:
            _tunnel_status["error"] = "30 秒内未获取到公网 URL"
        _tunnel_status["running"] = False

    except Exception as e:
        _tunnel_status["error"] = str(e)
        _tunnel_status["running"] = False


@router.post("/tunnel/start")
async def tunnel_start(data: dict):
    """启动公网隧道（cloudflared 或 SSH localhost.run），创建公网访问链接。"""
    global _tunnel_status

    if _tunnel_status["running"]:
        return {"url": _tunnel_status["url"], "message": "Tunnel 已在运行"}

    # 默认使用反向代理端口 9090（合并前端 8080 和 API 8520）
    port = data.get("port", 9090)

    _tunnel_status = {"running": False, "url": None, "error": None}

    thread = threading.Thread(
        target=_run_tunnel_thread,
        args=(port,),
        daemon=True,
    )
    thread.start()

    # 等待最多 20 秒获取 URL（SSH 隧道需要更长时间）
    import time
    deadline = time.time() + 20
    while time.time() < deadline:
        if _tunnel_status["url"]:
            return {"url": _tunnel_status["url"]}
        if _tunnel_status["error"]:
            raise HTTPException(500, _tunnel_status["error"])
        time.sleep(0.5)

    if _tunnel_status["url"]:
        return {"url": _tunnel_status["url"]}
    raise HTTPException(500, "启动超时，请确认 cloudflared 已安装")


@router.get("/tunnel/status")
async def tunnel_status():
    """查询 Tunnel 状态。"""
    return _tunnel_status


@router.post("/tunnel/stop")
async def tunnel_stop():
    """停止 Tunnel。"""
    global _tunnel_process, _tunnel_status

    if _tunnel_process:
        _tunnel_process.terminate()
        _tunnel_process = None

    _tunnel_status = {"running": False, "url": None, "error": None}
    return {"ok": True, "message": "Tunnel 已停止"}
