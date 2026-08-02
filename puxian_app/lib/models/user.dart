/// 用户数据模型

class UserProfile {
  final String userId;
  final String name;
  final String createdAt;
  final int voiceSamplesCount;
  final int registerSentencesDone;
  final bool registerComplete;
  final String preferredLang;
  final String lastActive;

  UserProfile({
    required this.userId,
    required this.name,
    this.createdAt = '',
    this.voiceSamplesCount = 0,
    this.registerSentencesDone = 0,
    this.registerComplete = false,
    this.preferredLang = 'putian',
    this.lastActive = '',
  });

  factory UserProfile.fromJson(Map<String, dynamic> json) => UserProfile(
    userId: json['user_id'] ?? '',
    name: json['name'] ?? '',
    createdAt: json['created_at'] ?? '',
    voiceSamplesCount: json['voice_samples_count'] ?? 0,
    registerSentencesDone: json['register_sentences_done'] ?? 0,
    registerComplete: json['register_complete'] ?? false,
    preferredLang: json['preferred_lang'] ?? 'putian',
    lastActive: json['last_active'] ?? '',
  );

  Map<String, dynamic> toJson() => {
    'user_id': userId,
    'name': name,
    'created_at': createdAt,
    'voice_samples_count': voiceSamplesCount,
    'register_sentences_done': registerSentencesDone,
    'register_complete': registerComplete,
    'preferred_lang': preferredLang,
    'last_active': lastActive,
  };
}

class UserSummary {
  final String userId;
  final String name;
  final bool registerComplete;
  final int voiceSamplesDone;

  UserSummary({
    required this.userId,
    required this.name,
    this.registerComplete = false,
    this.voiceSamplesDone = 0,
  });

  factory UserSummary.fromJson(Map<String, dynamic> json) => UserSummary(
    userId: json['user_id'] ?? '',
    name: json['name'] ?? '',
    registerComplete: json['register_complete'] ?? false,
    voiceSamplesDone: json['voice_samples_done'] ?? 0,
  );
}

class RegisterSentence {
  final String text;
  final String meaning;

  RegisterSentence({required this.text, required this.meaning});

  factory RegisterSentence.fromJson(Map<String, dynamic> json) => RegisterSentence(
    text: json['text'] ?? '',
    meaning: json['meaning'] ?? '',
  );
}

class RegisterStatus {
  final int done;
  final int total;
  final bool complete;
  final List<RegisterSentence> sentences;
  final int currentSentenceIndex;

  RegisterStatus({
    required this.done,
    required this.total,
    required this.complete,
    required this.sentences,
    required this.currentSentenceIndex,
  });

  factory RegisterStatus.fromJson(Map<String, dynamic> json) => RegisterStatus(
    done: json['done'] ?? 0,
    total: json['total'] ?? 10,
    complete: json['complete'] ?? false,
    sentences: (json['sentences'] as List<dynamic>?)
        ?.map((e) => RegisterSentence.fromJson(e as Map<String, dynamic>))
        .toList() ?? [],
    currentSentenceIndex: json['current_sentence_index'] ?? 0,
  );
}

class UserProgress {
  final String userId;
  final int total;
  final int covered;
  final int personal;
  final int target;
  final UserStats stats;

  UserProgress({
    required this.userId,
    required this.total,
    required this.covered,
    required this.personal,
    required this.target,
    required this.stats,
  });

  factory UserProgress.fromJson(Map<String, dynamic> json) => UserProgress(
    userId: json['user_id'] ?? '',
    total: json['total'] ?? 0,
    covered: json['covered'] ?? 0,
    personal: json['personal'] ?? 0,
    target: json['target'] ?? 1000,
    stats: UserStats.fromJson(json['stats'] as Map<String, dynamic>? ?? {}),
  );

  double get percent => target > 0 ? (covered / target).clamp(0, 1) : 0;
}

class UserStats {
  final int recorded;
  final int confirmed;
  final int corrected;
  final double accuracyPct;

  UserStats({
    this.recorded = 0,
    this.confirmed = 0,
    this.corrected = 0,
    this.accuracyPct = 0,
  });

  factory UserStats.fromJson(Map<String, dynamic> json) => UserStats(
    recorded: json['recorded'] ?? 0,
    confirmed: json['confirmed'] ?? 0,
    corrected: json['corrected'] ?? 0,
    accuracyPct: (json['accuracy_pct'] ?? 0).toDouble(),
  );
}

class AuthResult {
  final UserProfile user;
  final String token;

  AuthResult({required this.user, required this.token});
}
