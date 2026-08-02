import 'dart:html' as html;
import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../services/audio_service.dart';
import '../services/user_service.dart';

class ReadTab extends StatefulWidget {
  const ReadTab({super.key});

  @override
  State<ReadTab> createState() => _ReadTabState();
}

class _ReadTabState extends State<ReadTab> {
  final _userService = UserService();
  NextWord? _currentWord;
  bool _loading = true;
  bool _recording = false;
  bool _processing = false;
  bool _reverseMode = false; // false=中文→莆仙, true=莆仙→中文
  String? _selectedCategory;
  List<String> _wrongWords = [];
  RecognizeResult? _result;
  String _statusText = '准备中...';

  static const categories = {
    '': '全部',
    'pronoun': '人称代词', 'adj': '形容词', 'emotion': '情感',
    'verb': '动词', 'time': '时间', 'num': '数字',
    'question': '疑问词', 'daily': '日常用语', 'place': '地点',
    'food': '饮食', 'object': '物品', 'sentence': '常用句子',
  };

  String get _userId => _userService.userId ?? '';

  @override
  void initState() {
    super.initState();
    _loadNextWord();
  }

  Future<void> _loadNextWord() async {
    setState(() {
      _loading = true;
      _result = null;
      _statusText = '';
    });
    try {
      final word = await ApiService.getNextWord(userId: _userId);
      if (mounted) {
        setState(() {
          _currentWord = word;
          _loading = false;
          _statusText = word.done ? '' : '点击录音，说出对应的方言';
        });
      }
    } catch (e) {
      if (mounted) setState(() {
        _loading = false;
        _statusText = '加载失败: $e';
      });
    }
  }

  /// 用浏览器 TTS 播放发音
  void _playPronunciation() {
    if (_currentWord == null || _currentWord!.done) return;
    final text = _reverseMode
        ? _result?.dialect ?? _currentWord!.word
        : _currentWord!.word;
    try {
      if (html.window.speechSynthesis != null) {
        html.window.speechSynthesis!.cancel();
        final utterance = html.SpeechSynthesisUtterance(text);
        utterance.lang = 'cmn-CN';
        utterance.rate = 0.85;
        html.window.speechSynthesis!.speak(utterance);
      }
    } catch (_) {
      // 浏览器不支持就静默
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
    try {
      setState(() {
        _recording = true;
        _statusText = '录音中...';
      });
      // startRecording 不限时，等待用户手动停止
      AudioService.startRecording(maxDurationSec: 30);
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
      _statusText = '识别中...';
    });
    try {
      final path = await AudioService.stopRecording();
      final audioBytes = AudioService.getRecordingData();
      if (path != null && audioBytes != null && _currentWord != null) {
        final result = await ApiService.recognizeBytes(
          audioBytes, _currentWord!.word,
          userId: _userId,
        );
        if (mounted) {
          setState(() {
            _result = result;
            _processing = false;
            _statusText = '识别完成';
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

  Future<void> _confirm() async {
    if (_result == null || _currentWord == null) return;
    final ok = await ApiService.confirm(
      _result!.dialect, _currentWord!.word,
      userId: _userId,
    );
    if (ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('✓ 已保存到个人词库'), duration: Duration(seconds: 1)),
      );
      _loadNextWord();
    }
  }

  Future<void> _skip() {
    // 收集到错词本
    if (_currentWord != null && !_currentWord!.done) {
      _wrongWords.add(_currentWord!.word);
    }
    return _loadNextWord();
  }

  void _showCorrectDialog() {
    final controller = TextEditingController(text: _result?.meaning ?? '');
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('修正中文含义'),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(
            labelText: '正确的中文含义',
            border: OutlineInputBorder(),
          ),
          autofocus: true,
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
          FilledButton(onPressed: () async {
            if (_result != null && controller.text.trim().isNotEmpty) {
              await ApiService.correct(
                _result!.dialect, controller.text.trim(),
                userId: _userId,
              );
              if (mounted) Navigator.pop(ctx);
              _loadNextWord();
            }
          }, child: const Text('提交')),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        children: [
          // === 顶部控制栏 ===
          Card(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(
                children: [
                  // 分类下拉
                  Expanded(
                    child: DropdownButton<String>(
                      value: _selectedCategory,
                      isExpanded: true,
                      hint: const Text('选择分类'),
                      underline: const SizedBox(),
                      items: categories.entries.map((e) =>
                        DropdownMenuItem(value: e.key, child: Text(e.value))
                      ).toList(),
                      onChanged: (v) => setState(() => _selectedCategory = v),
                    ),
                  ),
                  const SizedBox(width: 8),
                  // 模式切换
                  InkWell(
                    onTap: () {
                      setState(() => _reverseMode = !_reverseMode);
                      _loadNextWord();
                    },
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: _reverseMode ? Colors.orange.shade50 : Colors.blue.shade50,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            _reverseMode ? Icons.swap_horiz : Icons.menu_book,
                            size: 16,
                            color: _reverseMode ? Colors.orange : Colors.blue,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            _reverseMode ? '方言→中文' : '中文→方言',
                            style: TextStyle(fontSize: 12, color: _reverseMode ? Colors.orange : Colors.blue),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),

          // === 单词卡片 ===
          Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                children: [
                  // 播放按钮 + 发音引导
                  if (_currentWord != null && !_currentWord!.done)
                    Align(
                      alignment: Alignment.topRight,
                      child: IconButton(
                        icon: const Icon(Icons.volume_up, size: 20),
                        onPressed: _playPronunciation,
                        tooltip: '播放标准发音',
                      ),
                    ),
                  Text(
                    _loading ? '---'
                        : _reverseMode
                            ? (_result?.dialect ?? _currentWord?.word ?? '无')
                            : _currentWord?.word ?? '全部完成',
                    style: theme.textTheme.displaySmall?.copyWith(fontWeight: FontWeight.bold),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 8),
                  if (!_reverseMode && _currentWord != null && !_currentWord!.done)
                    Text(
                      '说对应的莆仙话',
                      style: theme.textTheme.bodySmall?.copyWith(color: Colors.grey),
                    ),
                  if (_reverseMode && _currentWord != null && !_currentWord!.done)
                    Text(
                      '说这句话对应的中文意思',
                      style: theme.textTheme.bodySmall?.copyWith(color: Colors.grey),
                    ),
                  const SizedBox(height: 4),
                  if (_currentWord != null && !_currentWord!.done)
                    Text(
                      '${categories[_currentWord!.category] ?? _currentWord!.category} · 第 ${_currentWord!.index + 1}/${_currentWord!.total} 个',
                      style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                  if (_currentWord?.done == true)
                    Text(
                      _currentWord?.message ?? '全部完成！',
                      style: theme.textTheme.bodyLarge?.copyWith(color: Colors.green),
                    ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 20),

          // === 录音按钮 ===
          if (_currentWord?.done != true) ...[
            SizedBox(
              width: 80,
              height: 80,
              child: FloatingActionButton.large(
                onPressed: _loading || _processing ? null : _toggleRecording,
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
              style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            if (_recording) ...[
              const SizedBox(height: 8),
              Text(
                '最多 8 秒，再次点击停止',
                style: theme.textTheme.labelSmall?.copyWith(color: Colors.orange),
              ),
            ],
          ],

          const SizedBox(height: 20),

          // === 识别结果 ===
          if (_result != null) ...[
            Card(
              color: _result!.dialect != '(未识别)'
                  ? Colors.green.shade50
                  : Colors.orange.shade50,
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  children: [
                    // 结果文字 + 播放按钮
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Text('识别的方言', style: TextStyle(fontSize: 12, color: Colors.grey)),
                        const Spacer(),
                        IconButton(
                          icon: const Icon(Icons.volume_up, size: 18),
                          onPressed: _result!.dialect != '(未识别)'
                              ? () {
                                if (html.window.speechSynthesis != null) {
                                    html.window.speechSynthesis!.cancel();
                                    final u = html.SpeechSynthesisUtterance(_result!.dialect);
                                    u.lang = 'cmn-CN';
                                    u.rate = 0.9;
                                    html.window.speechSynthesis!.speak(u);
                                }
                                }
                              : null,
                        ),
                      ],
                    ),
                    Text(
                      _result!.dialect,
                      style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 12),
                    const Text('中文含义', style: TextStyle(fontSize: 12, color: Colors.grey)),
                    const SizedBox(height: 4),
                    Text(
                      _result!.meaning,
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
                          '已保存到 ${_userService.userName} 的个人词库',
                          style: TextStyle(fontSize: 12, color: Colors.blue.shade700),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),

            // === 操作按钮 ===
            Wrap(
              spacing: 8,
              runSpacing: 8,
              alignment: WrapAlignment.center,
              children: [
                FilledButton.icon(
                  onPressed: _confirm,
                  icon: const Icon(Icons.check, size: 18),
                  label: const Text('正确'),
                  style: FilledButton.styleFrom(backgroundColor: Colors.green),
                ),
                OutlinedButton.icon(
                  onPressed: _showCorrectDialog,
                  icon: const Icon(Icons.edit, size: 18),
                  label: const Text('修正'),
                ),
                OutlinedButton.icon(
                  onPressed: () => _showProofreadDialog(),
                  icon: const Icon(Icons.report, size: 18),
                  label: const Text('纠错'),
                  style: OutlinedButton.styleFrom(foregroundColor: Colors.orange),
                ),
                TextButton.icon(
                  onPressed: _skip,
                  icon: const Icon(Icons.skip_next, size: 18),
                  label: const Text('跳过'),
                ),
              ],
            ),
          ],

          // === 错词本 ===
          if (_wrongWords.isNotEmpty) ...[
            const SizedBox(height: 24),
            Card(
              color: Colors.red.shade50,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.error_outline, size: 16, color: Colors.red),
                        const SizedBox(width: 4),
                        Text('待复习 (${_wrongWords.length})',
                            style: TextStyle(fontWeight: FontWeight.bold, color: Colors.red.shade700)),
                        const Spacer(),
                        TextButton(
                          onPressed: () {
                            // 跳转到复习
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text('共 ${_wrongWords.length} 个词待复习')),
                            );
                          },
                          child: const Text('复习'),
                        ),
                      ],
                    ),
                    Wrap(
                      spacing: 4,
                      runSpacing: 2,
                      children: _wrongWords.take(10).map((w) =>
                        Chip(label: Text(w, style: const TextStyle(fontSize: 12)), materialTapTargetSize: MaterialTapTargetSize.shrinkWrap)
                      ).toList(),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  // 纠错对话框
  void _showProofreadDialog() {
    final controller = TextEditingController(text: '');
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('提交纠错'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('方言: ${_result?.dialect ?? "未知"}'),
            const SizedBox(height: 4),
            Text('当前含义: ${_result?.meaning ?? "未知"}'),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              decoration: const InputDecoration(
                labelText: '正确的含义',
                border: OutlineInputBorder(),
              ),
              autofocus: true,
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
          FilledButton(onPressed: () async {
            if (controller.text.trim().isNotEmpty && _result != null) {
              await ApiService.correct(
                _result!.dialect, controller.text.trim(),
                userId: _userId,
              );
              if (mounted) {
                Navigator.pop(ctx);
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('✓ 纠错已提交'), duration: Duration(seconds: 2)),
                );
              }
            }
          }, child: const Text('提交纠错')),
        ],
      ),
    );
  }
}
