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

# Sakoe-Chiba 带宽约束（限制 DTW 路径偏离对角线的范围，防止病态规整）
# 设为 0 表示不约束；设为正整数表示允许偏离对角线的最大帧数
_SAKOE_CHIBA_RATIO = 0.3  # 允许偏离对角线的比例为 30%

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


def _build_reference_library() -> dict[str, list[list[list[float]]]]:
    """
    构建参考音频特征库。

    来源：
      1. 动态扫描 recordings.json（有 normalized_text 的录音）
      2. 硬编码 _REFERENCE_CONFIG（补充无 normalized_text 的录音）

    两者合并去重。
    """
    global _REFERENCE_CACHE
    if _REFERENCE_CACHE is not None:
        return _REFERENCE_CACHE

    print("🔊 构建音频参考库 (DTW)...", flush=True)
    library: dict[str, list[list[list[float]]]] = {}
    processed_paths: set[str] = set()

    # 1. 动态扫描 recordings.json
    dynamic_refs = _scan_recordings_from_metadata()
    for program_name, audio_paths in dynamic_refs.items():
        features = []
        for audio_path in audio_paths:
            if audio_path in processed_paths:
                continue
            processed_paths.add(audio_path)
            feat = _extract_mfcc_matrix(audio_path)
            if feat is not None:
                features.append(feat)
        if features:
            library[program_name] = features

    # 2. 硬编码配置补充
    for program_name, rel_paths in _REFERENCE_CONFIG.items():
        features = library.get(program_name, [])
        for rel_path in rel_paths:
            full_path = _USER_DATA / rel_path
            if not full_path.exists():
                wav_path = str(full_path).rsplit(".", 1)[0] + ".wav"
                if os.path.exists(wav_path):
                    full_path = Path(wav_path)
                else:
                    continue

            abs_path = str(full_path)
            if abs_path in processed_paths:
                continue
            processed_paths.add(abs_path)

            feat = _extract_mfcc_matrix(abs_path)
            if feat is not None:
                features.append(feat)

        if features:
            library[program_name] = features

    for name, feats in library.items():
        print(f"  ✅ {name}: {len(feats)} 条参考音频", flush=True)
    print(f"  📊 参考库共 {len(library)} 个节目名", flush=True)

    _REFERENCE_CACHE = library
    return library


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
    将输入音频与参考库中的节目名进行 DTW 相似度匹配。

    对每个节目名取最近参考录音的 DTW 距离（最小距离），转换为相似度。
    要求最高相似度超过阈值，且与次高相似度的差距达到 margin 要求。

    Args:
        audio_path: 输入音频文件路径
        threshold: 匹配阈值（相似度）

    Returns:
        (program_name, similarity) — 匹配到的节目名和相似度分数。
        如果没有匹配，返回 (None, best_score)。
    """
    library = _build_reference_library()

    if not library:
        return None, 0.0

    # 提取输入音频的 MFCC 矩阵
    input_feat = _extract_mfcc_matrix(audio_path)
    if input_feat is None:
        return None, 0.0

    # 对每个节目名，计算输入音频与所有参考录音的 DTW 距离
    program_results: list[tuple[str, float, float]] = []  # (name, min_dist, similarity)

    for program_name, ref_features in library.items():
        best_dist = float('inf')
        for ref_feat in ref_features:
            dtw_dist = _dtw_distance(input_feat, ref_feat)
            # 跳过自身（距离为 0，留一法用）
            if dtw_dist > 0.001 and dtw_dist < best_dist:
                best_dist = dtw_dist

        if best_dist != float('inf'):
            sim = _dtw_to_similarity(best_dist)
            program_results.append((program_name, best_dist, sim))

    if not program_results:
        return None, 0.0

    # 按距离升序排序（距离越小越相似）
    program_results.sort(key=lambda x: x[1])

    best_match, best_dist, best_sim = program_results[0]
    second_sim = program_results[1][2] if len(program_results) > 1 else 0.0

    # 检查阈值和间距
    if best_sim >= threshold and (best_sim - second_sim) >= _MARGIN_THRESHOLD:
        return best_match, best_sim

    # 如果只有一个节目名且分数较高，也返回
    if len(program_results) == 1 and best_sim >= threshold:
        return best_match, best_sim

    return None, best_sim


def get_status() -> dict:
    """获取音频匹配器的状态信息。"""
    library = _build_reference_library()
    return {
        "reference_count": sum(len(v) for v in library.values()),
        "programs": {name: len(feats) for name, feats in library.items()},
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
