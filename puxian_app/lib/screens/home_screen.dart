import 'package:flutter/material.dart';
import 'read_tab.dart';
import 'free_tab.dart';
import 'kb_tab.dart';
import 'register_screen.dart';
import '../services/api_service.dart';
import '../services/user_service.dart';
import '../models/user.dart';
import 'login_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _currentIndex = 0;
  UserProgress? _progress;
  final _userService = UserService();
  bool _loadingProgress = true;

  final _pages = [
    ReadTab(),
    FreeTab(),
    KbTab(),
  ];

  @override
  void initState() {
    super.initState();
    _loadProgress();
  }

  String get _userId => _userService.userId ?? '';

  Future<void> _loadProgress() async {
    setState(() => _loadingProgress = true);
    try {
      final p = await ApiService.getProgress(userId: _userId);
      if (mounted) setState(() {
        _progress = p;
        _loadingProgress = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loadingProgress = false);
    }
  }

  void _showUserMenu() {
    final user = _userService.currentUser;
    final regComplete = user?.registerComplete ?? false;

    showModalBottomSheet(
      context: context,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                _userService.userName,
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 4),
              if (_progress != null) ...[
                Text(
                  '已录 ${_progress!.personal} 条个人映射',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                if (_progress!.stats.accuracyPct > 0)
                  Text(
                    '识别准确率: ${_progress!.stats.accuracyPct}%',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
              ],
              const SizedBox(height: 16),

              // 声纹注册入口
              if (!regComplete)
                FilledButton.tonalIcon(
                  onPressed: () {
                    Navigator.pop(ctx);
                    _startVoiceRegister();
                  },
                  icon: const Icon(Icons.mic),
                  label: const Text('声纹注册（可选）'),
                ),

              if (!regComplete) const SizedBox(height: 8),

              FilledButton.tonalIcon(
                onPressed: () {
                  Navigator.pop(ctx);
                  _userService.logout();
                  Navigator.pushReplacement(
                    context,
                    MaterialPageRoute(builder: (_) => const LoginScreen()),
                  );
                },
                icon: const Icon(Icons.swap_horiz),
                label: const Text('切换用户'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _startVoiceRegister() {
    final user = _userService.currentUser;
    if (user == null) return;
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => RegisterScreen(userProfile: user, fromHome: true),
      ),
    ).then((_) => _loadProgress());
  }

  void refreshProgress() => _loadProgress();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final user = _userService.currentUser;
    final userName = user?.name ?? '用户';
    final accuracy = _progress?.stats.accuracyPct ?? 0;
    final regComplete = user?.registerComplete ?? false;

    return Scaffold(
      appBar: AppBar(
        title: Column(
          children: [
            Text(
              '莆仙话训练',
              style: TextStyle(
                fontWeight: FontWeight.w600,
                fontSize: 18,
                foreground: Paint()..shader = LinearGradient(
                  colors: [theme.colorScheme.primary, const Color(0xFF764BA2)],
                ).createShader(const Rect.fromLTWH(0, 0, 200, 50)),
              ),
            ),
            if (_progress != null)
              Text(
                '个人 ${_progress!.personal} 条 · ${accuracy > 0 ? '准确率 $accuracy%' : ''}',
                style: TextStyle(fontSize: 11, color: theme.colorScheme.onSurfaceVariant),
              ),
          ],
        ),
        actions: [
          // User profile button
          GestureDetector(
            onTap: _showUserMenu,
            child: Container(
              margin: const EdgeInsets.only(right: 8),
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: theme.colorScheme.primaryContainer,
                borderRadius: BorderRadius.circular(20),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.person, size: 16, color: theme.colorScheme.onPrimaryContainer),
                  const SizedBox(width: 4),
                  Text(
                    userName,
                    style: TextStyle(
                      fontSize: 13,
                      color: theme.colorScheme.onPrimaryContainer,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
        bottom: _progress != null ? PreferredSize(
          preferredSize: const Size.fromHeight(30),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Column(
              children: [
                LinearProgressIndicator(
                  value: _progress!.percent,
                  backgroundColor: theme.colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(3),
                ),
                const SizedBox(height: 2),
                Text(
                  '${_progress!.covered} / 目标 ${_progress!.target}  · 共 ${_progress!.total} 条',
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ) : null,
      ),
      body: Column(
        children: [
          // 未完成声纹注册的提示横幅
          if (!regComplete)
            GestureDetector(
              onTap: _startVoiceRegister,
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                color: Colors.orange.shade50,
                child: Row(
                  children: [
                    Icon(Icons.mic, size: 18, color: Colors.orange.shade700),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        '声纹注册后可提高识别准确率，去录制 →',
                        style: TextStyle(fontSize: 13, color: Colors.orange.shade800),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          Expanded(
            child: IndexedStack(
              index: _currentIndex,
              children: _pages,
            ),
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (i) => setState(() => _currentIndex = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.menu_book), label: '朗读'),
          NavigationDestination(icon: Icon(Icons.record_voice_over), label: '对话'),
          NavigationDestination(icon: Icon(Icons.library_books), label: '词库'),
        ],
      ),
    );
  }
}
