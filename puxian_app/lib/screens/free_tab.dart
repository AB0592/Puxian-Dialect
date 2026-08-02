import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../services/api_service.dart';
import '../services/audio_service.dart';
import '../services/tts_service.dart';
import '../services/user_service.dart';

class FreeTab extends StatefulWidget {
  const FreeTab({super.key});

  @override
  State<FreeTab> createState() => _FreeTabState();
}

class _FreeTabState extends State<FreeTab> {
  final _userService = UserService();
  bool _recording = false;
  bool _processing = false;
  bool _playingTts = false;
  String _statusText = '点击录音，讲莆仙话';
  FreeSpeechResult? _result;
  final _textController = TextEditingController();

  String get _userId => _userService.userId ?? '';

  @override
  void dispose() {
    _textController.dispose();
    super.dispose();
  }

  Future<void> _toggleRecording() async {
    if (_recording) {
      await _stopRecording();
    } else {
      await _startRecording();
    }
  }

  Future<void> _startRecording() async {
    try {
      setState(() {
        _recording = true;
        _statusText = '录音中...';
      });
      await AudioService.startRecording(maxDurationSec: 10);
    } catch (e) {
      setState(() {
        _recording = false;
        _statusText = '录音失败: $e';
      });
    }
  }

  Future<void> _stopRecording() async {
    setState(() {
      _recording = false;
      _processing = true;
      _statusText = '识别中...';
    });
    try {
      final path = await AudioService.stopRecording();
      final audioBytes = AudioService.getRecordingData();
      if (path != null && audioBytes != null) {
        final result = await ApiService.freeSpeechBytes(audioBytes, userId: _userId);
        if (mounted) {
          setState(() {
            _result = result;
            _processing = false;
            _statusText = '';
          });
        }
      }
    } catch (e) {
      if (mounted) setState(() {
        _processing = false;
        _statusText = '识别失败: $e';
      });
    }
  }

  Future<void> _submitText() async {
    final text = _textController.text.trim();
    if (text.isEmpty) return;
    setState(() => _processing = true);
    try {
      final result = await ApiService.translateText(text, userId: _userId);
      if (mounted) {
        setState(() {
          _result = FreeSpeechResult(
            dialect: result.dialect,
            translation: result.meaning,
          );
          _processing = false;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _processing = false);
    }
  }

  void _reset() {
    setState(() {
      _result = null;
      _statusText = '点击录音，讲莆仙话';
      _textController.clear();
    });
  }

  /// 复制中文翻译到系统剪贴板
  void _copyToClipboard() {
    if (_result == null) return;
    Clipboard.setData(ClipboardData(text: _result!.translation));
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: const Text('已复制到剪贴板，可粘贴到微信/短信'),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        duration: const Duration(seconds: 2),
      ),
    );
  }

  /// TTS 播放中文翻译为方言语音
  Future<void> _playTts() async {
    if (_result == null || _playingTts) return;
    setState(() => _playingTts = true);
    try {
      final audioBytes = await TtsService.synthesize(
        _result!.translation,
        lang: 'putian',
      );
      if (audioBytes != null && mounted) {
        // TODO: 播放音频 — 需要音频播放器
        // 当前方案：显示数据 URI 供 Web 端使用
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('方言语音已合成 (${(audioBytes.length / 1024).toStringAsFixed(1)} KB)'),
            behavior: SnackBarBehavior.floating,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('语音合成失败: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _playingTts = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        children: [
          const SizedBox(height: 8),
          Text(
            '用莆仙话随意说一句话，系统识别并翻译成中文',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 20),

          // Record button
          SizedBox(
            width: 80,
            height: 80,
            child: FloatingActionButton.large(
              onPressed: _processing ? null : _toggleRecording,
              backgroundColor: _recording
                  ? Colors.red
                  : (_processing ? Colors.grey : theme.colorScheme.primary),
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

          const SizedBox(height: 20),

          // Result card
          if (_result != null) ...[
            Card(
              color: Colors.green.shade50,
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  children: [
                    const Text('识别的方言', style: TextStyle(fontSize: 12, color: Colors.grey)),
                    const SizedBox(height: 4),
                    Text(
                      _result!.dialect,
                      style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 12),
                    const Text('中文翻译', style: TextStyle(fontSize: 12, color: Colors.grey)),
                    const SizedBox(height: 4),
                    Text(
                      _result!.translation,
                      style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold),
                    ),
                    if (_userService.isLoggedIn) ...[
                      const SizedBox(height: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                        decoration: BoxDecoration(
                          color: Colors.blue.shade50,
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Text(
                          '${_userService.userName} 的个人词库匹配',
                          style: TextStyle(fontSize: 12, color: Colors.blue.shade700),
                        ),
                      ),
                    ],

                    // --- Phase 1+2: 操作按钮 ---
                    const SizedBox(height: 16),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        // 复制到剪贴板
                        FilledButton.tonalIcon(
                          onPressed: _copyToClipboard,
                          icon: const Icon(Icons.copy, size: 18),
                          label: const Text('复制中文'),
                        ),
                        const SizedBox(width: 12),

                        // TTS 方言播放
                        FilledButton.tonalIcon(
                          onPressed: _playingTts ? null : _playTts,
                          icon: _playingTts
                              ? const SizedBox(
                                  width: 16, height: 16,
                                  child: CircularProgressIndicator(strokeWidth: 2),
                                )
                              : const Icon(Icons.volume_up, size: 18),
                          label: const Text('方言播放'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
            TextButton.icon(
              onPressed: _reset,
              icon: const Icon(Icons.refresh),
              label: const Text('再来一次'),
            ),
          ],

          const SizedBox(height: 24),

          // Text input
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: theme.colorScheme.surface,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: theme.colorScheme.outlineVariant),
            ),
            child: Column(
              children: [
                Text(
                  '或直接输入中文，翻译为方言',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: _textController,
                  decoration: const InputDecoration(
                    hintText: '输入中文句子...',
                    border: OutlineInputBorder(),
                    contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  ),
                  onSubmitted: (_) => _submitText(),
                ),
                const SizedBox(height: 8),
                FilledButton.tonalIcon(
                  onPressed: _processing ? null : _submitText,
                  icon: const Icon(Icons.translate),
                  label: const Text('翻译为方言'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
