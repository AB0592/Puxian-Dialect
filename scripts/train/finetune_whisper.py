#!/usr/bin/env python3
"""
Whisper LoRA 微调脚本 — 莆仙话方言适配

使用 PEFT/LoRA 对 OpenAI Whisper 模型进行参数高效微调，
使其适应莆仙话（莆田方言）的语音识别任务。

数据格式（JSONL，每行一个 JSON 对象）：
  {"audio": {"path": "/path/to/audio.wav"}, "sentence": "莆仙话文本", "language": "Chinese"}
  或
  {"audio": "/path/to/audio.wav", "text": "莆仙话文本"}
  或
  {"source": "/path/to/audio.wav", "target": "莆仙话文本"}

用法:
    python finetune_whisper.py \\
        --train_jsonl data/train.jsonl \\
        --val_jsonl data/val.jsonl \\
        --output_dir ./output \\
        --base_model openai/whisper-small \\
        --lora_r 16 --lora_alpha 32 \\
        --num_epochs 3 --batch_size 8

依赖:
    pip install torch transformers peft librosa soundfile numpy
    (可选) pip install bitsandbytes  # 用于 8-bit 量化 (QLoRA)
"""

import sys
import json
import os
import time
import argparse
import warnings
from pathlib import Path

# ============================================================
# 离线模式 — 防止 transformers 尝试联网下载模型
# ============================================================

os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

# ============================================================
# 将父级 scripts 目录加入 sys.path，以便导入同级模块
# ============================================================

SCRIPTS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

# ============================================================
# 依赖检查 — 友好的错误提示
# ============================================================

try:
    import torch
except ImportError:
    print("=" * 60)
    print("错误: 未安装 PyTorch")
    print("请运行: pip install torch")
    print("=" * 60)
    sys.exit(1)

try:
    from transformers import (
    WhisperProcessor,
    WhisperForConditionalGeneration,
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
    EarlyStoppingCallback,
)
except ImportError:
    print("=" * 60)
    print("错误: 未安装 transformers")
    print("请运行: pip install transformers")
    print("=" * 60)
    sys.exit(1)

try:
    from peft import LoraConfig, get_peft_model
except ImportError:
    print("=" * 60)
    print("错误: 未安装 peft")
    print("请运行: pip install peft")
    print("=" * 60)
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    print("=" * 60)
    print("错误: 未安装 numpy")
    print("请运行: pip install numpy")
    print("=" * 60)
    sys.exit(1)

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False

try:
    import soundfile as sf
    SOUNDFILE_AVAILABLE = True
except ImportError:
    SOUNDFILE_AVAILABLE = False

if not LIBROSA_AVAILABLE and not SOUNDFILE_AVAILABLE:
    print("=" * 60)
    print("错误: librosa 和 soundfile 均未安装")
    print("请运行: pip install librosa soundfile")
    print("至少需要其中一个来加载音频文件")
    print("=" * 60)
    sys.exit(1)


# ============================================================
# 设备选择 — 支持 CUDA / MPS (Apple Silicon) / CPU
# ============================================================

def _select_device():
    """选择计算设备"""
    if torch.cuda.is_available():
        return "cuda"
    try:
        if torch.backends.mps.is_available():
            return "mps"
    except (AttributeError, RuntimeError):
        pass
    return "cpu"


DEVICE = _select_device()

# 采样率 — Whisper 特征提取器要求 16kHz 单声道
SAMPLING_RATE = 16000


# ============================================================
# 训练数据集
# ============================================================

class WhisperLoRADataset(torch.utils.data.Dataset):
    """Whisper LoRA 训练数据集

    读取 JSONL 格式的训练数据，加载音频文件，
    使用 WhisperProcessor 处理音频和文本，
    返回 input_features (log-mel 频谱图) 和 labels (token IDs)。

    支持的 JSONL 字段：
      - audio: {"path": "..."} 或 "..."（音频文件路径）
      - sentence / text / target: 转写文本
      - language: 语言（可选，默认使用初始化参数）
    """

    def __init__(self, jsonl_path, processor, language="Chinese",
                 sampling_rate=SAMPLING_RATE):
        """
        Args:
            jsonl_path: JSONL 文件路径
            processor: WhisperProcessor 实例
            language: 语言名称（如 "Chinese"）
            sampling_rate: 采样率（默认 16000）
        """
        self.processor = processor
        self.language = language
        self.sampling_rate = sampling_rate
        self.samples = []

        jsonl_path = Path(jsonl_path)
        if not jsonl_path.exists():
            raise FileNotFoundError(f"JSONL 文件不存在: {jsonl_path}")

        # 读取 JSONL 文件
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    warnings.warn(
                        f"跳过无法解析的 JSON 行 (第 {line_num} 行): "
                        f"{line[:80]}..."
                    )
                    continue

                # 解析音频路径 — 兼容多种字段格式
                audio_field = entry.get("audio", entry.get("source", ""))
                if isinstance(audio_field, dict):
                    audio_path = audio_field.get("path", "")
                else:
                    audio_path = audio_field

                # 解析文本 — 兼容多种字段名
                text = (entry.get("sentence")
                        or entry.get("text")
                        or entry.get("target")
                        or "")

                # 解析语言（可选，覆盖默认值）
                entry_language = entry.get("language", language)

                if audio_path and text:
                    self.samples.append({
                        "audio_path": audio_path,
                        "text": text.strip(),
                        "language": entry_language,
                    })

        print(f"📦 加载数据: {jsonl_path} — {len(self.samples)} 个样本")

        # 预检查音频文件是否存在
        missing = [s["audio_path"] for s in self.samples
                   if not Path(s["audio_path"]).exists()]
        if missing:
            print(f"⚠️ {len(missing)} 个音频文件不存在（将在训练时跳过）")
            for path in missing[:5]:
                print(f"   - {path}")
            if len(missing) > 5:
                print(f"   ... 还有 {len(missing) - 5} 个")

    def __len__(self):
        return len(self.samples)

    def _load_audio(self, audio_path):
        """加载音频文件，返回 16kHz 单声道 numpy 数组"""
        if LIBROSA_AVAILABLE:
            audio, sr = librosa.load(
                audio_path, sr=self.sampling_rate, mono=True
            )
        else:
            audio, sr = sf.read(audio_path)
            # 确保单声道
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            # 重采样到目标采样率
            if sr != self.sampling_rate:
                num_samples = int(len(audio) * self.sampling_rate / sr)
                audio = np.interp(
                    np.linspace(0, len(audio), num_samples),
                    np.arange(len(audio)),
                    audio,
                )
        return audio.astype(np.float32)

    def __getitem__(self, idx):
        """获取单个样本，处理音频和文本

        如果音频文件不存在或加载失败，自动跳到下一个样本。
        """
        # 遍历查找有效样本（跳过不存在的音频文件）
        for attempt in range(len(self)):
            actual_idx = (idx + attempt) % len(self)
            sample = self.samples[actual_idx]
            audio_path = sample["audio_path"]
            text = sample["text"]

            # 检查音频文件是否存在
            if not Path(audio_path).exists():
                warnings.warn(f"⚠️ 音频文件不存在，跳过: {audio_path}")
                continue

            try:
                # 加载音频
                audio = self._load_audio(audio_path)

                # 处理音频 -> input_features (log-mel 频谱图)
                input_features = self.processor.feature_extractor(
                    audio,
                    sampling_rate=self.sampling_rate,
                    return_tensors="pt",
                ).input_features[0]

                # 处理文本 -> labels (token IDs)
                labels = self.processor.tokenizer(text).input_ids

                return {
                    "input_features": input_features,
                    "labels": labels,
                }

            except Exception as e:
                warnings.warn(
                    f"⚠️ 加载音频失败，跳过: {audio_path} — {e}"
                )
                continue

        raise RuntimeError("所有音频文件都无法加载，请检查数据路径")


# ============================================================
# 数据整理器
# ============================================================

class DataCollatorSeq2SeqWithPadding:
    """Seq2Seq 数据整理器 — 填充 input_features 和 labels

    将多个样本的 input_features 和 labels 整理成一个 batch，
    自动处理填充和 -100 掩码（padding 部分不参与 loss 计算）。

    注意：输出 batch 中使用 'input_ids' 作为键名（而非 'input_features'），
    以兼容 PEFT 的 PeftModelForSeq2SeqLM.forward() 签名。
    """

    def __init__(self, processor):
        """
        Args:
            processor: WhisperProcessor 实例
        """
        self.processor = processor

    def __call__(self, features):
        # 分离 input_features 和 labels
        input_features = [
            {"input_features": f["input_features"]} for f in features
        ]
        label_features = [{"input_ids": f["labels"]} for f in features]

        # 填充 input_features（Whisper 特征长度固定，主要是 batch 化）
        batch = self.processor.feature_extractor.pad(
            input_features, return_tensors="pt"
        )

        # 填充 labels
        labels_batch = self.processor.tokenizer.pad(
            label_features, return_tensors="pt"
        )

        # 将 padding 部分替换为 -100（不参与 loss 计算）
        labels = labels_batch["input_ids"].masked_fill(
            labels_batch.attention_mask.ne(1), -100
        )

        # 如果 tokenizer 自动添加了 BOS token，移除它
        if (labels[:, 0] == self.processor.tokenizer.bos_token_id).all():
            labels = labels[:, 1:]

        batch["labels"] = labels

        # 将 input_features 重命名为 input_ids，以兼容 PEFT 的 forward 签名
        # PEFT PeftModelForSeq2SeqLM.forward() 使用 input_ids 而非 input_features
        batch["input_ids"] = batch.pop("input_features")

        return batch


# ============================================================
# 模型与 LoRA 设置
# ============================================================

# 保存原始 forward 方法（仅修补一次）
_original_whisper_forward = None


def patch_whisper_for_peft():
    """修补 WhisperForConditionalGeneration.forward 以兼容 PEFT。

    PEFT 的 PeftModelForSeq2SeqLM.forward() 使用 'input_ids' 作为参数名，
    但 Whisper 模型使用 'input_features'。此函数将 input_ids 从 **kwargs 中
    提取出来，作为 input_features 使用，避免参数冲突。
    """
    global _original_whisper_forward

    if _original_whisper_forward is not None:
        # 已经修补过，跳过
        return

    _original_whisper_forward = WhisperForConditionalGeneration.forward

    def patched_forward(
        self,
        input_features=None,
        attention_mask=None,
        decoder_input_ids=None,
        decoder_attention_mask=None,
        encoder_outputs=None,
        past_key_values=None,
        decoder_inputs_embeds=None,
        decoder_position_ids=None,
        labels=None,
        use_cache=None,
        **kwargs,
    ):
        # PEFT 通过 input_ids 传递 Whisper 的 input_features
        if input_features is None and "input_ids" in kwargs:
            input_features = kwargs.pop("input_ids")

        # 移除 PEFT 传递的但 Whisper 不需要的参数（避免 **kwargs 冲突）
        # inputs_embeds: PEFT 传递但 WhisperForConditionalGeneration 不接受
        # task_ids: PEFT 内部参数，Whisper 不需要
        for drop_key in ("inputs_embeds", "task_ids"):
            kwargs.pop(drop_key, None)

        return _original_whisper_forward(
            self,
            input_features=input_features,
            attention_mask=attention_mask,
            decoder_input_ids=decoder_input_ids,
            decoder_attention_mask=decoder_attention_mask,
            encoder_outputs=encoder_outputs,
            past_key_values=past_key_values,
            decoder_inputs_embeds=decoder_inputs_embeds,
            decoder_position_ids=decoder_position_ids,
            labels=labels,
            use_cache=use_cache,
            **kwargs,
        )

    WhisperForConditionalGeneration.forward = patched_forward
    print("✅ 已修补 Whisper forward 以兼容 PEFT (input_ids → input_features)")


def setup_model_and_processor(base_model, device, use_8bit=False,
                               language="Chinese"):
    """加载 Whisper 模型和处理器

    Args:
        base_model: 基础模型名称或路径（如 "openai/whisper-small"）
        device: 计算设备（"cuda" / "mps" / "cpu"）
        use_8bit: 是否使用 8-bit 量化 (QLoRA)
        language: 语言名称（用于设置 forced_decoder_ids）

    Returns:
        (model, processor) 元组
    """
    # 修补 Whisper forward 以兼容 PEFT
    patch_whisper_for_peft()

    print(f"🔄 加载基础模型 {base_model} ...")

    # 加载处理器（feature_extractor + tokenizer）
    processor = WhisperProcessor.from_pretrained(base_model)

    # 加载模型
    quantization_applied = False
    if use_8bit:
        if device != "cuda":
            print(
                f"⚠️ 8-bit 量化 (QLoRA) 仅支持 CUDA，当前设备为 "
                f"{device}，将使用全精度"
            )
        else:
            try:
                from transformers import BitsAndBytesConfig
                quantization_config = BitsAndBytesConfig(load_in_8bit=True)
                model = WhisperForConditionalGeneration.from_pretrained(
                    base_model,
                    quantization_config=quantization_config,
                    device_map="auto",
                )
                quantization_applied = True
                print("✅ 已启用 8-bit 量化 (QLoRA)")
            except ImportError:
                print(
                    "⚠️ 未安装 bitsandbytes，无法使用 8-bit 量化，"
                    "将使用全精度"
                )
                print("   安装: pip install bitsandbytes")

    if not quantization_applied:
        model = WhisperForConditionalGeneration.from_pretrained(base_model)
        model = model.to(device)

    # 设置 forced_decoder_ids — 指定语言和任务（转写）
    try:
        forced_decoder_ids = processor.get_decoder_prompt_ids(
            language=language, task="transcribe"
        )
        model.config.forced_decoder_ids = forced_decoder_ids
    except Exception as e:
        print(f"⚠️ 无法设置 forced_decoder_ids: {e}")

    # 训练时不抑制任何 token
    model.config.suppress_tokens = []

    # 训练时关闭 cache（避免与梯度计算冲突）
    model.config.use_cache = False

    print("✅ 模型加载完成")
    return model, processor


def apply_lora(model, lora_r, lora_alpha, lora_dropout):
    """应用 LoRA 配置

    Args:
        model: Whisper 模型
        lora_r: LoRA 秩
        lora_alpha: LoRA alpha
        lora_dropout: LoRA dropout

    Returns:
        应用 LoRA 后的 PEFT 模型
    """
    print(f"🔧 应用 LoRA 配置 (r={lora_r}, alpha={lora_alpha}) ...")

    # 目标模块 — Whisper 的注意力投影层和前馈网络层
    target_modules = ["q_proj", "v_proj", "k_proj", "out_proj", "fc1", "fc2"]

    lora_config = LoraConfig(
        r=lora_r,
        lora_alpha=lora_alpha,
        target_modules=target_modules,
        lora_dropout=lora_dropout,
        bias="none",
        task_type="SEQ_2_SEQ_LM",
    )

    model = get_peft_model(model, lora_config)
    print_trainable_parameters(model)
    return model


def print_trainable_parameters(model):
    """打印可训练参数统计（可训练参数数 vs 总参数数）"""
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    percentage = 100 * trainable / total if total > 0 else 0
    print(f"📊 可训练参数: {trainable:,} ({percentage:.2f}%)")


# ============================================================
# 进度回调 — 每步打印训练进度
# ============================================================

class ProgressPrintCallback:
    """自定义训练进度回调，确保每步都有可见的输出。"""

    def __init__(self):
        self.step_start_time = None
        self.epoch_start_time = None

    def on_train_begin(self, args, state, control, **kwargs):
        total_steps = state.max_steps
        print(f"\n🚀 训练开始：共 {total_steps} 步，{args.num_train_epochs} 轮")
        print(f"   {'轮次':>4} | {'步骤':>6} | {'损失':>10} | {'学习率':>12} | {'用时':>8}")
        print(f"   {'-'*4}-+-{'-'*6}-+-{'-'*10}-+-{'-'*12}-+-{'-'*8}")

    def on_epoch_begin(self, args, state, control, **kwargs):
        self.epoch_start_time = time.time()
        print(f"\n📋 第 {state.epoch + 1:.0f}/{args.num_train_epochs} 轮开始")

    def on_step_begin(self, args, state, control, **kwargs):
        self.step_start_time = time.time()

    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs is None:
            return
        loss = logs.get("loss", logs.get("eval_loss", "?"))
        lr = logs.get("learning_rate", "?")
        epoch = state.epoch
        step = state.global_step
        max_steps = state.max_steps
        pct = 100 * step / max_steps if max_steps > 0 else 0
        if self.step_start_time:
            elapsed = time.time() - self.step_start_time
        else:
            elapsed = 0
        loss_str = f"{loss:.4f}" if isinstance(loss, (int, float)) else str(loss)
        lr_str = f"{lr:.2e}" if isinstance(lr, (int, float)) else str(lr)
        print(f"   {epoch:>4.1f} | {step:>4}/{max_steps:<4} | {loss_str:>10} | {lr_str:>12} | {elapsed:>6.1f}s  [{pct:.0f}%]")

    def on_epoch_end(self, args, state, control, **kwargs):
        if self.epoch_start_time:
            elapsed = time.time() - self.epoch_start_time
            print(f"✅ 第 {state.epoch + 1:.0f} 轮完成，用时 {elapsed:.1f}s")

    def on_train_end(self, args, state, control, **kwargs):
        print(f"\n🎉 训练结束！共 {state.global_step} 步")
        if hasattr(state, 'best_metric') and state.best_metric is not None:
            print(f"   最佳指标: {state.best_metric}")


# ============================================================
# 训练
# ============================================================

def train(args):
    """主训练函数

    Args:
        args: argparse 参数对象
    """
    print("=" * 60)
    print("  Whisper LoRA 微调 — 莆仙话方言适配")
    print(f"  设备: {DEVICE}")
    print(f"  基础模型: {args.base_model}")
    print(
        f"  LoRA: r={args.lora_r}, alpha={args.lora_alpha}, "
        f"dropout={args.lora_dropout}"
    )
    print(f"  训练轮数: {args.num_epochs}")
    print(f"  批大小: {args.batch_size}")
    print(f"  学习率: {args.learning_rate}")
    print(f"  8-bit 量化: {'是' if args.use_8bit else '否'}")
    print("=" * 60)

    # 1. 加载模型和处理器
    model, processor = setup_model_and_processor(
        args.base_model, DEVICE, args.use_8bit, args.language
    )

    # 2. 应用 LoRA
    model = apply_lora(
        model, args.lora_r, args.lora_alpha, args.lora_dropout
    )

    # 3. 加载数据集
    print()
    train_dataset = WhisperLoRADataset(
        args.train_jsonl, processor, language=args.language
    )

    eval_dataset = None
    if args.val_jsonl:
        eval_dataset = WhisperLoRADataset(
            args.val_jsonl, processor, language=args.language
        )

    print()

    # 4. 数据整理器
    data_collator = DataCollatorSeq2SeqWithPadding(processor)

    # 5. 训练参数
    use_fp16 = (DEVICE == "cuda")

    # 构建 TrainingArguments — 兼容不同版本的 transformers
    common_kwargs = dict(
        output_dir=args.output_dir,
        num_train_epochs=args.num_epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        warmup_ratio=0.1,
        logging_steps=1,
        save_strategy="epoch",
        fp16=use_fp16,
        predict_with_generate=True,
        generation_max_length=225,
        report_to=[],
        save_total_limit=1,
        remove_unused_columns=False,
        dataloader_num_workers=0,
        disable_tqdm=True,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
    )

    eval_strat = "epoch" if eval_dataset else "no"

    # 尝试使用 eval_strategy（新版 transformers >= 4.46）
    # 或 evaluation_strategy（旧版）
    try:
        training_args = Seq2SeqTrainingArguments(
            eval_strategy=eval_strat,
            **common_kwargs,
        )
    except TypeError:
        training_args = Seq2SeqTrainingArguments(
            evaluation_strategy=eval_strat,
            **common_kwargs,
        )

    # 6. 创建 Trainer — 兼容不同版本的参数名
    common_trainer_kwargs = dict(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=data_collator,
    )

    try:
        trainer = Seq2SeqTrainer(
            processing_class=processor,
            **common_trainer_kwargs,
        )
    except TypeError:
        trainer = Seq2SeqTrainer(
            tokenizer=processor,
            **common_trainer_kwargs,
        )

    # 6.5 添加自定义进度回调
    from transformers import TrainerCallback
    progress_cb = TrainerCallback()
    # 将 ProgressPrintCallback 的方法绑定到 TrainerCallback 实例
    _progress = ProgressPrintCallback()
    for method_name in ["on_train_begin", "on_epoch_begin", "on_step_begin",
                        "on_log", "on_epoch_end", "on_train_end"]:
        setattr(progress_cb, method_name, getattr(_progress, method_name))
    trainer.add_callback(progress_cb)

    # 6.6 添加早停回调（patience=3，eval_loss 连续 3 轮不降则停）
    if eval_dataset:
        trainer.add_callback(EarlyStoppingCallback(early_stopping_patience=3))
        print(f"📋 早停已启用 (patience=3, metric=eval_loss)")

    # 7. 开始训练
    print(f"🚀 开始训练 ({args.num_epochs} 轮) ...")
    print(f"   设备: {DEVICE}")
    print(f"   训练样本: {len(train_dataset)} 条")
    if eval_dataset:
        print(f"   验证样本: {len(eval_dataset)} 条")
    print()

    train_result = trainer.train()

    # 8. 打印训练结果
    print()
    print("📈 训练指标:")
    for key, value in train_result.metrics.items():
        print(f"   {key}: {value}")

    # 9. 保存模型
    print()
    print(f"💾 保存 LoRA 适配器到 {args.output_dir} ...")

    # 创建输出目录
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 保存 LoRA 适配器
    model.save_pretrained(str(output_dir))

    # 保存处理器（tokenizer + feature_extractor）
    processor.save_pretrained(str(output_dir))

    # 保存训练状态
    trainer.save_state()

    print()
    print(f"✅ 训练完成！LoRA 适配器已保存到: {args.output_dir}")
    print()
    print("使用方法:")
    print("   from peft import PeftModel")
    print("   from transformers import WhisperForConditionalGeneration")
    print(
        f"   base = WhisperForConditionalGeneration.from_pretrained("
        f"'{args.base_model}')"
    )
    print(
        f"   model = PeftModel.from_pretrained(base, '{args.output_dir}')"
    )


# ============================================================
# 入口
# ============================================================

def main():
    """入口"""
    parser = argparse.ArgumentParser(
        description="Whisper LoRA 微调 — 莆仙话方言适配",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--base_model", default="openai/whisper-small", help="基础模型"
    )
    parser.add_argument(
        "--train_jsonl", required=True, help="训练数据 JSONL 路径"
    )
    parser.add_argument(
        "--val_jsonl", default=None, help="验证数据 JSONL 路径"
    )
    parser.add_argument(
        "--output_dir", default="./output", help="输出目录"
    )
    parser.add_argument(
        "--lora_r", type=int, default=16, help="LoRA 秩"
    )
    parser.add_argument(
        "--lora_alpha", type=int, default=32, help="LoRA alpha"
    )
    parser.add_argument(
        "--lora_dropout", type=float, default=0.05, help="LoRA dropout"
    )
    parser.add_argument(
        "--learning_rate", type=float, default=1e-4, help="学习率"
    )
    parser.add_argument(
        "--num_epochs", type=int, default=3, help="训练轮数"
    )
    parser.add_argument(
        "--batch_size", type=int, default=8, help="批大小"
    )
    parser.add_argument(
        "--language", default="Chinese", help="语言"
    )
    parser.add_argument(
        "--use_8bit", action="store_true", help="使用 8-bit 量化 (QLoRA)"
    )

    args = parser.parse_args()

    # 打印设备信息
    print(f"🖥️ 计算设备: {DEVICE}")
    if DEVICE == "cpu":
        print("⚠️ 当前使用 CPU 训练，速度会非常慢")
        print("   建议使用 CUDA (NVIDIA GPU) 或 MPS (Apple Silicon)")

    # 执行训练
    train(args)


if __name__ == "__main__":
    main()
