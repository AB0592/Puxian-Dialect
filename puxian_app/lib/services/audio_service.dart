import 'dart:async';
import 'dart:js_util' as js_util;
import 'dart:typed_data';

/// 录音服务 — 调用 window.PuxianRecorder（纯 JS），完全绕过 dart:html.MediaRecorder
class AudioService {
  static bool _isRecording = false;
  static Uint8List? _lastRecordingData;
  static Timer? _autoStopTimer;

  static bool get isRecording => _isRecording;

  static Future<bool> hasMicrophone() async => true;
  /// 开始录音，maxDurationSec 后自动停止
  static Future<String> startRecording({int maxDurationSec = 10}) async {
    if (_isRecording) throw Exception('已经在录音中');

    _lastRecordingData = null;
    _isRecording = true;

    final puxian = js_util.getProperty(js_util.globalThis, 'PuxianRecorder');
    if (puxian == null) {
      _isRecording = false;
      throw Exception('PuxianRecorder 未加载');
    }

    try {
      // 调用 JS: PuxianRecorder.start(maxDurationSec)
      final promise = js_util.callMethod(puxian, 'start', [maxDurationSec]);
      await js_util.promiseToFuture(promise);
    } catch (e) {
      _isRecording = false;
      rethrow;
    }

    return 'recording';
  }

  /// 停止录音并等待 JS 侧处理完成
  static Future<String?> stopRecording() async {
    _isRecording = false;
    _autoStopTimer?.cancel();

    final puxian = js_util.getProperty(js_util.globalThis, 'PuxianRecorder');
    if (puxian == null) return null;

    // 如果不在录音中，直接拿数据
    final isRecording = js_util.callMethod(puxian, 'isRecording', []);
    if (isRecording != true) {
      final bytes = _fetchBytes();
      return bytes != null ? 'done' : null;
    }

    try {
      // 调用 JS: PuxianRecorder.stop() — 等待 onstop + FileReader 完成后才 resolve
      final status = await js_util.promiseToFuture(
        js_util.callMethod(puxian, 'stop', []),
      );
      if (status == 'error') return null;
      if (status == 'empty') return null;
    } catch (_) {
      return null;
    }

    final bytes = _fetchBytes();
    return bytes != null ? 'done' : null;
  }

  /// 从 window.__puxian_audio_bytes 获取录音数据
  static Uint8List? _fetchBytes() {
    final puxian = js_util.getProperty(js_util.globalThis, 'PuxianRecorder');
    if (puxian == null) return null;

    try {
      final result = js_util.callMethod(puxian, 'getBytes', []);
      if (result is List) {
        final list = result as List;
        if (list.isEmpty) return null;
        _lastRecordingData = Uint8List.fromList(list.cast<int>());
        return _lastRecordingData;
      }
    } catch (_) {
      // getBytes 可能返回空
    }
    return null;
  }

  static Uint8List? getRecordingData() {
    if (_lastRecordingData == null) return null;
    return Uint8List.fromList(_lastRecordingData!);
  }

  static Future<double> getFileSize(String path) async {
    if (_lastRecordingData == null) return 0;
    return _lastRecordingData!.length / 1024;
  }

  static Future<void> deleteFile(String path) async {
    _lastRecordingData = null;
  }

  static void dispose() {
    _autoStopTimer?.cancel();
    _isRecording = false;
    _lastRecordingData = null;
  }
}
