"""Pydantic v2 数据模型 - ASR v1 API 请求与响应结构。

所有 /api/v1/asr/* 端点共享这些模型，确保接口契约一致。
"""

from typing import Optional

from pydantic import BaseModel, Field


# ============================================================
# 请求模型
# ============================================================

class TranscribeRequest(BaseModel):
    """语音转写请求参数（audio 通过 multipart/form-data 单独上传）。"""

    language: str = Field(default="auto", description="语言代码：auto/putian/xianyou/mandarin")
    scene: Optional[str] = Field(default=None, description="场景：program_search/training/general")
    user_id: Optional[str] = Field(default=None, description="用户 ID（可选，用于个性化）")
    request_id: Optional[str] = Field(default=None, description="请求追踪 ID，未提供时自动生成")
    accent: Optional[str] = Field(default=None, description="口音标注：putian/xianyou 等")
    enable_candidates: bool = Field(default=False, description="是否返回多个候选结果")
    consent: bool = Field(default=False, description="用户是否同意录音数据处理")


# ============================================================
# 响应模型
# ============================================================

class Candidate(BaseModel):
    """候选识别结果。"""

    text: str = Field(description="候选文本")
    confidence: float = Field(description="置信度 0.0-1.0")
    matched_canonical: Optional[str] = Field(default=None, description="匹配到的标准节目名（无匹配时为 null）")


class TranscribeResponse(BaseModel):
    """语音转写成功响应。"""

    success: bool = Field(default=True, description="是否成功")
    request_id: str = Field(description="请求 ID")
    text: str = Field(description="识别文本")
    normalized_text: Optional[str] = Field(default=None, description="规范化后的文本（场景匹配后）")
    candidates: Optional[list[Candidate]] = Field(default=None, description="候选结果列表")
    duration_ms: int = Field(description="音频时长（毫秒）")
    processing_ms: int = Field(description="处理耗时（毫秒）")
    model_version: str = Field(description="模型版本标识")
    provider: str = Field(description="ASR 提供方：mock/thirdparty/local")
    needs_confirmation: bool = Field(default=False, description="是否需要用户确认")
    recording_id: Optional[str] = Field(default=None, description="录音 ID（save_recording=true 时返回）")
    recording_saved: Optional[bool] = Field(default=None, description="录音是否已保存")
    accent: Optional[str] = Field(default=None, description="使用的口音类型（Phase 4）")
    accent_adapted: Optional[bool] = Field(default=None, description="是否做了口音纠错")
    accent_corrections: Optional[list] = Field(default=None, description="口音纠错详情")
    audio_matched: Optional[bool] = Field(default=None, description="是否通过音频相似度匹配")
    audio_match_score: Optional[float] = Field(default=None, description="音频匹配相似度分数（旧字段，兼容）")
    engine: Optional[str] = Field(default=None, description="结果来源：sensevoice / dtw / empty")
    similarity: Optional[float] = Field(default=None, description="DTW 匹配相似度（engine=dtw 时返回）")


class ErrorDetail(BaseModel):
    """错误详情。"""

    code: str = Field(description="错误码：AUDIO_EMPTY/AUDIO_FORMAT_UNSUPPORTED/AUDIO_TOO_LONG 等")
    message: str = Field(description="人类可读的错误描述")
    retryable: bool = Field(default=False, description="是否可重试")


class ErrorResponse(BaseModel):
    """语音转写错误响应。"""

    success: bool = Field(default=False, description="固定为 False")
    request_id: str = Field(description="请求 ID")
    error: ErrorDetail = Field(description="错误详情")


# ============================================================
# 辅助：Capabilities / Health 响应
# ============================================================

class CapabilitiesResponse(BaseModel):
    """GET /api/v1/asr/capabilities 响应。"""

    providers: list[str] = Field(description="可用的 ASR 提供方列表")
    default_provider: str = Field(description="默认提供方")
    languages: list[str] = Field(description="支持的语言列表")
    scenes: list[str] = Field(description="支持的场景列表")
    max_duration_seconds: int = Field(description="最大音频时长（秒）")
    max_file_size_mb: int = Field(description="最大文件大小（MB）")
    supported_formats: list[str] = Field(description="支持的音频格式")


class HealthResponse(BaseModel):
    """GET /api/v1/health 响应。"""

    status: str = Field(default="ok")
    version: str = Field(default="v1")
    timestamp: str = Field(description="ISO 8601 时间戳")


# ============================================================
# Phase 3: 录音数据存储与回放
# ============================================================

class RecordingMetadata(BaseModel):
    """录音元数据。"""

    recording_id: str = Field(description="录音 ID")
    user_id: str = Field(description="用户 ID")
    timestamp: str = Field(description="录音时间（ISO 8601）")
    audio_filename: str = Field(description="音频文件名")
    audio_format: str = Field(description="音频格式：webm/wav/mp3/m4a/ogg")
    audio_size: int = Field(description="音频文件大小（字节）")
    duration_ms: int = Field(description="音频时长（毫秒）")
    text: str = Field(description="识别文本")
    normalized_text: Optional[str] = Field(default=None, description="规范化后的文本")
    provider: str = Field(description="ASR 提供方")
    processing_ms: int = Field(description="处理耗时（毫秒）")
    needs_confirmation: bool = Field(default=False, description="是否需要确认")
    request_id: str = Field(description="请求 ID")
    model_version: str = Field(description="模型版本")


class RecordingListResponse(BaseModel):
    """GET /api/v1/recordings 响应。"""

    recordings: list[RecordingMetadata] = Field(description="录音列表")
    total: int = Field(description="录音总数")
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页数量")
    total_pages: int = Field(description="总页数")


class RecordingDetailResponse(BaseModel):
    """GET /api/v1/recordings/{recording_id} 响应。"""

    recording: RecordingMetadata = Field(description="录音详情")


class RecordingStatsResponse(BaseModel):
    """GET /api/v1/recordings/stats 响应。"""

    total: int = Field(description="录音总数")
    total_size_bytes: int = Field(description="音频总大小（字节）")
    oldest_timestamp: Optional[str] = Field(default=None, description="最早录音时间")
    newest_timestamp: Optional[str] = Field(default=None, description="最新录音时间")


class SaveRecordingResponse(BaseModel):
    """录音保存响应（嵌入 TranscribeResponse 中）。"""

    recording_id: str = Field(description="录音 ID")
    saved: bool = Field(default=True, description="是否保存成功")


# ============================================================
# Phase 4: 口音适配层
# ============================================================

class AccentInfo(BaseModel):
    """口音类型信息。"""

    code: str = Field(description="口音代码：auto/putian/xianyou/mandarin")
    description: str = Field(description="口音描述")


class AccentListResponse(BaseModel):
    """GET /api/v1/accent/accents 响应。"""

    accents: list[AccentInfo] = Field(description="可用口音列表")


class AccentProfileResponse(BaseModel):
    """用户口音档案响应。"""

    user_id: str = Field(description="用户 ID")
    accent: str = Field(description="当前口音类型")
    custom_corrections: list[dict] = Field(default_factory=list, description="自定义纠错规则")
    stats: dict = Field(description="统计信息")


class SetAccentRequest(BaseModel):
    """设置口音类型请求。"""

    accent: str = Field(description="口音代码：auto/putian/xianyou/mandarin")


class AddCorrectionRequest(BaseModel):
    """添加纠错规则请求。"""

    original: str = Field(description="ASR 识别出的错误文本")
    corrected: str = Field(description="正确文本")


# ============================================================
# Phase 5: 模型微调数据管线
# ============================================================

class CreateDatasetRequest(BaseModel):
    """创建数据集请求。"""

    name: str = Field(description="数据集名称")
    description: str = Field(default="", description="数据集描述")


class DatasetInfo(BaseModel):
    """数据集索引信息。"""

    dataset_id: str = Field(description="数据集 ID")
    name: str = Field(description="数据集名称")
    status: str = Field(description="状态：draft/locked/exported")
    sample_count: int = Field(description="样本数量")
    updated_at: str = Field(description="最后更新时间")


class DatasetListResponse(BaseModel):
    """GET /api/v1/datasets 响应。"""

    datasets: list[DatasetInfo] = Field(description="数据集列表")


class DatasetDetailResponse(BaseModel):
    """数据集详情响应。"""

    dataset_id: str = Field(description="数据集 ID")
    name: str = Field(description="数据集名称")
    description: str = Field(description="数据集描述")
    status: str = Field(description="状态：draft/locked/exported")
    created_at: str = Field(description="创建时间")
    updated_at: str = Field(description="最后更新时间")
    sample_count: int = Field(description="样本数量")


class DatasetSample(BaseModel):
    """训练样本。"""

    sample_id: str = Field(description="样本 ID")
    recording_id: str = Field(description="来源录音 ID")
    user_id: str = Field(description="来源用户 ID")
    audio_path: str = Field(description="音频文件路径")
    audio_format: str = Field(description="音频格式")
    audio_size: int = Field(description="音频文件大小（字节）")
    duration_ms: int = Field(description="音频时长（毫秒）")
    original_text: str = Field(description="ASR 原始识别文本")
    normalized_text: Optional[str] = Field(default=None, description="规范化后的文本")
    corrected_text: str = Field(description="标注/修正后的文本")
    annotation_status: str = Field(description="标注状态：pending/annotated/verified")
    confidence: float = Field(description="ASR 置信度")
    provider: str = Field(description="ASR 提供方")
    model_version: str = Field(description="ASR 模型版本")
    accent: Optional[str] = Field(default=None, description="口音类型")
    added_at: str = Field(description="添加时间")
    annotated_at: Optional[str] = Field(default=None, description="标注时间")


class SampleListResponse(BaseModel):
    """样本列表响应。"""

    samples: list[DatasetSample] = Field(description="样本列表")
    total: int = Field(description="样本总数（过滤后）")
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页数量")
    total_pages: int = Field(description="总页数")


class UpdateAnnotationRequest(BaseModel):
    """更新标注请求。"""

    corrected_text: str = Field(description="修正后的文本")
    annotation_status: str = Field(default="annotated", description="标注状态：pending/annotated/verified")


class ExportRequest(BaseModel):
    """导出数据集请求。"""

    format: str = Field(default="jsonl", description="导出格式：jsonl/csv/manifest/kaldi")
    copy_audio: bool = Field(default=False, description="是否复制音频文件")
    status_filter: Optional[str] = Field(default=None, description="按标注状态过滤")
    min_confidence: Optional[float] = Field(default=None, description="最低置信度过滤")


class ExportResponse(BaseModel):
    """导出响应。"""

    export_id: str = Field(description="导出 ID")
    format: str = Field(description="导出格式")
    path: str = Field(description="导出目录路径")
    sample_count: int = Field(description="导出样本数")
    audio_copied: int = Field(description="复制的音频文件数")
    created_at: str = Field(description="导出时间")


class DatasetStatsResponse(BaseModel):
    """数据集统计响应。"""

    total_samples: int = Field(description="样本总数")
    pending: int = Field(description="待标注数")
    annotated: int = Field(description="已标注数")
    verified: int = Field(description="已验证数")
    total_duration_ms: int = Field(description="总音频时长（毫秒）")
    total_audio_size: int = Field(description="总音频大小（字节）")
    avg_confidence: float = Field(description="平均置信度")
    providers: dict = Field(description="按提供方统计")
    accents: dict = Field(description="按口音统计")


class BatchImportRequest(BaseModel):
    """批量导入录音请求。"""

    user_id: str = Field(default="", description="录音所属用户 ID")


# ============================================================
# Phase 6: 本地莆仙话模型
# ============================================================

class ModelEngineInfo(BaseModel):
    """单个 ASR 引擎状态信息。"""

    available: bool = Field(description="模型是否可用（已安装 + 模型文件存在）")
    installed: bool = Field(description="SDK 是否已安装")
    model_path: Optional[str] = Field(default=None, description="模型文件路径")
    model_size_mb: float = Field(default=0, description="模型文件大小（MB）")
    version: str = Field(default="", description="SDK 版本")
    model_size: Optional[str] = Field(default=None, description="Whisper 模型大小")


class ModelStatusResponse(BaseModel):
    """GET /api/v1/model/status 响应。"""

    config: dict = Field(description="当前模型配置")
    engines: dict = Field(description="引擎状态（sensevoice / whisper）")
    active_engine: str = Field(description="当前活跃引擎：sensevoice/whisper/finetuned/none")
    finetune_models: list[dict] = Field(default_factory=list, description="已注册的微调模型列表")


class UpdateModelConfigRequest(BaseModel):
    """PUT /api/v1/model/config 请求。"""

    engine: Optional[str] = Field(default=None, description="引擎选择：auto/sensevoice/whisper")
    custom_model_path: Optional[str] = Field(default=None, description="自定义微调模型路径")
    whisper_model_size: Optional[str] = Field(default=None, description="Whisper 模型大小")


class RegisterFinetuneModelRequest(BaseModel):
    """注册微调模型请求。"""

    name: str = Field(description="模型名称")
    engine: str = Field(description="引擎类型：sensevoice/whisper")
    model_path: str = Field(description="模型文件或目录路径")
    description: str = Field(default="", description="模型描述")
    dataset_id: str = Field(default="", description="来源数据集 ID")


class FinetuneExportRequest(BaseModel):
    """微调数据导出请求。"""

    dataset_id: str = Field(description="数据集 ID")
    format: str = Field(default="sensevoice", description="导出格式：sensevoice/whisper")
    status_filter: Optional[str] = Field(default=None, description="按标注状态过滤")
    min_confidence: Optional[float] = Field(default=None, description="最低置信度过滤")
