import 'dart:convert';
import 'package:flutter/foundation.dart';
import '../models/user.dart';

/// 本地用户状态管理 — 单例，全局持有当前用户
class UserService {
  // ---- 单例 ----
  static final UserService _instance = UserService._internal();
  factory UserService() => _instance;
  UserService._internal();

  /// 当前登录用户（null = 未登录）
  UserProfile? _currentUser;
  UserProfile? get currentUser => _currentUser;
  bool get isLoggedIn => _currentUser != null;
  String? get userId => _currentUser?.userId;
  String get userName => _currentUser?.name ?? '游客';

  /// 本地缓存的用户列表
  List<UserSummary> _userList = [];
  List<UserSummary> get userList => _userList;

  /// 注册进度缓存
  RegisterStatus? _registerStatus;
  RegisterStatus? get registerStatus => _registerStatus;

  // ---- 事件回调 ----
  VoidCallback? onUserChanged;

  /// 设置当前用户
  void setCurrentUser(UserProfile user) {
    _currentUser = user;
    onUserChanged?.call();
  }

  /// 登出
  void logout() {
    _currentUser = null;
    _registerStatus = null;
    onUserChanged?.call();
  }

  /// 更新用户列表
  void updateUserList(List<UserSummary> users) {
    _userList = users;
  }

  /// 更新注册进度
  void updateRegisterStatus(RegisterStatus status) {
    _registerStatus = status;
  }
}
