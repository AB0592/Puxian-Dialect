#!/usr/bin/env python3
"""
JWT 认证模块

为方言助手提供安全的用户登录/注册认证。
"""

import os
import json
import time
import hashlib
import secrets
from pathlib import Path
from typing import Optional

# JWT
try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False

# 密钥文件
SECRETS_DIR = Path(__file__).parent.parent / "secrets"
SECRETS_DIR.mkdir(parents=True, exist_ok=True)
SECRET_FILE = SECRETS_DIR / "jwt_secret.key"

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 72  # 3天过期

# ============================================================
# 密钥管理
# ============================================================

def _get_secret() -> str:
    """获取或生成 JWT 密钥"""
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text().strip()
    secret = secrets.token_hex(32)
    SECRET_FILE.write_text(secret)
    print(f"🔑 JWT 密钥已生成: {SECRET_FILE}")
    return secret


def _hash_password(password: str, salt: str = None) -> tuple[str, str]:
    """密码哈希"""
    if salt is None:
        salt = secrets.token_hex(8)
    hashed = hashlib.sha256((password + salt).encode()).hexdigest()
    return hashed, salt


# ============================================================
# 用户密码存储
# ============================================================

PASSWORDS_FILE = SECRETS_DIR / "passwords.json"


def _load_passwords() -> dict:
    if PASSWORDS_FILE.exists():
        with open(PASSWORDS_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_passwords(pw: dict):
    PASSWORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PASSWORDS_FILE, "w") as f:
        json.dump(pw, f, ensure_ascii=False, indent=2)


def set_password(user_id: str, password: str):
    """设置用户密码"""
    hashed, salt = _hash_password(password)
    pw = _load_passwords()
    pw[user_id] = {"hash": hashed, "salt": salt}
    _save_passwords(pw)


def verify_password(user_id: str, password: str) -> bool:
    """验证用户密码"""
    pw = _load_passwords()
    if user_id not in pw:
        return False
    entry = pw[user_id]
    hashed, _ = _hash_password(password, entry["salt"])
    return hashed == entry["hash"]


def has_password(user_id: str) -> bool:
    pw = _load_passwords()
    return user_id in pw


# ============================================================
# JWT Token
# ============================================================

def create_token(user_id: str, name: str) -> str:
    """生成 JWT token"""
    if not JWT_AVAILABLE:
        # 回退方案：简单 token
        payload = {
            "user_id": user_id,
            "name": name,
            "exp": int(time.time()) + TOKEN_EXPIRE_HOURS * 3600,
            "iat": int(time.time()),
        }
        # 简单签名
        raw = json.dumps(payload, separators=(",", ":"))
        sig = hashlib.sha256((raw + _get_secret()).encode()).hexdigest()[:16]
        import base64
        return base64.b64encode(f"{raw}|{sig}".encode()).decode()

    payload = {
        "user_id": user_id,
        "name": name,
        "exp": int(time.time()) + TOKEN_EXPIRE_HOURS * 3600,
        "iat": int(time.time()),
    }
    token = jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)
    return token


def verify_token(token: str) -> Optional[dict]:
    """验证 JWT token，返回 payload 或 None"""
    if not token:
        return None

    if not JWT_AVAILABLE:
        # 回退验证
        try:
            import base64
            decoded = base64.b64decode(token).decode()
            raw, sig = decoded.rsplit("|", 1)
            expected_sig = hashlib.sha256(
                (raw + _get_secret()).encode()
            ).hexdigest()[:16]
            if sig != expected_sig:
                return None
            payload = json.loads(raw)
            if payload.get("exp", 0) < time.time():
                return None
            return payload
        except Exception:
            return None

    try:
        payload = jwt.decode(
            token, _get_secret(), algorithms=[ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def token_required(token: str) -> Optional[dict]:
    """从 Authorization header 提取并验证 token"""
    if not token:
        return None
    # 支持 "Bearer xxx" 格式
    if token.startswith("Bearer "):
        token = token[7:]
    return verify_token(token)


# ============================================================
# CLI 测试
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("JWT 认证模块")
        print("\n命令:")
        print("  create-token <user_id> <name>  生成测试 token")
        print("  verify <token>                 验证 token")
        print("  set-pw <user_id> <password>    设置密码")
        print("  check-pw <user_id> <password>  验证密码")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "create-token" and len(sys.argv) > 3:
        token = create_token(sys.argv[2], sys.argv[3])
        print(f"Token: {token}")
        print(f"过期: {TOKEN_EXPIRE_HOURS}小时")

    elif cmd == "verify" and len(sys.argv) > 2:
        payload = verify_token(sys.argv[2])
        if payload:
            print(f"✅ 有效 Token")
            print(f"  user_id: {payload['user_id']}")
            print(f"  name:    {payload['name']}")
            print(f"  过期时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(payload['exp']))}")
        else:
            print("❌ 无效或已过期 Token")

    elif cmd == "set-pw" and len(sys.argv) > 3:
        set_password(sys.argv[2], sys.argv[3])
        print("密码已设置")

    elif cmd == "check-pw" and len(sys.argv) > 3:
        ok = verify_password(sys.argv[2], sys.argv[3])
        print("✅ 密码正确" if ok else "❌ 密码错误")

    else:
        print("参数错误")
