import 'dart:io';
import 'dart:async';
import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../services/user_service.dart';
import '../services/audio_service.dart';
import '../models/user.dart';
import 'home_screen.dart';

class RegisterScreen extends StatefulWidget {
  final UserProfile userProfile;
  final bool fromHome; // true=从主页进入（非强制），false=首次注册

  const RegisterScreen({
    super.key,
    required this.userProfile,
    this.fromHome = false,
  });

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _userService = UserService();
  RegisterStatus? _status;
  bool _loading = true;
  bool _recording = false;
  bool _processing = false;
  String? _audioPath;
  String _statusText = '准备中...';

  @override
  void initState() {
    super.initState();
    _loadStatus();
  }

  Future<void> _loadStatus() async {
    setState(() => _loading = true);
    try {
      final status = await ApiService.getRegisterStatus(
          _userService.userId!);
      _userService.updateRegisterStatus(status);
      if (mounted) setState(() {
        _status = status;
        _loading = false;
        _statusText = status.complete
            ? '注册完成！'
            : '朗读第 ${status.currentSentenceIndex + 1} 句';
      });
    } catch (e) {
      if (mounted) setState(() {
        _loading = false;
        _statusText = '加载失败: $e';
      });
    }
  }

  Future<void> _toggleRecording() async {
    if (_recording) {
      await _stopRecording();
    } else {
      await _startRecording();
    }
  }

  Future<void> _startRecording() async {
    if (_status == null || _status!.complete) return;

    try {
      // 先检测麦克风
      if (!await AudioService.hasMicrophone()) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('未检测到麦克风，请用手机打开 Web 版'),
              backgroundColor: Colors.red,
            ),
          );
        }
        return;
      }

      setState(() {
        _recording = true;
        _statusText = '朗读中...';
      });

      final path = await AudioService.startRecording(maxDurationSec: 6);
      _audioPath = path;

      // 自动停止 6 秒后
      await Future.delayed(const Duration(seconds: 6));
      if (_recording) {
        await _stopRecording();
      }
    } catch (e) {
      setState(() {
        _recording = false;
        _statusText = '录音失败: $e';
      });
    }
  }

  Future<void> _stopRecording() async {
    if (!_recording) return;
    setState(() {
      _recording = false;
      _processing = true;
      _statusText = '上传中...';
    });

    try {
      final path = await AudioService.stopRecording();
      final audioBytes = AudioService.getRecordingData();
      if (path != null && audioBytes != null && _status != null) {
        final idx = _status!.currentSentenceIndex;
        final ok = await ApiService.submitRegisterSampleBytes(
          _userService.userId!,
          audioBytes,
          idx,
        );
        if (ok && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('✓ 已记录'),
              duration: Duration(seconds: 1),
            ),
          );
          await _loadStatus();
        }
      }
    } catch (e) {
      if (mounted) setState(() => _statusText = '上传失败: $e');
    } finally {
      if (mounted) setState(() => _processing = false);
    }
  }

  void _finishRegistration() {
    if (widget.fromHome) {
      Navigator.pop(context);
    } else {
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (_) => const HomeScreen()),
      );
    }
  }

  RegisterSentence? get _currentSentence {
    if (_status == null || _status!.complete) return null;
    final idx = _status!.currentSentenceIndex;
    if (idx < _status!.sentences.length) return _status!.sentences[idx];
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final sentence = _currentSentence;
    final done = _status?.done ?? 0;
    final total = _status?.total ?? 10;
    final complete = _status?.complete ?? false;

    return Scaffold(
      appBar: AppBar(
        title: Text(
          complete ? '注册完成' : '声纹注册 (${done + 1}/$total)',
        ),
        centerTitle: true,
        actions: [
          if (!complete)
            TextButton(
              onPressed: () {
                if (widget.fromHome) {
                  Navigator.pop(context);
                } else {
                  Navigator.pushReplacement(
                    context,
                    MaterialPageRoute(builder: (_) => const HomeScreen()),
                  );
                }
              },
              child: const Text(
                '跳过',
                style: TextStyle(
                  color: Colors.white70,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                children: [
                  // Progress
                  LinearProgressIndicator(
                    value: complete ? 1.0 : done / total,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    complete
                        ? '全部完成！'
                        : '进度: $done / $total',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),

                  const SizedBox(height: 32),

                  // Instruction
                  if (!complete) ...[
                    Icon(
                      Icons.hearing,
                      size: 32,
                      color: theme.colorScheme.primary,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      '用莆仙话朗读下面的句子',
                      style: theme.textTheme.titleMedium,
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      '这是为了学习你的口音特色\n以后你说方言时系统就能准确识别你',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                      textAlign: TextAlign.center,
                    ),

                    const SizedBox(height: 32),

                    // Sentence card
                    if (sentence != null) ...[
                      Card(
                        elevation: 4,
                        child: Padding(
                          padding: const EdgeInsets.symmetric(
                              vertical: 40, horizontal: 24),
                          child: Column(
                            children: [
                              Text(
                                sentence.text,
                                style: theme.textTheme.displaySmall?.copyWith(
                                  fontWeight: FontWeight.bold,
                                  color: theme.colorScheme.primary,
                                ),
                                textAlign: TextAlign.center,
                              ),
                              const SizedBox(height: 12),
                              Container(
                                padding: const EdgeInsets.symmetric(
                                    horizontal: 16, vertical: 8),
                                decoration: BoxDecoration(
                                  color: theme
                                      .colorScheme.surfaceContainerHighest,
                                  borderRadius: BorderRadius.circular(20),
                                ),
                                child: Text(
                                  '含义: ${sentence.meaning}',
                                  style: theme.textTheme.bodyMedium?.copyWith(
                                    color: theme.colorScheme.onSurfaceVariant,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),

                      const SizedBox(height: 32),

                      // Record button
                      SizedBox(
                        width: 80,
                        height: 80,
                        child: FloatingActionButton.large(
                          onPressed: _processing ? null : _toggleRecording,
                          backgroundColor: _recording
                              ? Colors.red
                              : (_processing
                                  ? Colors.grey
                                  : theme.colorScheme.primary),
                          child: Icon(
                            _recording ? Icons.stop : Icons.mic,
                            color: Colors.white,
                            size: 36,
                          ),
                        ),
                      ),
                      const SizedBox(height: 12),
                      Text(
                        _statusText,
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                      if (_recording) ...[
                        const SizedBox(height: 8),
                        Text(
                          '录音中... 再次点击停止',
                          style: theme.textTheme.labelSmall?.copyWith(
                            color: Colors.orange,
                          ),
                        ),
                      ],

                      const SizedBox(height: 24),

                      // Hint
                      Container(
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: Colors.blue.shade50,
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Row(
                          children: [
                            Icon(Icons.info_outline,
                                color: Colors.blue.shade700, size: 20),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                '用你平时说话的口音朗读即可，\n不用刻意标准！',
                                style: TextStyle(
                                  color: Colors.blue.shade700,
                                  fontSize: 13,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ],

                  // Complete state
                  if (complete) ...[
                    Icon(
                      Icons.check_circle,
                      size: 80,
                      color: Colors.green,
                    ),
                    const SizedBox(height: 16),
                    Text(
                      '声纹注册完成！',
                      style: theme.textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: Colors.green,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      '系统已学习你的口音特征\n开始训练，系统会越来越懂你',
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 32),
                    FilledButton.icon(
                      onPressed: _finishRegistration,
                      icon: const Icon(Icons.arrow_forward),
                      label: const Text('开始训练'),
                      style: FilledButton.styleFrom(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 32, vertical: 16),
                      ),
                    ),
                  ],
                ],
              ),
            ),
    );
  }
}
