import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'api_service.dart';

/// TTS 语音合成服务
/// 调用后端 Edge TTS / CosyVoice 将中文合成为方言语音
class TtsService {
  static String get _baseUrl {
    if (kIsWeb) return '';
    return 'http://127.0.0.1:8520';
  }

  /// 合成方言语音，返回音频字节
  /// [text] 要合成的中文文本
  /// [lang] 方言代码 (putian/canton/minnan/sichuan/shanghai/hakka)
  static Future<Uint8List?> synthesize(String text, {String lang = 'putian'}) async {
    try {
      final uri = Uri.parse('$_baseUrl/api/tts');
      final response = await http.post(
        uri,
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'text': text,
          'lang': lang,
        }),
      ).timeout(const Duration(seconds: 15));

      if (response.statusCode == 200) {
        return response.bodyBytes;
      }
      return null;
    } catch (e) {
      debugPrint('TTS error: $e');
      return null;
    }
  }

  /// 合成并返回 base64 data URI（供 Web 端 <audio> 使用）
  static Future<String?> synthesizeAsDataUri(String text, {String lang = 'putian'}) async {
    final bytes = await synthesize(text, lang: lang);
    if (bytes == null) return null;
    final b64 = base64.encode(bytes);
    return 'data:audio/mpeg;base64,$b64';
  }
}
