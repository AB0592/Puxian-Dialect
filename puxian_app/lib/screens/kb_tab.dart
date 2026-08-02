import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../services/user_service.dart';

class KbTab extends StatefulWidget {
  const KbTab({super.key});

  @override
  State<KbTab> createState() => _KbTabState();
}

class _KbTabState extends State<KbTab> {
  final _userService = UserService();
  List<List<String>> _items = [];
  int _total = 0;
  bool _loading = true;
  String _scope = 'base';
  final _searchController = TextEditingController();

  String get _userId => _userService.userId ?? '';

  @override
  void initState() {
    super.initState();
    _loadKB();
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _loadKB({String query = ''}) async {
    setState(() => _loading = true);
    try {
      final result = query.isEmpty
          ? await ApiService.getAllKB(userId: _userId)
          : await ApiService.searchKB(query, userId: _userId);
      if (mounted) {
        setState(() {
          _items = result.items;
          _total = result.total;
          _scope = query.isEmpty ? 'personal' : 'personal';
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _delete(String dialect) async {
    final ok = await ApiService.deleteEntry(dialect, userId: _userId);
    if (ok) {
      final q = _searchController.text.trim();
      _loadKB(query: q);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _searchController,
                  decoration: const InputDecoration(
                    hintText: '搜索方言或中文...',
                    border: OutlineInputBorder(),
                    contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                    prefixIcon: Icon(Icons.search),
                  ),
                  onSubmitted: (v) => _loadKB(query: v.trim()),
                  onChanged: (v) => _loadKB(query: v.trim()),
                ),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Row(
            children: [
              Text(
                '$_total 条个人词条',
                style: theme.textTheme.labelSmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
              const Spacer(),
              if (_userService.isLoggedIn)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: Colors.blue.shade50,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    _userService.userName,
                    style: TextStyle(fontSize: 11, color: Colors.blue.shade700),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _items.isEmpty
                  ? Center(
                      child: Text(
                        '暂无个人映射词条\n开始朗读训练后会自动生成',
                        textAlign: TextAlign.center,
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    )
                  : ListView.builder(
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                      itemCount: _items.length,
                      itemBuilder: (ctx, i) {
                        final item = _items[i];
                        final dialect = item.isNotEmpty ? item[0] : '';
                        final meaning = item.length > 1 ? item[1] : '';
                        return Card(
                          margin: const EdgeInsets.only(bottom: 6),
                          child: ListTile(
                            dense: true,
                            title: Text(dialect, style: const TextStyle(fontWeight: FontWeight.w500)),
                            subtitle: Text(meaning, style: TextStyle(color: Colors.grey.shade600)),
                            trailing: IconButton(
                              icon: Icon(Icons.delete_outline, color: Colors.red.shade300, size: 20),
                              onPressed: dialect.isNotEmpty ? () => _delete(dialect) : null,
                            ),
                          ),
                        );
                      },
                    ),
        ),
      ],
    );
  }
}
