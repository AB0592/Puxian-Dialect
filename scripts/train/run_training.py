#!/usr/bin/env python3
"""端到端训练编排脚本 — 一键完成 LoRA 微调。

自动执行完整流程：
  1. 检查/安装依赖
  2. 准备训练数据
  3. 运行 LoRA 微调
  4. 合并权重并注册模型
  5. 可选：自动激活

用法：
  # 全自动（使用示例数据）
  python run_training.py --auto

  # 指定数据集
  python run_training.py --dataset_id ds-xxx --activate

  # 自定义参数
  python run_training.py \
    --base_model openai/whisper-small \
    --lora_r 16 --lora_alpha 32 \
    --num_epochs 5 --batch_size 4 \
    --model_name "莆仙话Whisper微调v1" \
    --activate
"""

import sys
import os
import subprocess
from pathlib import Path

# ============================================================
# 离线模式 — 防止 transformers/HuggingFace 尝试联网
# ============================================================

os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

# 添加 scripts 目录到 path
SCRIPTS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

PROJECT_ROOT = SCRIPTS_DIR.parent
TRAIN_DIR = Path(__file__).parent
WORKSPACE_DIR = PROJECT_ROOT / "training_data" / "finetune_workspace"


# ============================================================
# 依赖检查与安装
# ============================================================

REQUIRED_PACKAGES = {
    "torch": "torch>=2.0.0",
    "transformers": "transformers>=4.36.0",
    "peft": "peft>=0.7.0",
    "librosa": "librosa>=0.10.0",
    "numpy": "numpy>=1.24.0",
    "datasets": "datasets>=2.14.0",
    "accelerate": "accelerate>=0.24.0",
}


def check_package(pkg_name: str) -> bool:
    """检查包是否已安装。"""
    try:
        __import__(pkg_name)
        return True
    except ImportError:
        return False


def install_package(pip_name: str):
    """安装 pip 包。"""
    print(f"  📦 安装 {pip_name} ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", pip_name, "--break-system-packages"],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"  ❌ 安装失败: {pip_name}")
        print(f"     {result.stderr[:300]}")
        return False
    return True


def ensure_dependencies(auto_install: bool = False) -> bool:
    """确保所有依赖包已安装。"""
    print("\n📋 检查依赖包...")
    missing = []
    for pkg_name, pip_name in REQUIRED_PACKAGES.items():
        if check_package(pkg_name):
            print(f"  ✅ {pkg_name}")
        else:
            print(f"  ❌ {pkg_name} 未安装")
            missing.append((pkg_name, pip_name))

    if not missing:
        print("  ✅ 所有依赖已安装")
        return True

    if not auto_install:
        print(f"\n⚠️ 缺少 {len(missing)} 个依赖包:")
        for pkg_name, pip_name in missing:
            print(f"   - {pip_name}")
        print(f"\n请运行安装命令:")
        print(f"  pip install {' '.join(p for _, p in missing)} --break-system-packages")
        print(f"\n或使用 --auto 参数自动安装")
        return False

    print(f"\n🔧 自动安装 {len(missing)} 个依赖包...")
    for pkg_name, pip_name in missing:
        if not install_package(pip_name):
            print(f"  ⚠️ {pip_name} 安装失败，请手动安装")
            return False
        print(f"  ✅ {pip_name} 安装成功")

    return True


# ============================================================
# 训练步骤
# ============================================================

def step1_prepare_data(dataset_id: str = "", val_ratio: float = 0.2) -> dict:
    """步骤 1：准备训练数据。"""
    print("\n" + "=" * 60)
    print("  步骤 1/4：准备训练数据")
    print("=" * 60)

    from train.prepare_data import prepare

    result = prepare(
        dataset_id=dataset_id,
        output_dir=str(WORKSPACE_DIR),
        val_ratio=val_ratio,
    )

    print(f"\n  ✅ 数据准备完成")
    print(f"     训练集: {result['train_count']} 个样本 → {result['train_path']}")
    print(f"     验证集: {result['val_count']} 个样本 → {result['val_path']}")

    return result


def step2_finetune(
    train_jsonl: str,
    val_jsonl: str,
    output_dir: str,
    base_model: str = "openai/whisper-small",
    lora_r: int = 16,
    lora_alpha: int = 32,
    lora_dropout: float = 0.05,
    learning_rate: float = 1e-4,
    num_epochs: int = 3,
    batch_size: int = 8,
    use_8bit: bool = False,
) -> str:
    """步骤 2：运行 LoRA 微调。"""
    print("\n" + "=" * 60)
    print("  步骤 2/4：LoRA 微调训练")
    print("=" * 60)

    from train.finetune_whisper import train as run_train
    import argparse

    args = argparse.Namespace(
        train_jsonl=train_jsonl,
        val_jsonl=val_jsonl,
        output_dir=output_dir,
        base_model=base_model,
        lora_r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        learning_rate=learning_rate,
        num_epochs=num_epochs,
        batch_size=batch_size,
        language="Chinese",
        use_8bit=use_8bit,
    )

    run_train(args)

    print(f"\n  ✅ 训练完成")
    print(f"     LoRA 适配器: {output_dir}")

    return output_dir


def step3_merge_and_register(
    lora_path: str,
    base_model: str,
    model_name: str,
    description: str,
    dataset_id: str,
    activate: bool,
) -> dict:
    """步骤 3：合并权重并注册。"""
    print("\n" + "=" * 60)
    print("  步骤 3/4：合并权重 + 注册模型")
    print("=" * 60)

    merged_dir = str(WORKSPACE_DIR / "merged_model")

    from train.merge_and_register import merge_lora, register_model

    merged_path = merge_lora(
        lora_path=lora_path,
        base_model=base_model,
        merged_dir=merged_dir,
    )

    meta = register_model(
        model_path=merged_path,
        name=model_name,
        description=description,
        dataset_id=dataset_id,
        activate=activate,
    )

    return meta


def step4_verify(activate: bool):
    """步骤 4：验证结果。"""
    print("\n" + "=" * 60)
    print("  步骤 4/4：验证")
    print("=" * 60)

    from asr.local_model_manager import get_model_status

    status = get_model_status()
    print(f"  活跃引擎: {status['active_engine']}")
    print(f"  微调模型数量: {len(status['finetune_models'])}")

    if status["finetune_models"]:
        for m in status["finetune_models"]:
            active = "🟢" if status["active_engine"] == "finetuned" else "⚪"
            print(f"    {active} {m.get('name', '未命名')} ({m.get('engine', '?')}) — {m.get('model_id', '?')}")

    if activate and status["active_engine"] == "finetuned":
        print(f"\n  ✅ 微调模型已激活！")
        print(f"     后续使用 provider=local 的语音识别将自动使用微调模型")
    elif activate:
        print(f"\n  ⚠️ 微调模型未成功激活，请检查配置")


# ============================================================
# 主函数
# ============================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="端到端 LoRA 微调训练流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 全自动（安装依赖 + 使用示例数据 + 激活）
  python run_training.py --auto --activate

  # 使用指定数据集
  python run_training.py --dataset_id ds-xxx --activate

  # 自定义训练参数
  python run_training.py --lora_r 32 --num_epochs 10 --batch_size 4
        """,
    )
    parser.add_argument("--auto", action="store_true",
                        help="自动安装缺失依赖")
    parser.add_argument("--dataset_id", default="",
                        help="数据集 ID（留空则自动选择或生成示例数据）")
    parser.add_argument("--base_model", default="openai/whisper-small",
                        help="基础模型（默认: openai/whisper-small）")
    parser.add_argument("--lora_r", type=int, default=16,
                        help="LoRA 秩（默认: 16）")
    parser.add_argument("--lora_alpha", type=int, default=32,
                        help="LoRA alpha（默认: 32）")
    parser.add_argument("--lora_dropout", type=float, default=0.05,
                        help="LoRA dropout（默认: 0.05）")
    parser.add_argument("--learning_rate", type=float, default=1e-4,
                        help="学习率（默认: 1e-4）")
    parser.add_argument("--num_epochs", type=int, default=3,
                        help="训练轮数（默认: 3）")
    parser.add_argument("--batch_size", type=int, default=8,
                        help="批大小（默认: 8）")
    parser.add_argument("--use_8bit", action="store_true",
                        help="使用 8-bit 量化 (QLoRA，显存不足时使用)")
    parser.add_argument("--val_ratio", type=float, default=0.2,
                        help="验证集比例（默认: 0.2）")
    parser.add_argument("--model_name", default="莆仙话Whisper微调v1",
                        help="模型名称")
    parser.add_argument("--description", default="LoRA微调模型",
                        help="模型描述")
    parser.add_argument("--activate", action="store_true",
                        help="训练完成后自动激活为当前模型")
    parser.add_argument("--skip_train", action="store_true",
                        help="跳过训练步骤（已有 LoRA 适配器时使用）")
    parser.add_argument("--lora_path", default="",
                        help="已有的 LoRA 适配器路径（--skip_train 时使用）")

    args = parser.parse_args()

    print("=" * 60)
    print("  莆仙话 Whisper LoRA 微调训练流水线")
    print("=" * 60)

    # 步骤 0：检查依赖
    if not ensure_dependencies(auto_install=args.auto):
        sys.exit(1)

    # 确保工作目录存在
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    # 步骤 1：准备数据
    data = step1_prepare_data(
        dataset_id=args.dataset_id,
        val_ratio=args.val_ratio,
    )

    # 步骤 2：训练
    if args.skip_train and args.lora_path:
        lora_output = args.lora_path
        print(f"\n  ⏭️ 跳过训练，使用已有 LoRA 适配器: {lora_output}")
    else:
        lora_output = step2_finetune(
            train_jsonl=data["train_path"],
            val_jsonl=data["val_path"],
            output_dir=str(WORKSPACE_DIR / "lora_output"),
            base_model=args.base_model,
            lora_r=args.lora_r,
            lora_alpha=args.lora_alpha,
            lora_dropout=args.lora_dropout,
            learning_rate=args.learning_rate,
            num_epochs=args.num_epochs,
            batch_size=args.batch_size,
            use_8bit=args.use_8bit,
        )

    # 步骤 3：合并 + 注册
    meta = step3_merge_and_register(
        lora_path=lora_output,
        base_model=args.base_model,
        model_name=args.model_name,
        description=args.description,
        dataset_id=args.dataset_id,
        activate=args.activate,
    )

    # 步骤 4：验证
    step4_verify(activate=args.activate)

    # 完成
    print("\n" + "=" * 60)
    print("  🎉 训练流水线完成！")
    print("=" * 60)
    print(f"  模型 ID: {meta['model_id']}")
    print(f"  模型名称: {meta['name']}")
    if args.activate:
        print(f"  状态: 已激活")
        print(f"\n  现在可以在前端选择 provider=local 使用微调模型了！")
    else:
        print(f"  状态: 已注册（未激活）")
        print(f"  激活: curl -X POST http://localhost:8520/api/v1/model/finetune/activate/{meta['model_id']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
