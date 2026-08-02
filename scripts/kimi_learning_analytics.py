#!/usr/bin/env python3
"""
Kimi K2.6 学情分析引擎 — 长会话训练数据分析

定位: 异步分析脑，不参与实时语音链。
用途:
  1. 学情追踪 — 分析用户训练记录，识别薄弱点
  2. 错误模式聚类 — 发现重复发音错误
  3. 个性化教案生成 — 基于完整学习历史生成定制四级素材

工作原理:
  - 每天从训练日志中提取数据
  - 用 Kimi K2.6 的 256K 上下文 + 思考模式分析
  - 生成结构化分析报告
  - 存入 Hindsight 长期记忆

Pre-requisites:
  - KIMI_API_KEY 已在 .env 中
  - pip3 install openai
"""

import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from collections import Counter

# ============================================================
# 配置
# ============================================================

KIMI_MODEL = "kimi-k2.6"
KIMI_BASE_URL = "https://api.moonshot.cn/v1"
KIMI_MAX_CONTEXT = 256000

PROFILE_DIR = Path(__file__).parent.parent
TRAINING_LOG_DIR = PROFILE_DIR / "training_logs"
REPORT_DIR = PROFILE_DIR / "learning_reports"

# 全局缓存
_KIMI_API_KEY: Optional[str] = None


def _get_api_key() -> str:
    """从 .env 获取 Kimi API Key"""
    global _KIMI_API_KEY
    if _KIMI_API_KEY:
        return _KIMI_API_KEY

    env_keys = ["KIMI_API_KEY", "KIMI_CN_API_KEY"]
    env_paths = [
        PROFILE_DIR / ".env",
        Path("/Users/sagaai/.hermes/hermes-agent/.env"),
    ]

    for env_path in env_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    for key_name in env_keys:
                        if line.startswith(key_name + "="):
                            key = line.split("=", 1)[1].strip().strip("'\"").strip()
                            if key:
                                _KIMI_API_KEY = key
                                return key
    return ""


# ============================================================
# 训练数据加载
# ============================================================

def collect_training_data(days: int = 7) -> Dict:
    """
    收集最近 N 天的训练数据。
    
    数据来源:
      - dialect_map.json 的 add 日志 (新学词汇)
      - user_data/{username}/ 下的 training 记录
      - putian_trainer.py 的 session 数据
    """
    data = {
        "period": f"最近 {days} 天",
        "new_words": [],
        "training_sessions": [],
        "errors": [],
        "total_items": 0,
    }

    # 1. 从 dialect_map.json 统计新增词汇
    map_path = PROFILE_DIR / "dialect_map.json"
    if map_path.exists():
        try:
            mtime = map_path.stat().st_mtime
            days_ago = datetime.fromtimestamp(mtime)
            if (datetime.now() - days_ago).days <= days:
                with open(map_path, "r", encoding="utf-8") as f:
                    dialect_map = json.load(f)
                data["total_items"] = len(dialect_map)
                # 统计各语言新增
                data["map_size"] = {
                    "total": len(dialect_map),
                    "recently_modified": (datetime.now() - days_ago).days <= 7,
                }
        except Exception as e:
            data["map_load_error"] = str(e)

    # 2. 遍历用户目录
    user_data_dir = PROFILE_DIR / "user_data"
    if user_data_dir.exists():
        for user_dir in user_data_dir.iterdir():
            if not user_dir.is_dir():
                continue
            profile_path = user_dir / "profile.json"
            if profile_path.exists():
                try:
                    with open(profile_path) as f:
                        profile = json.load(f)
                    # 兼容 preferred_lang（新）和 dialect（旧）字段名
                    user_dialect = profile.get("preferred_lang", profile.get("dialect", "unknown"))
                    data["training_sessions"].append({
                        "user": user_dir.name,
                        "dialect": user_dialect,
                        "last_active": profile.get("last_active", ""),
                        "total_trained": profile.get("total_trained", 0),
                        "accuracy": profile.get("accuracy", 0),
                    })
                except Exception:
                    pass

    return data


# ============================================================
# Kimi K2.6 分析
# ============================================================

def _build_analysis_prompt(training_data: Dict) -> str:
    """构建 Kimi K2.6 分析 prompt"""
    return f"""你是一位方言语言教学专家。请分析以下训练数据并生成学情报告。

## 训练数据

训练周期: {training_data['period']}
词汇总量: {training_data.get('total_items', 'N/A')} 条
训练会话: {json.dumps(training_data.get('training_sessions', []), ensure_ascii=False, indent=2)}

## 分析任务

请按以下结构输出报告:

### 1. 学习进度摘要
- 新增词汇数量
- 活跃用户
- 训练频次

### 2. 薄弱点识别
- 哪些方言词汇/发音反复出现问题
- 可能的原因（声调混淆/韵母错误/不熟悉）

### 3. 错误模式聚类
- 按音系特征分组
- 高频错误类型 TOP 5

### 4. 个性化建议
- 针对每个用户的推荐训练素材（字/词/句/文章四级）
- 每日训练量建议

### 5. 下周预测
- 预计能掌握多少新词
- 哪些词最值得优先学（高频使用）

用中文输出。不要使用 Markdown 表格，用加粗标题 + 列表格式。"""


def analyze_with_kimi(training_data: Dict) -> Dict:
    """
    用 Kimi K2.6 分析训练数据。
    
    返回分析报告 dict。
    """
    import openai

    api_key = _get_api_key()
    if not api_key:
        return {"error": "KIMI_API_KEY 未配置", "report": ""}

    client = openai.OpenAI(
        api_key=api_key,
        base_url=KIMI_BASE_URL,
    )

    prompt = _build_analysis_prompt(training_data)
    print(f"  -> Kimi K2.6: 分析训练数据 ({len(prompt)} chars)")

    try:
        response = client.chat.completions.create(
            model=KIMI_MODEL,
            messages=[
                {"role": "system", "content": "你是方言语言教学分析专家。输出结构化的学情报告。"},
                {"role": "user", "content": prompt},
            ],
            temperature=1.0,
            max_tokens=8000,
        )

        report = response.choices[0].message.content
        tokens = response.usage.total_tokens if response.usage else 0
        print(f"  -> 分析完成: {len(report)} chars, {tokens} tokens")

        return {
            "report": report,
            "tokens_used": tokens,
            "model": KIMI_MODEL,
            "timestamp": datetime.now().isoformat(),
            "data_summary": {
                "sessions": len(training_data.get("training_sessions", [])),
                "total_items": training_data.get("total_items", 0),
            },
        }

    except Exception as e:
        print(f"  -> Kimi 分析失败: {e}")
        return {"error": str(e), "report": ""}


# ============================================================
# 报告持久化
# ============================================================

def save_report(analysis: Dict) -> str:
    """保存分析报告到文件"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"learning_report_{timestamp}.json"

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    print(f"  -> 报告已保存: {report_path}")
    return str(report_path)


def get_recent_reports(limit: int = 5) -> List[Dict]:
    """获取最近的学情报告"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    reports = []
    for f in sorted(REPORT_DIR.glob("learning_report_*.json"), reverse=True):
        try:
            with open(f) as fp:
                data = json.load(fp)
            data["_file"] = str(f)
            reports.append(data)
        except Exception:
            pass
        if len(reports) >= limit:
            break

    return reports


# ============================================================
# 统一入口
# ============================================================

def run_analysis(days: int = 7) -> Dict:
    """
    运行完整学情分析流程:
      1. 收集训练数据
      2. Kimi K2.6 分析
      3. 保存报告
    """
    print(f"\n{'='*60}")
    print(f"方言学情分析 — Kimi K2.6")
    print(f"{'='*60}")

    # Step 1: 收集数据
    print("\n[Step 1] 收集训练数据...")
    training_data = collect_training_data(days)
    print(f"  -> {len(training_data['training_sessions'])} 个用户会话")

    # Step 2: Kimi 分析
    print("\n[Step 2] Kimi K2.6 分析...")
    analysis = analyze_with_kimi(training_data)

    if analysis.get("error"):
        print(f"  [FAIL] 分析失败: {analysis['error']}")
        return analysis

    # Step 3: 保存
    print("\n[Step 3] 保存报告...")
    report_path = save_report(analysis)

    return {
        **analysis,
        "report_path": report_path,
        "status": "success",
    }


def format_report_for_reading(analysis: Dict) -> str:
    """将分析报告格式化为可读文本"""
    report = analysis.get("report", "")
    if not report:
        return "无分析内容"

    summary = f"""**学情分析报告**
**时间**: {analysis.get('timestamp', 'N/A')}
**模型**: `{analysis.get('model', 'N/A')}`
**Token**: {analysis.get('tokens_used', 0)}

{report}
"""
    return summary


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 kimi_learning_analytics.py analyze [天数]")
        print("  python3 kimi_learning_analytics.py history [条数]")
        print()
        print(f"KIMI_API_KEY 状态: {'已配置' if _get_api_key() else '未配置'}")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "analyze":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        result = run_analysis(days)
        if result.get("status") == "success":
            print("\n" + "=" * 60)
            print(result["report"])
        else:
            print(f"\n[FAIL] {result.get('error', '未知错误')}")

    elif cmd == "history":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        reports = get_recent_reports(limit)
        print(f"最近 {len(reports)} 份报告:\n")
        for i, r in enumerate(reports, 1):
            ts = r.get("timestamp", "N/A")[:16]
            tokens = r.get("tokens_used", 0)
            print(f"  {i}. {ts}  ({tokens} tokens)")

    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)
