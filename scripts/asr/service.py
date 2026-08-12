"""统一 transcribe 服务（编排层）。

职责：
  1. 校验文件大小（< 50MB）
  2. 校验 MAGIC NUMBER（RIFF/WAVE, ID3, EBML/WebM, ftyp/MP4, OggS）
  3. 写入临时文件
  4. 获取 provider 并调用 transcribe()
  5. 调用 normalize() 做场景规范化
  6. 组装 TranscribeResponse 或 ErrorResponse
  7. 清理临时文件
"""

import os
import time
import uuid
import tempfile
from typing import Optional

from asr.providers import get_provider, ASRError
from asr.normalize import normalize
from asr.accent_adapter import adapt_text as accent_adapt
from asr import audio_matcher

# ============================================================
# 常量
# ============================================================

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_DURATION_SECONDS = 30

# 音频 magic number 定义
_AUDIO_MAGIC = {
    b"RIFF": "wav",
    b"ID3": "mp3",
    b"\xff\xfb": "mp3",
    b"\xff\xf3": "mp3",
    b"\xff\xfa": "mp3",
    b"\xff\xf2": "mp3",
    b"\xff\xe3": "mp3",
    b"\x1a\x45\xdf\xa5": "webm",
    b"OggS": "ogg",
}


# ============================================================
# 内部工具
# ============================================================

def _check_audio_format(audio_bytes: bytes) -> str:
    """
    校验音频字节流的 magic number。

    Returns:
        格式名称：wav / mp3 / webm / m4a / ogg

    Raises:
        ASRError: AUDIO_FORMAT_UNSUPPORTED
    """
    if len(audio_bytes) < 4:
        raise ASRError("AUDIO_FORMAT_UNSUPPORTED", "文件过短，无法识别格式", retryable=False)

    first4 = audio_bytes[:4]
    first2 = audio_bytes[:2]
    first3 = audio_bytes[:3]

    # WAV
    if first4 == b"RIFF":
        return "wav"

    # MP3: ID3v2
    if first3 == b"ID3":
        return "mp3"

    # MP3: 帧同步
    if first2 in (b"\xff\xfb", b"\xff\xf3", b"\xff\xfa", b"\xff\xf2", b"\xff\xe3"):
        return "mp3"

    # WebM / Matroska
    if first4 == b"\x1a\x45\xdf\xa5":
        return "webm"

    # OGG
    if first4 == b"OggS":
        return "ogg"

    # M4A / MP4: ftyp at offset 4
    if len(audio_bytes) >= 8 and audio_bytes[4:8] == b"ftyp":
        return "m4a"

    raise ASRError(
        "AUDIO_FORMAT_UNSUPPORTED",
        f"不支持的音频格式（magic: {first4.hex()}）",
        retryable=False,
    )


def _error_response(request_id: str, code: str, message: str, retryable: bool) -> dict:
    """构造 ErrorResponse 字典。"""
    return {
        "success": False,
        "request_id": request_id,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }


# ============================================================
# 主函数
# ============================================================

def transcribe(audio_bytes: bytes, filename: str, opts: dict) -> dict:
    """
    统一语音转写服务。

    Args:
        audio_bytes: 音频文件字节流
        filename: 原始文件名（用于推断扩展名）
        opts: 选项字典，支持以下 key：
            - provider: str = "mock"        ASR 提供方
            - language: str = "auto"        语言代码
            - scene: str|None = None        场景（program_search 时启用规范化）
            - accent: str|None = None       口音标注
            - user_id: str|None = None      用户 ID
            - request_id: str|None = None   请求追踪 ID
            - enable_candidates: bool = False  是否返回候选
            - consent: bool = False         用户同意标志

    Returns:
        dict: TranscribeResponse 或 ErrorResponse 格式的字典
    """
    request_id = opts.get("request_id") or f"req-{uuid.uuid4().hex[:12]}"
    provider_name = opts.get("provider", "thirdparty")
    scene = opts.get("scene")
    language = opts.get("language", "auto")
    accent = opts.get("accent")
    enable_candidates = opts.get("enable_candidates", False)

    start_time = time.time()

    # 1. 校验文件大小
    file_size = len(audio_bytes)
    if file_size == 0:
        return _error_response(request_id, "AUDIO_EMPTY", "文件为空（0 字节）", retryable=False)
    if file_size > MAX_FILE_SIZE:
        size_mb = file_size / (1024 * 1024)
        return _error_response(
            request_id, "AUDIO_TOO_LARGE",
            f"文件大小 {size_mb:.1f}MB 超过限制 {MAX_FILE_SIZE // (1024 * 1024)}MB",
            retryable=False,
        )

    # 2. 校验 MAGIC NUMBER
    try:
        audio_format = _check_audio_format(audio_bytes)
    except ASRError as e:
        # 尝试用 ffmpeg 转换为 WAV（浏览器可能发送了非标准格式）
        import tempfile as _tempfile
        import subprocess as _subproc
        import os as _os
        _tmp_in = None
        _tmp_out = None
        try:
            with _tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as _tmp:
                _tmp.write(audio_bytes)
                _tmp.flush()
                _tmp_in = _tmp.name
            _tmp_out = _tmp_in.replace(".bin", ".wav")
            _result = _subproc.run(
                ["ffmpeg", "-y", "-i", _tmp_in, "-ar", "16000", "-ac", "1", "-f", "wav", _tmp_out],
                capture_output=True, text=True, timeout=30
            )
            if _result.returncode == 0 and _os.path.exists(_tmp_out):
                with open(_tmp_out, "rb") as _f:
                    audio_bytes = _f.read()
                audio_format = "wav"
                filename = "converted.wav"
            else:
                hex_preview = audio_bytes[:16].hex() if audio_bytes else "empty"
                return _error_response(request_id, e.code,
                    f"{e.message} (前16字节: {hex_preview}, ffmpeg: {_result.stderr[-200:] if _result.stderr else 'unknown'})",
                    e.retryable)
        except Exception as _conv_e:
            hex_preview = audio_bytes[:16].hex() if audio_bytes else "empty"
            return _error_response(request_id, e.code,
                f"{e.message} (前16字节: {hex_preview}, 转换失败: {_conv_e})",
                e.retryable)
        finally:
            for _p in [_tmp_in, _tmp_out]:
                if _p and _os.path.exists(_p):
                    try: _os.unlink(_p)
                    except: pass

    # 3. 写入临时文件
    suffix = os.path.splitext(filename)[1] if filename else f".{audio_format}"
    if not suffix:
        suffix = f".{audio_format}"

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            tmp.flush()
            tmp_path = tmp.name

        # 4. 获取 provider
        provider = get_provider(provider_name)

        # 5. 调用 provider.transcribe()
        try:
            result = provider.transcribe(tmp_path, language, accent)
        except ASRError as e:
            return _error_response(request_id, e.code, e.message, e.retryable)
        except NotImplementedError as e:
            return _error_response(request_id, "PROVIDER_ERROR", str(e), retryable=False)

        # 6. 提取识别结果
        text = result.get("text", "")
        confidence = result.get("confidence", 0.0)
        duration_ms = result.get("duration_ms", 0)
        provider_str = result.get("provider", provider_name)
        model_version = result.get("model_version", "")

        # 6.5 口音适配（Phase 4）
        user_id = opts.get("user_id")
        accent_result = accent_adapt(text, accent, user_id)
        text = accent_result["adapted_text"]
        accent_used = accent_result["accent"]
        accent_adapted = accent_result["was_adapted"]
        accent_corrections = accent_result["corrections_applied"] if accent_adapted else None

        # 7. 构建候选列表（始终包含主结果，供 normalize 评估置信度）
        candidates = [{"text": text, "confidence": confidence}]
        if enable_candidates:
            # enable_candidates 时可能有多条候选（阶段 2+ 真实 ASR 会返回多候选）
            # 阶段 1 Mock 模式下只有一条
            pass

        # 8. 调用 normalize() 做场景规范化
        norm_result = normalize(text, scene, candidates)
        normalized_text = norm_result.get("normalized_text")
        # 仅在 enable_candidates 时返回候选列表给调用方
        reranked_candidates = norm_result.get("candidates") if enable_candidates else None
        needs_confirmation = norm_result.get("needs_confirmation", False)

        # 8.5 DTW 音频匹配兜底
        # 当文字匹配失败（normalized_text 为 None）或 SenseVoice 文本过短不可靠时，
        # 使用 DTW 音频相似度匹配尝试识别节目名。
        # engine 字段区分结果来源：sensevoice / dtw / empty
        audio_matched = False
        audio_match_score = 0.0
        engine = "empty"

        if normalized_text:
            # normalize 已命中节目名 → 文字匹配成功
            engine = "sensevoice"

        # DTW 触发条件：normalized_text 为 None（文字没匹配上）
        # 或 SenseVoice 文本过短（< 2 字，不可靠）
        text_is_unreliable = not text or len(text.strip()) < 2
        if (normalized_text is None or text_is_unreliable) and scene == "program_search" and tmp_path:
            try:
                audio_result, audio_score = audio_matcher.match(tmp_path)
                if audio_result:
                    # DTW 命中 → 用 DTW 结果覆盖
                    normalized_text = audio_result
                    engine = "dtw"
                    audio_matched = True
                    audio_match_score = audio_score
                    needs_confirmation = True
                    # SenseVoice 返回空文本时，用 DTW 结果填充 text 字段
                    if not text or not text.strip():
                        text = audio_result
                    print(f"  🎵 DTW 匹配成功: {audio_result} (score={audio_score:.3f})", flush=True)
                else:
                    print(f"  🎵 DTW 未命中 (best_score={audio_score:.3f})", flush=True)
            except Exception as am_e:
                print(f"  ⚠️ DTW 匹配异常: {am_e}", flush=True)

        # 9. 计算处理耗时
        processing_ms = int((time.time() - start_time) * 1000)

        # 10. 组装 TranscribeResponse
        response = {
            "success": True,
            "request_id": request_id,
            "text": text,
            "normalized_text": normalized_text,
            "engine": engine,
            "candidates": reranked_candidates,
            "duration_ms": duration_ms,
            "processing_ms": processing_ms,
            "model_version": model_version,
            "provider": provider_str,
            "needs_confirmation": needs_confirmation,
        }

        # Phase 4: 口音适配信息
        if accent_adapted:
            response["accent"] = accent_used
            response["accent_adapted"] = True
            response["accent_corrections"] = accent_corrections

        # DTW 匹配信息
        if audio_matched:
            response["audio_matched"] = True
            response["similarity"] = round(audio_match_score, 3)

        return response

    except Exception as e:
        return _error_response(request_id, "INTERNAL_ERROR", str(e), retryable=True)

    finally:
        # 清理临时文件
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
