import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../services/user_service.dart';
import '../models/user.dart';
import 'register_screen.dart';
import 'home_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _userService = UserService();
  List<UserSummary> _users = [];
  bool _loading = true;
  bool _submitting = false;

  // 登录/注册表单
  bool _isRegister = false;
  final _nameController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmPwController = TextEditingController();
  bool _obscurePw = true;
  bool _agreeTerms = false;

  @override
  void initState() {
    super.initState();
    _loadUsers();
  }

  @override
  void dispose() {
    _nameController.dispose();
    _passwordController.dispose();
    _confirmPwController.dispose();
    super.dispose();
  }

  Future<void> _loadUsers() async {
    setState(() => _loading = true);
    try {
      final users = await ApiService.getUsers();
      _userService.updateUserList(users);
      if (mounted) setState(() {
        _users = users;
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// 计算密码强度 (0-100)
  int _calcStrength(String pw) {
    if (pw.isEmpty) return 0;
    int score = 0;
    // 长度
    if (pw.length >= 4) score += 10;
    if (pw.length >= 6) score += 15;
    if (pw.length >= 8) score += 20;
    if (pw.length >= 12) score += 15;
    // 字符多样性
    if (pw.contains(RegExp(r'[a-z]'))) score += 10;
    if (pw.contains(RegExp(r'[A-Z]'))) score += 10;
    if (pw.contains(RegExp(r'[0-9]'))) score += 10;
    if (pw.contains(RegExp(r'[^a-zA-Z0-9]'))) score += 10;
    return score.clamp(0, 100);
  }

  Color _strengthColor(int score) {
    if (score < 30) return Colors.red;
    if (score < 60) return Colors.orange;
    return Colors.green;
  }

  String _strengthLabel(int score) {
    if (score < 30) return '弱';
    if (score < 60) return '中';
    return '强';
  }

  Future<void> _submit() async {
    final name = _nameController.text.trim();
    final password = _passwordController.text;

    if (name.isEmpty || password.isEmpty) {
      _showError('请填写用户名和密码');
      return;
    }

    if (_isRegister) {
      if (password.length < 4) {
        _showError('密码至少 4 位');
        return;
      }
      if (password != _confirmPwController.text) {
        _showError('两次密码不一致');
        return;
      }
      if (!_agreeTerms) {
        _showError('请阅读并同意用户协议和隐私政策');
        return;
      }
    }

    setState(() => _submitting = true);
    try {
      final AuthResult result;
      if (_isRegister) {
        result = await ApiService.register(name, password);
      } else {
        result = await ApiService.login(name, password);
      }
      ApiService.setAuthToken(result.token);
      _userService.setCurrentUser(result.user);

      if (!mounted) return;

      // 注册/登录后始终进入主页，声纹注册改为可选
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (_) => const HomeScreen()),
      );
    } catch (e) {
      _showError(e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: Colors.red),
    );
  }

  void _quickLogin(UserSummary user) {
    _nameController.text = user.name;
    _passwordController.text = '';
    setState(() => _isRegister = false);
    _showError('请在下方输入 ${user.name} 的密码登录');
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final pwScore = _calcStrength(_passwordController.text);

    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 40),

              // Logo
              Icon(Icons.record_voice_over, size: 64,
                  color: theme.colorScheme.primary),
              const SizedBox(height: 12),
              Text(
                '莆仙话训练',
                style: theme.textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 4),
              Text(
                '个人口音引擎',
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
                textAlign: TextAlign.center,
              ),

              const SizedBox(height: 32),

              // Tabs: 登录 / 注册
              Row(
                children: [
                  Expanded(
                    child: _TabButton(
                      label: '登录',
                      selected: !_isRegister,
                      onTap: () => setState(() => _isRegister = false),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _TabButton(
                      label: '注册',
                      selected: _isRegister,
                      onTap: () => setState(() => _isRegister = true),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 24),

              // 用户名
              TextField(
                controller: _nameController,
                decoration: const InputDecoration(
                  labelText: '用户名',
                  prefixIcon: Icon(Icons.person),
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),

              // 密码
              TextField(
                controller: _passwordController,
                obscureText: _obscurePw,
                onChanged: _isRegister ? (_) => setState(() {}) : null,
                decoration: InputDecoration(
                  labelText: '密码',
                  prefixIcon: const Icon(Icons.lock),
                  border: const OutlineInputBorder(),
                  suffixIcon: IconButton(
                    icon: Icon(_obscurePw
                        ? Icons.visibility_off
                        : Icons.visibility),
                    onPressed: () =>
                        setState(() => _obscurePw = !_obscurePw),
                  ),
                ),
                onSubmitted: (_) => _isRegister ? null : _submit(),
              ),

              // 密码强度指示器（注册时）
              if (_isRegister && _passwordController.text.isNotEmpty) ...[
                const SizedBox(height: 6),
                ClipRRect(
                  borderRadius: BorderRadius.circular(3),
                  child: LinearProgressIndicator(
                    value: pwScore / 100,
                    backgroundColor: Colors.grey.shade200,
                    color: _strengthColor(pwScore),
                    minHeight: 4,
                  ),
                ),
                Text(
                  '密码强度: ${_strengthLabel(pwScore)}',
                  style: TextStyle(
                    fontSize: 12,
                    color: _strengthColor(pwScore),
                  ),
                ),
              ],

              // 确认密码（注册时）
              if (_isRegister) ...[
                const SizedBox(height: 12),
                TextField(
                  controller: _confirmPwController,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: '确认密码',
                    prefixIcon: Icon(Icons.lock_outline),
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (_) => _submit(),
                ),
              ],

              // 用户协议（注册时）
              if (_isRegister) ...[
                const SizedBox(height: 16),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SizedBox(
                      width: 24,
                      height: 24,
                      child: Checkbox(
                        value: _agreeTerms,
                        onChanged: (v) => setState(() => _agreeTerms = v ?? false),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: RichText(
                        text: TextSpan(
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                          children: [
                            const TextSpan(text: '我已阅读并同意 '),
                            TextSpan(
                              text: '用户协议',
                              style: TextStyle(
                                color: theme.colorScheme.primary,
                                decoration: TextDecoration.underline,
                              ),
                            ),
                            const TextSpan(text: ' 和 '),
                            TextSpan(
                              text: '隐私政策',
                              style: TextStyle(
                                color: theme.colorScheme.primary,
                                decoration: TextDecoration.underline,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ],

              const SizedBox(height: 24),

              // Submit button
              FilledButton(
                onPressed: _submitting ? null : _submit,
                style: FilledButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                ),
                child: Text(
                  _submitting
                      ? '处理中...'
                      : (_isRegister ? '注册并开始' : '登录'),
                  style: const TextStyle(fontSize: 16),
                ),
              ),

              const SizedBox(height: 32),

              // Existing users
              if (!_isRegister && _users.isNotEmpty) ...[
                Row(
                  children: [
                    const Expanded(child: Divider()),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      child: Text(
                        '已有用户',
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ),
                    const Expanded(child: Divider()),
                  ],
                ),
                const SizedBox(height: 12),
                ..._users.map((user) => Card(
                  margin: const EdgeInsets.only(bottom: 6),
                  child: ListTile(
                    leading: CircleAvatar(
                      backgroundColor: user.registerComplete
                          ? Colors.green.shade100
                          : Colors.orange.shade100,
                      child: Icon(
                        user.registerComplete
                            ? Icons.check_circle
                            : Icons.mic,
                        color: user.registerComplete
                            ? Colors.green
                            : Colors.orange,
                        size: 20,
                      ),
                    ),
                    title: Text(user.name),
                    subtitle: Text(
                      user.registerComplete
                          ? '已注册'
                          : '未完成注册 ${user.voiceSamplesDone}/10',
                      style: TextStyle(
                        fontSize: 12,
                        color: user.registerComplete
                            ? Colors.green
                            : Colors.orange,
                      ),
                    ),
                    trailing: const Icon(Icons.login, size: 20),
                    onTap: () => _quickLogin(user),
                  ),
                )),
              ],

              if (!_isRegister && _users.isEmpty && !_loading)
                Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: Text(
                    '还没有用户，切换到"注册"创建',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TabButton extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _TabButton({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 12),
        decoration: BoxDecoration(
          color: selected
              ? theme.colorScheme.primaryContainer
              : theme.colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Text(
          label,
          textAlign: TextAlign.center,
          style: TextStyle(
            fontWeight: selected ? FontWeight.w600 : FontWeight.normal,
            color: selected
                ? theme.colorScheme.onPrimaryContainer
                : theme.colorScheme.onSurfaceVariant,
          ),
        ),
      ),
    );
  }
}
