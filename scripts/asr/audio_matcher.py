"""音频相似度匹配模块（DTW 版）。

当 ASR 文字匹配失败时，通过 DTW（动态时间规整）比较音频的 MFCC 声学特征来匹配节目名。
这不依赖 ASR 识别结果，即使 ASR 输出完全错误的文字也能正确匹配。

工作原理：
  1. 从 recordings.json 中动态扫描已有录音，按 normalized_text 分组构建参考库
  2. 同时使用硬编码的 _REFERENCE_CONFIG 补充（用于无 normalized_text 的录音）
  3. 对每条参考录音提取完整 MFCC 矩阵（39维 × n帧，HTK 标准）
  4. 对输入音频同样提取 MFCC 矩阵
  5. 使用 DTW 计算输入音频与每条参考录音的规整距离
  6. 对每个节目名取最小 DTW 距离，转换为相似度分数：sim = exp(-dist / scale)
  7. 取相似度最高的节目名作为匹配结果，要求达到阈值和间距
"""

import os
import json
import math
import subprocess
from pathlib import Path
from typing import Optional

# ============================================================
# 配置
# ============================================================

# 3 级向上到达项目根目录（scripts/asr/audio_matcher.py → scripts/asr → scripts → 项目根）
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_USER_DATA = _PROJECT_ROOT / "user_data"
_ASR_DIR = Path(__file__).parent

# 硬编码参考音频配置：节目名 → 录音文件路径列表（相对于 user_data 目录）
_REFERENCE_CONFIG = {
    "春草闯堂": [
        "record_user_fxxeer4m/recordings/rec-12775e6dfaa8.webm",
        "record_user_fxxeer4m/recordings/rec-2fcf3eb67127.webm",
        "record_user_fxxeer4m/recordings/rec-be062854ab0d.webm",
        "record_user_6ccd3e5q/recordings/rec-f736a457a5d2.webm",
        "record_user_qojbppz0/recordings/rec-9b9d28046fca.webm",
        "record_user_qojbppz0/recordings/rec-74a9707c5809.webm",
        "user_mslax52oawtpeb/recordings/rec-4c84b6360c7f.webm",
        "user_mslax52oawtpeb/recordings/rec-8f410f90e5c1.webm",
        "user_mslax52oawtpeb/recordings/rec-a6a83bb85a47.webm",
        "user_mslax52oawtpeb/recordings/rec-d3b0cba19f08.webm",
        "user_mslax52oawtpeb/recordings/rec-fdb1e4582d39.webm",
        "user_mslax52oawtpeb/recordings/rec-17b5034e119c.webm",
        "user_mslax52oawtpeb/recordings/rec-634f4f43158d.webm",
    ],
    "状元与乞丐": [
        "record_user_q2k6ixrn/recordings/rec-1da2f797970b.webm",
        "record_user_q2k6ixrn/recordings/rec-3fc4bad3d617.webm",
        "record_user_q2k6ixrn/recordings/rec-96a96b8fa5ce.webm",
        "record_user_q2k6ixrn/recordings/rec-36725a4957ad.webm",
        "user_mslax52oawtpeb/recordings/rec-2188e2846cb4.webm",
        "user_mslax52oawtpeb/recordings/rec-65c57669b29f.webm",
        "user_mslax52oawtpeb/recordings/rec-5fd0d40ab13f.webm",
    ],
    "江梅妃": [
        # 参考录音由 recordings.json 动态扫描提供（normalized_text="江梅妃"）
    ],
}

# DTW 距离转换为相似度的缩放因子（越小分数区分度越大）
_DTW_SCALE = 10.0

# 匹配阈值：相似度高于此值才认为匹配
_MATCH_THRESHOLD = 0.35

# 最高分与次高分的差距要求
_MARGIN_THRESHOLD = 0.005

# 每个节目名最多保留的参考音频条数
# 原 5 条过少（124 条标注仅用 40 条），提高到 10 条以增加匹配覆盖
# 57 节目名 × 10 = 570 条上限，DTW 匹配仍可在 1s 内完成
_MAX_REFS_PER_PROGRAM = 10

# Sakoe-Chiba 带宽约束（限制 DTW 路径偏离对角线的范围，防止病态规整）
# 设为 0 表示不约束；设为正整数表示允许偏离对角线的最大帧数
_SAKOE_CHIBA_RATIO = 1.0  # 不约束（短音频节目名匹配需要全路径搜索）

# ============================================================
# 特征缓存
# ============================================================

# 缓存：{program_name: [mfcc_matrix1, mfcc_matrix2, ...]}
# 每个 mfcc_matrix 是 list[list[float]]，形状 (n_mfcc, n_frames)
_REFERENCE_CACHE: Optional[dict[str, list[list[list[float]]]]] = None


# ============================================================
# 音频处理
# ============================================================

def _convert_to_wav(audio_path: str) -> str:
    """将音频文件转换为 WAV 格式（如果需要）。返回 WAV 文件路径。"""
    if audio_path.lower().endswith(".wav"):
        return audio_path

    wav_path = audio_path.rsplit(".", 1)[0] + ".wav"
    if not os.path.exists(wav_path):
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
                capture_output=True, text=True, timeout=30,
            )
        except Exception:
            return audio_path

    return wav_path if os.path.exists(wav_path) else audio_path


def _extract_mfcc_matrix(audio_path: str) -> Optional[list[list[float]]]:
    """
    提取音频的完整特征矩阵（HTK 标准 39 维）。

    使用 librosa 提取 13 维 MFCC + 13 维 delta + 13 维 delta-delta = 39 维。
    对每一维做 z-score 归一化（CMVN），使不同录音间可比。

    Returns:
        特征矩阵的 list 表示：[[feat_0_frame_0, feat_0_frame_1, ...], ...]
        形状 (39, n_frames)。如果提取失败返回 None。
    """
    try:
        import librosa
        import numpy as np

        wav_path = _convert_to_wav(audio_path)
        if not os.path.exists(wav_path):
            return None

        # 加载音频（16kHz, mono）
        y, sr = librosa.load(wav_path, sr=16000, mono=True, duration=10)

        if len(y) < 1600:  # 少于 0.1 秒，跳过
            return None

        # 静音修剪
        try:
            y_trimmed, _ = librosa.effects.trim(y, top_db=30)
            if len(y_trimmed) > 1600:
                y = y_trimmed
        except Exception:
            pass

        # 提取 MFCC 特征矩阵（13 维 × n 帧）— 低阶系数更稳定
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, n_fft=512, hop_length=160)

        # 一阶差分（delta）— 捕捉频谱变化速率
        delta = librosa.feature.delta(mfcc)

        # 二阶差分（delta-delta）— 捕捉频谱变化的加速度
        delta2 = librosa.feature.delta(mfcc, order=2)

        # 拼接：13 + 13 + 13 = 39 维
        features = np.vstack([mfcc, delta, delta2])  # (39, n_frames)

        # z-score 归一化（逐维 = CMVN），使不同录音间可比
        mean = np.mean(features, axis=1, keepdims=True)
        std = np.std(features, axis=1, keepdims=True)
        std[std == 0] = 1.0  # 避免除零
        features_normalized = (features - mean) / std

        return features_normalized.tolist()

    except Exception as e:
        print(f"  ⚠️ MFCC 提取失败 ({audio_path}): {e}")
        return None


# ============================================================
# DTW 距离计算
# ============================================================

def _dtw_distance(mfcc1: list[list[float]], mfcc2: list[list[float]]) -> float:
    """
    计算两个 MFCC 矩阵的 DTW 距离（归一化后）。

    使用经典的动态时间规整算法，欧氏距离作为帧间距离度量。
    返回归一化后的平均路径距离。

    Args:
        mfcc1: (n_mfcc, n_frames1) 矩阵
        mfcc2: (n_mfcc, n_frames2) 矩阵

    Returns:
        归一化的 DTW 距离（越小越相似）
    """
    try:
        import numpy as np
    except ImportError:
        return float('inf')

    n1 = len(mfcc1[0])  # n_frames1
    n2 = len(mfcc2[0])  # n_frames2
    dim = len(mfcc1)    # n_mfcc

    if n1 == 0 or n2 == 0:
        return float('inf')

    # 转为 numpy 数组方便计算
    arr1 = np.array(mfcc1)  # (dim, n1)
    arr2 = np.array(mfcc2)  # (dim, n2)

    # 限制最大帧数，避免过长计算
    max_frames = 200
    if n1 > max_frames:
        indices = np.linspace(0, n1 - 1, max_frames).astype(int)
        arr1 = arr1[:, indices]
        n1 = max_frames
    if n2 > max_frames:
        indices = np.linspace(0, n2 - 1, max_frames).astype(int)
        arr2 = arr2[:, indices]
        n2 = max_frames

    # 计算帧间欧氏距离矩阵
    # dist_matrix[i][j] = euclidean_distance(arr1[:, i], arr2[:, j])
    # 使用广播：arr1.T[:, np.newaxis, :] - arr2.T[np.newaxis, :, :]
    diff = arr1.T[:, np.newaxis, :] - arr2.T[np.newaxis, :, :]  # (n1, n2, dim)
    dist_matrix = np.sqrt(np.sum(diff ** 2, axis=2))  # (n1, n2)

    # DTW 动态规划（带 Sakoe-Chiba 带约束）
    # D[i][j] = dist_matrix[i][j] + min(D[i-1][j], D[i][j-1], D[i-1][j-1])
    # 约束：|i - j| <= window，防止病态规整
    window = max(int(max(n1, n2) * _SAKOE_CHIBA_RATIO), 5)
    INF = float('inf')
    D = np.full((n1 + 1, n2 + 1), INF)
    D[0, 0] = 0.0

    for i in range(1, n1 + 1):
        # Sakoe-Chiba 带约束：j 的范围限制在 [i-window, i+window]
        j_start = max(1, i - window)
        j_end = min(n2, i + window)
        for j in range(j_start, j_end + 1):
            cost = dist_matrix[i - 1, j - 1]
            D[i, j] = cost + min(D[i - 1, j], D[i, j - 1], D[i - 1, j - 1])

    # 归一化：除以路径长度（近似为 n1 + n2）
    total_cost = D[n1, n2]
    path_length = n1 + n2

    return total_cost / path_length


def _dtw_to_similarity(dtw_dist: float) -> float:
    """将 DTW 距离转换为相似度分数 [0, 1]。"""
    if dtw_dist == float('inf'):
        return 0.0
    return math.exp(-dtw_dist / _DTW_SCALE)


# ============================================================
# 动态参考库构建
# ============================================================

def _scan_recordings_from_metadata() -> dict[str, list[str]]:
    """
    扫描 user_data 下所有 recordings.json，按 normalized_text 分组。

    返回：{program_name: [audio_path1, audio_path2, ...]}
    """
    result: dict[str, list[str]] = {}

    if not _USER_DATA.exists():
        return result

    for user_dir in _USER_DATA.iterdir():
        if not user_dir.is_dir():
            continue

        meta_path = user_dir / "recordings.json"
        if not meta_path.exists():
            continue

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                recordings = json.load(f)

            for rec in recordings:
                norm_text = rec.get("normalized_text")
                if not norm_text:
                    continue

                audio_filename = rec.get("audio_filename", "")
                if not audio_filename:
                    continue

                audio_path = user_dir / "recordings" / audio_filename
                if audio_path.exists():
                    if norm_text not in result:
                        result[norm_text] = []
                    result[norm_text].append(str(audio_path))

        except Exception:
            continue

    return result


def _scan_training_wavs() -> dict[str, list[str]]:
    """
    扫描 training_data/wavs/ 目录，从文件名提取节目名。

    文件名格式：sample_0000_春草闯堂.wav
    返回：{program_name: [audio_path1, audio_path2, ...]}
    """
    result: dict[str, list[str]] = {}

    wavs_dir = _PROJECT_ROOT / "training_data" / "wavs"
    if not wavs_dir.exists():
        return result

    for wav_file in wavs_dir.glob("*.wav"):
        # sample_0000_春草闯堂.wav → 春草闯堂
        parts = wav_file.stem.split("_", 2)
        if len(parts) >= 3:
            program_name = parts[2]
            if program_name not in result:
                result[program_name] = []
            result[program_name].append(str(wav_file))

    return result


def _build_reference_library() -> dict[str, list[list[list[float]]]]:
    """
    构建参考音频特征库（真实录音）。

    来源：
      1. 动态扫描 recordings.json（有 normalized_text 的录音）
      2. 硬编码 _REFERENCE_CONFIG（补充无 normalized_text 的录音）

    注意：training_data/wavs/ 的数据已确认存在大量重复和错误标注
    （46 个文件仅 6 个唯一音频，同一音频被标注为不同节目名），
    因此不再作为参考源。仅使用 user_data 中用户实际录音。

    所有音频按内容（MD5）去重，确保同一音频不会被重复计入。
    每个节目名最多保留 _MAX_REFS_PER_PROGRAM 条参考音频，避免样本不平衡。
    """
    global _REFERENCE_CACHE
    if _REFERENCE_CACHE is not None:
        return _REFERENCE_CACHE

    print("🔊 构建音频参考库 (DTW)...", flush=True)
    library: dict[str, list[list[list[float]]]] = {}
    processed_paths: set[str] = set()
    seen_hashes: set[str] = set()  # 按音频内容去重

    def _add_reference(program_name: str, audio_path: str) -> bool:
        """添加一条参考音频，按 MD5 去重。返回是否成功添加。"""
        if audio_path in processed_paths:
            return False
        processed_paths.add(audio_path)

        # 按内容去重
        try:
            import hashlib
            with open(audio_path, 'rb') as f:
                md5 = hashlib.md5(f.read()).hexdigest()
            if md5 in seen_hashes:
                return False
            seen_hashes.add(md5)
        except Exception:
            pass

        # 每个节目名最多 _MAX_REFS_PER_PROGRAM 条参考音频
        if program_name in library and len(library[program_name]) >= _MAX_REFS_PER_PROGRAM:
            return False

        feat = _extract_mfcc_matrix(audio_path)
        if feat is not None:
            if program_name not in library:
                library[program_name] = []
            library[program_name].append(feat)
            return True
        return False

    # 1. 动态扫描 recordings.json（用户实际录音，标签可靠）
    dynamic_refs = _scan_recordings_from_metadata()
    for program_name, audio_paths in dynamic_refs.items():
        for audio_path in audio_paths:
            _add_reference(program_name, audio_path)

    # 2. 硬编码配置补充
    for program_name, rel_paths in _REFERENCE_CONFIG.items():
        for rel_path in rel_paths:
            full_path = _USER_DATA / rel_path
            if not full_path.exists():
                wav_path = str(full_path).rsplit(".", 1)[0] + ".wav"
                if os.path.exists(wav_path):
                    full_path = Path(wav_path)
                else:
                    continue
            _add_reference(program_name, str(full_path))

    for name, feats in library.items():
        print(f"  ✅ {name}: {len(feats)} 条参考音频", flush=True)
    print(f"  📊 真实录音参考库共 {len(library)} 个节目名", flush=True)

    _REFERENCE_CACHE = library
    return library


def rebuild_reference_library() -> dict:
    """重建 DTW 参考库并返回统计信息。

    清空缓存后重新扫描 recordings.json，热更新生效。
    后续 ASR 请求即用新参考库，无需重启服务。

    Returns:
        {
            "programs": {program_name: ref_count, ...},
            "total_programs": int,
            "total_refs": int,
            "max_per_program": int,
        }
    """
    global _REFERENCE_CACHE, _DICTIONARY_TEMPLATE_CACHE
    _REFERENCE_CACHE = None
    _DICTIONARY_TEMPLATE_CACHE = None

    library = _build_reference_library()

    stats = {
        "programs": {name: len(refs) for name, refs in library.items()},
        "total_programs": len(library),
        "total_refs": sum(len(refs) for refs in library.values()),
        "max_per_program": _MAX_REFS_PER_PROGRAM,
    }
    return stats


# ============================================================
# 词典字级发音模板（DTW 增强）
# ============================================================

_DICTIONARY_TEMPLATE_CACHE: Optional[dict[str, list[list[list[float]]]]] = None
_HINGHWA_AUDIO_DIR = _PROJECT_ROOT / "data" / "hinghwa" / "audio"
_HINGHWA_AUDIO_INDEX = _PROJECT_ROOT / "data" / "hinghwa" / "audio_index.json"
_HINGHWA_WORDS = _PROJECT_ROOT / "data" / "hinghwa" / "words.json"
_VOCAB_PATH_FOR_TEMPLATES = _ASR_DIR / "program_vocab.json"

# 三地区标识（audio_index.json 中的 region 字段，不含 county 前缀）
_REGIONS = ["城里", "城关", "游洋"]  # 莆田城里 / 仙游城关 / 仙游游洋


def _build_char_audio_map() -> dict[str, dict[str, list[str]]]:
    """
    构建 字→{地区: [音频路径]} 映射。

    链路：字 → words.json 查拼音 → audio_index.json 按拼音后缀匹配 → 音频路径

    Returns:
        {"江": {"莆田_城里": ["/path/to/gang1.mp3"], "仙游_城关": [...]}, ...}
    """
    if not _HINGHWA_AUDIO_INDEX.exists() or not _HINGHWA_WORDS.exists():
        return {}

    # 1. 从 words.json 构建 字→[拼音] 映射
    from collections import defaultdict
    char_pinyin = defaultdict(set)

    with open(_HINGHWA_WORDS, "r", encoding="utf-8") as f:
        words = json.load(f)

    for entry in words:
        word = entry.get("word", "")
        pinyin = entry.get("standard_pinyin", "")
        if not word or not pinyin:
            continue
        if len(word) == 1:
            char_pinyin[word].add(pinyin)
        else:
            parts = pinyin.split()
            if len(parts) == len(word):
                for char, py in zip(word, parts):
                    if py:
                        char_pinyin[char].add(py)

    # 2. 从 audio_index.json 构建 拼音→{地区: [音频路径]} 映射
    pinyin_audio = defaultdict(lambda: defaultdict(list))

    with open(_HINGHWA_AUDIO_INDEX, "r", encoding="utf-8") as f:
        audio_index = json.load(f)

    for entry in audio_index:
        pinyin_field = entry.get("pinyin", "")  # 如 "城关_ang4"
        filename = entry.get("file", "")

        # 提取拼音后缀（最后一个 "_" 之后的部分）
        if "_" in pinyin_field:
            pinyin_suffix = pinyin_field.rsplit("_", 1)[-1]
        else:
            pinyin_suffix = pinyin_field

        # 提取地区（pinyin_field 中 "_" 之前的部分）
        region = pinyin_field.rsplit("_", 1)[0] if "_" in pinyin_field else ""

        audio_path = _HINGHWA_AUDIO_DIR / filename
        if audio_path.exists() and pinyin_suffix:
            pinyin_audio[pinyin_suffix][region].append(str(audio_path))

    # 3. 匹配：字→拼音→音频
    result: dict[str, dict[str, list[str]]] = {}

    for char, pinyins in char_pinyin.items():
        for py in pinyins:
            if py in pinyin_audio:
                if char not in result:
                    result[char] = {}
                for region, paths in pinyin_audio[py].items():
                    if region not in result[char]:
                        result[char][region] = []
                    result[char][region].extend(paths)

    return result


def _build_dictionary_templates() -> dict[str, list[list[list[float]]]]:
    """
    为无录音或录音少的节目名构建字级发音模板。

    流程：节目名拆字 → 查字→音频映射 → 提取 MFCC → 按字序拼接为参考序列
    三地区模板都要建，取最佳地区分数。

    匹配优先级：真实录音参考 > 词典合成模板

    Returns:
        {program_name: [mfcc_matrix1, ...]} — 每个节目名 1-3 个合成模板（按地区）
    """
    global _DICTIONARY_TEMPLATE_CACHE
    if _DICTIONARY_TEMPLATE_CACHE is not None:
        return _DICTIONARY_TEMPLATE_CACHE

    # 只为有真实录音的节目名之外的那些构建模板
    real_library = _build_reference_library()
    real_programs = set(real_library.keys())

    # 加载节目名词表
    if not _VOCAB_PATH_FOR_TEMPLATES.exists():
        _DICTIONARY_TEMPLATE_CACHE = {}
        return _DICTIONARY_TEMPLATE_CACHE

    with open(_VOCAB_PATH_FOR_TEMPLATES, "r", encoding="utf-8") as f:
        vocab = json.load(f)

    all_programs = [e["canonical"] for e in vocab.get("entries", [])]

    # 构建字→音频映射
    char_audio_map = _build_char_audio_map()
    if not char_audio_map:
        print("  ⚠️ 词典字级音频映射为空，跳过模板构建", flush=True)
        _DICTIONARY_TEMPLATE_CACHE = {}
        return _DICTIONARY_TEMPLATE_CACHE

    print("🔊 构建词典字级发音模板 (DTW 增强)...", flush=True)

    templates: dict[str, list[list[list[float]]]] = {}
    template_details = []

    for program_name in all_programs:
        # 跳过已有真实录音的节目名（真实录音优先）
        if program_name in real_programs:
            continue

        chars = list(program_name)
        # 允许部分字符覆盖（至少 50% 的字有音频即可构建模板）
        min_coverage = max(2, len(chars) // 2)

        char_audio_per_region: dict[str, list[list[list[float]]]] = {}

        for region in _REGIONS:
            char_mfccs = []
            for char in chars:
                if char in char_audio_map and region in char_audio_map[char]:
                    audio_path = char_audio_map[char][region][0]
                    mfcc = _extract_mfcc_matrix(audio_path)
                    if mfcc is not None:
                        char_mfccs.append(mfcc)

            # 检查覆盖率是否达标
            if len(char_mfccs) >= min_coverage:
                # 按字序水平拼接 MFCC 矩阵（沿时间轴）
                # 每个 char_mfcc 是 (39, n_frames_i)，拼接后 (39, sum(n_frames_i))
                try:
                    import numpy as np
                    concatenated = np.hstack(char_mfccs)
                    char_audio_per_region[region] = concatenated.tolist()
                except Exception:
                    # numpy 不可用时用纯 Python 拼接
                    all_frames = []
                    for mfcc in char_mfccs:
                        all_frames.extend(mfcc)  # 每行是一个时间帧
                    # 转置回 (39, total_frames) 格式
                    if all_frames:
                        n_dim = len(all_frames[0])
                        concatenated = [[all_frames[frame][dim] for frame in range(len(all_frames))] for dim in range(n_dim)]
                        char_audio_per_region[region] = concatenated

        if char_audio_per_region:
            if program_name not in templates:
                templates[program_name] = []
            for region, mfcc_matrix in char_audio_per_region.items():
                templates[program_name].append(mfcc_matrix)
            covered_regions = list(char_audio_per_region.keys())
            # 统计每个地区实际有音频的字数
            best_region = max(covered_regions, key=lambda r: sum(1 for c in chars if c in char_audio_map and r in char_audio_map[c]))
            best_covered = sum(1 for c in chars if c in char_audio_map and best_region in char_audio_map[c])
            covered_chars = [c for c in chars if c in char_audio_map and best_region in char_audio_map[c]]
            uncovered_chars = [c for c in chars if c not in covered_chars]
            template_details.append((program_name, len(covered_regions), covered_regions))
            print(f"  📝 {program_name}: {len(covered_regions)} 地区模板, 实际覆盖 {best_covered}/{len(chars)} 字 (有: {''.join(covered_chars)}, 无: {''.join(uncovered_chars)})", flush=True)

    print(f"  📊 词典模板共 {len(templates)} 个节目名", flush=True)

    _DICTIONARY_TEMPLATE_CACHE = templates
    return templates


def add_reference(program_name: str, audio_path: str):
    """
    添加一条新的参考音频到参考库。

    Args:
        program_name: 节目名（canonical）
        audio_path: 音频文件路径
    """
    global _REFERENCE_CACHE

    library = _build_reference_library()

    feat = _extract_mfcc_matrix(audio_path)
    if feat is not None:
        if program_name not in library:
            library[program_name] = []
        library[program_name].append(feat)
        print(f"  ➕ 已添加参考音频: {program_name} ← {os.path.basename(audio_path)}")


# ============================================================
# 匹配主函数
# ============================================================

def match(audio_path: str, threshold: float = _MATCH_THRESHOLD) -> tuple[Optional[str], float]:
    """
    将输入音频与参考库中的节目名进行 DTW 匹配。

    匹配优先级：真实录音参考 > 词典合成模板

    对每个节目名取最近参考录音的 DTW 距离（最小距离），转换为相似度。
    要求最高相似度超过阈值，且与次高相似度的差距达到 margin 要求。

    参考库中每个节目限制最多 5 条参考音频（在构建时截断），
    避免样本数量不平衡导致偏向样本多的节目。

    Args:
        audio_path: 输入音频文件路径
        threshold: 匹配阈值（相似度）

    Returns:
        (program_name, similarity) — 匹配到的节目名和相似度分数。
        如果没有匹配，返回 (None, best_score)。
    """
    _MARGIN = 0.01  # 最高分与次高分的差距要求

    # 1. 真实录音匹配（优先）
    library = _build_reference_library()

    if not library:
        return None, 0.0

    # 提取输入音频的 MFCC 矩阵
    input_feat = _extract_mfcc_matrix(audio_path)
    if input_feat is None:
        return None, 0.0

    # 对每个节目名，计算输入音频与所有参考录音的 DTW 距离，取最小值
    program_results: list[tuple[str, float, float]] = []  # (name, min_dist, similarity)

    for program_name, ref_features in library.items():
        best_dist = float('inf')
        for ref_feat in ref_features:
            dtw_dist = _dtw_distance(input_feat, ref_feat)
            if dtw_dist < best_dist:
                best_dist = dtw_dist

        if best_dist != float('inf'):
            sim = _dtw_to_similarity(best_dist)
            program_results.append((program_name, best_dist, sim))

    if program_results:
        # 按距离升序排序（距离越小越相似）
        program_results.sort(key=lambda x: x[1])

        best_match, best_dist, best_sim = program_results[0]
        second_sim = program_results[1][2] if len(program_results) > 1 else 0.0

        # 检查阈值和间距
        if best_sim >= threshold and (best_sim - second_sim) >= _MARGIN:
            return best_match, best_sim

        # 如果只有一个节目名且分数较高，也返回
        if len(program_results) == 1 and best_sim >= threshold:
            return best_match, best_sim

    # 2. 词典合成模板匹配（真实录音未命中时的兜底）
    dict_templates = _build_dictionary_templates()
    if dict_templates:
        template_results: list[tuple[str, float, float]] = []

        for program_name, ref_features in dict_templates.items():
            best_dist = float('inf')
            for ref_feat in ref_features:
                dtw_dist = _dtw_distance(input_feat, ref_feat)
                if dtw_dist < best_dist:
                    best_dist = dtw_dist

            if best_dist != float('inf'):
                sim = _dtw_to_similarity(best_dist)
                template_results.append((program_name, best_dist, sim))

        if template_results:
            template_results.sort(key=lambda x: x[1])

            # 词典模板使用更高阈值（合成模板可靠性较低）
            dict_threshold = max(threshold, 0.4)
            best_match, best_dist, best_sim = template_results[0]
            second_sim = template_results[1][2] if len(template_results) > 1 else 0.0

            if best_sim >= dict_threshold and (best_sim - second_sim) >= _MARGIN:
                return best_match, best_sim

    # 返回真实录音的最高分（即使未达阈值）
    if program_results:
        return None, program_results[0][2]
    return None, 0.0


def get_status() -> dict:
    """获取音频匹配器的状态信息。"""
    library = _build_reference_library()
    dict_templates = _build_dictionary_templates()

    # 合并真实录音和模板的节目名覆盖情况
    all_programs = {}
    for name, feats in library.items():
        all_programs[name] = {"real_recordings": len(feats), "dict_templates": 0}
    for name, feats in dict_templates.items():
        if name not in all_programs:
            all_programs[name] = {"real_recordings": 0, "dict_templates": len(feats)}
        else:
            all_programs[name]["dict_templates"] = len(feats)

    return {
        "reference_count": sum(len(v) for v in library.values()),
        "template_count": sum(len(v) for v in dict_templates.values()),
        "programs": all_programs,
        "threshold": _MATCH_THRESHOLD,
        "method": "DTW",
        "user_data_path": str(_USER_DATA),
    }


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python audio_matcher.py <音频文件>")
        print("      python audio_matcher.py --status  (查看参考库状态)")
        sys.exit(1)

    if sys.argv[1] == "--status":
        status = get_status()
        print(json.dumps(status, indent=2, ensure_ascii=False))
        sys.exit(0)

    audio_file = sys.argv[1]
    if not os.path.exists(audio_file):
        print(f"文件不存在: {audio_file}")
        sys.exit(1)

    match_result, score = match(audio_file)
    if match_result:
        print(f"✅ 匹配: {match_result} (相似度: {score:.3f})")
    else:
        print(f"❌ 未匹配 (最高相似度: {score:.3f})")

    print(f"\n参考库: {get_status()}")
