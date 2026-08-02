import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../models/user.dart';

class ApiService {
  // 自动检测服务器地址
  static String get _baseUrl {
    if (kIsWeb) {
      return '';
    }
    return 'http://127.0.0.1:8520';
  }

  /// 存储当前登录 token
  static String? _authToken;
  static String? get authToken => _authToken;
  static void setAuthToken(String? token) => _authToken = token;

  /// 请求头（含认证）
  static Map<String, String> get _headers {
    final h = <String, String>{'Content-Type': 'application/json'};
    if (_authToken != null) {
      h['Authorization'] = 'Bearer $_authToken';
    }
    return h;
  }

  // ============================================================
  // 认证 API
  // ============================================================

  static Future<AuthResult> register(String name, String password) async {
    final res = await http.post(
      Uri.parse('$_baseUrl/api/auth/register'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({'name': name, 'password': password}),
    ).timeout(const Duration(seconds: 10));
    final data = json.decode(res.body);
    if (res.statusCode != 200) {
      throw Exception(data['detail'] ?? '注册失败');
    }
    _authToken = data['token'];
    return AuthResult(
      user: UserProfile.fromJson(data['user']),
      token: data['token'],
    );
  }

  static Future<AuthResult> login(String name, String password) async {
    final res = await http.post(
      Uri.parse('$_baseUrl/api/auth/login'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({'name': name, 'password': password}),
    ).timeout(const Duration(seconds: 10));
    final data = json.decode(res.body);
    if (res.statusCode != 200) {
      throw Exception(data['detail'] ?? '登录失败');
    }
    _authToken = data['token'];
    return AuthResult(
      user: UserProfile.fromJson(data['user']),
      token: data['token'],
    );
  }

  // ============================================================
  // 用户管理
  // ============================================================

  static Future<List<UserSummary>> getUsers() async {
    final res = await http.get(Uri.parse('$_baseUrl/api/users'))
        .timeout(const Duration(seconds: 10));
    final data = json.decode(res.body);
    return (data['users'] as List<dynamic>)
        .map((e) => UserSummary.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  static Future<UserProfile> createUser(String name) async {
    final res = await http.post(
      Uri.parse('$_baseUrl/api/user/create'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({'name': name}),
    ).timeout(const Duration(seconds: 10));
    final data = json.decode(res.body);
    return UserProfile.fromJson(data['user']);
  }

  static Future<UserProfile> getUserProfile(String userId) async {
    final res = await http.get(Uri.parse('$_baseUrl/api/user/$userId'))
        .timeout(const Duration(seconds: 10));
    return UserProfile.fromJson(json.decode(res.body));
  }

  static Future<UserProgress> getUserProgress(String userId) async {
    final res = await http
        .get(Uri.parse('$_baseUrl/api/user/$userId/progress'))
        .timeout(const Duration(seconds: 10));
    return UserProgress.fromJson(json.decode(res.body));
  }

  static Future<RegisterStatus> getRegisterStatus(String userId) async {
    final res = await http
        .get(Uri.parse('$_baseUrl/api/user/$userId/register-status'))
        .timeout(const Duration(seconds: 10));
    return RegisterStatus.fromJson(json.decode(res.body));
  }

  /// Web / 原生 通用：用二进制数据上传注册样本
  static Future<bool> submitRegisterSampleBytes(
      String userId, Uint8List audioBytes, int index) async {
    final uri = Uri.parse('$_baseUrl/api/user/$userId/register-sample');
    final request = http.MultipartRequest('POST', uri);
    request.fields['index'] = index.toString();
    request.files.add(http.MultipartFile.fromBytes('audio', audioBytes, filename: 'recording.webm'));
    final streamed = await request.send().timeout(const Duration(seconds: 30));
    return streamed.statusCode == 200;
  }

  // ============================================================
  // 训练 API
  // ============================================================

  static Future<NextWord> getNextWord({String? userId}) async {
    final params = <String, String>{};
    if (userId != null && userId.isNotEmpty) params['user_id'] = userId;
    final uri = Uri.parse('$_baseUrl/api/next-word').replace(queryParameters: params);
    final res = await http.get(uri).timeout(const Duration(seconds: 15));
    return NextWord.fromJson(json.decode(res.body));
  }

  static Future<UserProgress> getProgress({String? userId}) async {
    final params = <String, String>{};
    if (userId != null && userId.isNotEmpty) params['user_id'] = userId;
    final uri = Uri.parse('$_baseUrl/api/progress').replace(queryParameters: params);
    final res = await http.get(uri).timeout(const Duration(seconds: 10));
    return UserProgress.fromJson(json.decode(res.body));
  }

  /// 通用识别：用二进制数据上传音频
  static Future<RecognizeResult> recognizeBytes(
      Uint8List audioBytes, String word,
      {String lang = 'putian', String? userId}) async {
    final uri = Uri.parse('$_baseUrl/api/recognize');
    final request = http.MultipartRequest('POST', uri);
    request.fields['word'] = word;
    request.fields['lang'] = lang;
    if (userId != null && userId.isNotEmpty) {
      request.fields['user_id'] = userId;
    }
    request.files.add(http.MultipartFile.fromBytes('audio', audioBytes, filename: 'recording.webm'));
    final streamed = await request.send().timeout(const Duration(seconds: 120));
    final res = await http.Response.fromStream(streamed);
    return RecognizeResult.fromJson(json.decode(res.body));
  }

  static Future<bool> confirm(
      String dialectText, String word,
      {String? userId}) async {
    final res = await http.post(
      Uri.parse('$_baseUrl/api/confirm'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({
        'word': word,
        'dialect_text': dialectText,
        'action': 'confirm',
        if (userId != null && userId.isNotEmpty) 'user_id': userId,
      }),
    ).timeout(const Duration(seconds: 10));
    return res.statusCode == 200;
  }

  static Future<bool> correct(
      String dialectText, String correctMeaning,
      {String? userId}) async {
    final res = await http.post(
      Uri.parse('$_baseUrl/api/confirm'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({
        'dialect_text': dialectText,
        'correct_meaning': correctMeaning,
        'action': 'correct',
        if (userId != null && userId.isNotEmpty) 'user_id': userId,
      }),
    ).timeout(const Duration(seconds: 10));
    return res.statusCode == 200;
  }

  static Future<TranslateResult> translateText(String text,
      {String lang = 'putian', String? userId}) async {
    final res = await http.post(
      Uri.parse('$_baseUrl/api/translate-text'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({
        'text': text,
        'lang': lang,
        if (userId != null && userId.isNotEmpty) 'user_id': userId,
      }),
    ).timeout(const Duration(seconds: 10));
    return TranslateResult.fromJson(json.decode(res.body));
  }

  /// 通用自由发言：用二进制数据上传音频
  static Future<FreeSpeechResult> freeSpeechBytes(
      Uint8List audioBytes,
      {String lang = 'putian', String? userId}) async {
    final uri = Uri.parse('$_baseUrl/api/free-speech');
    final request = http.MultipartRequest('POST', uri);
    request.fields['lang'] = lang;
    if (userId != null && userId.isNotEmpty) {
      request.fields['user_id'] = userId;
    }
    request.files.add(http.MultipartFile.fromBytes('audio', audioBytes, filename: 'recording.webm'));
    final streamed = await request.send().timeout(const Duration(seconds: 120));
    final res = await http.Response.fromStream(streamed);
    return FreeSpeechResult.fromJson(json.decode(res.body));
  }

  static Future<bool> addText(String dialect, String meaning,
      {String? userId}) async {
    final res = await http.post(
      Uri.parse('$_baseUrl/api/add-text'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({
        'dialect': dialect,
        'meaning': meaning,
        if (userId != null && userId.isNotEmpty) 'user_id': userId,
      }),
    ).timeout(const Duration(seconds: 10));
    return res.statusCode == 200;
  }

  static Future<KbResult> searchKB(String query, {String? userId}) async {
    final params = <String, String>{'q': query};
    if (userId != null && userId.isNotEmpty) params['user_id'] = userId;
    final uri = Uri.parse('$_baseUrl/api/search').replace(queryParameters: params);
    final res = await http.get(uri).timeout(const Duration(seconds: 10));
    return KbResult.fromJson(json.decode(res.body));
  }

  static Future<KbResult> getAllKB({String? userId}) async {
    final params = <String, String>{};
    if (userId != null && userId.isNotEmpty) params['user_id'] = userId;
    final uri = Uri.parse('$_baseUrl/api/kb').replace(queryParameters: params);
    final res = await http.get(uri).timeout(const Duration(seconds: 10));
    return KbResult.fromJson(json.decode(res.body));
  }

  static Future<bool> deleteEntry(String dialect, {String? userId}) async {
    final res = await http.post(
      Uri.parse('$_baseUrl/api/delete'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({
        'dialect': dialect,
        if (userId != null && userId.isNotEmpty) 'user_id': userId,
      }),
    ).timeout(const Duration(seconds: 10));
    return res.statusCode == 200;
  }
}

// ---- 数据模型 ----

class NextWord {
  final String word;
  final String category;
  final int level;
  final int index;
  final int total;
  final bool done;
  final String? message;

  NextWord({this.word = '', this.category = '', this.level = 0,
    this.index = 0, this.total = 0, this.done = false, this.message});

  factory NextWord.fromJson(Map<String, dynamic> json) {
    if (json['done'] == true) {
      return NextWord(done: true, message: json['message']);
    }
    return NextWord(
      word: json['word'] ?? '',
      category: json['category'] ?? '',
      level: json['level'] ?? 0,
      index: json['index'] ?? 0,
      total: json['total'] ?? 0,
    );
  }
}

class RecognizeResult {
  final String dialect;
  final String meaning;
  final String audioId;

  RecognizeResult({required this.dialect, required this.meaning, this.audioId = ''});

  factory RecognizeResult.fromJson(Map<String, dynamic> json) => RecognizeResult(
    dialect: json['dialect'] ?? '(未识别)',
    meaning: json['meaning'] ?? '',
    audioId: json['audio_id'] ?? '',
  );
}

class TranslateResult {
  final String dialect;
  final String meaning;

  TranslateResult({required this.dialect, required this.meaning});

  factory TranslateResult.fromJson(Map<String, dynamic> json) => TranslateResult(
    dialect: json['dialect'] ?? '',
    meaning: json['meaning'] ?? '',
  );
}

class FreeSpeechResult {
  final String dialect;
  final String translation;
  final String? audioId;

  FreeSpeechResult({required this.dialect, required this.translation, this.audioId});

  factory FreeSpeechResult.fromJson(Map<String, dynamic> json) => FreeSpeechResult(
    dialect: json['dialect'] ?? '',
    translation: json['translation'] ?? json['dialect'] ?? '',
    audioId: json['audio_id'],
  );
}

class KbResult {
  final int total;
  final List<List<String>> items;

  KbResult({required this.total, required this.items});

  factory KbResult.fromJson(Map<String, dynamic> json) {
    final raw = json['items'] as List<dynamic>? ?? [];
    final items = raw.map<dynamic>((e) {
      if (e is List) return e.map((x) => x.toString()).toList();
      return <String>[];
    }).toList();
    return KbResult(
      total: json['total'] ?? 0,
      items: items.cast<List<String>>(),
    );
  }
}
