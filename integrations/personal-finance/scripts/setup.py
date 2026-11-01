"""Create local-only secrets once. Never print the password or encryption key."""
import base64
import os
from pathlib import Path
import secrets

from argon2 import PasswordHasher

ROOT = Path(__file__).resolve().parents[1]
os.umask(0o077)
for directory in (".secrets", "data/wealthfolio", "data/market", "backups"):
    (ROOT / directory).mkdir(parents=True, exist_ok=True)
env_file = ROOT / ".env"
if env_file.exists():
    print("Existing configuration preserved.")
else:
    if any((ROOT / "data/wealthfolio").rglob("*.db")):
        raise SystemExit("已有数据库但 .env 缺失；请恢复原密钥，拒绝生成不匹配的新密钥。")
    password = secrets.token_urlsafe(24)
    encryption_key = base64.b64encode(secrets.token_bytes(32)).decode()
    password_file = ROOT / ".secrets/local-login-password.txt"
    password_file.write_text(password + "\n")
    env_file.write_text(
        "WF_SECRET_KEY='" + encryption_key + "'\n"
        "WF_AUTH_PASSWORD_HASH='" + PasswordHasher().hash(password) + "'\n"
    )
    print("Created .env and .secrets/local-login-password.txt (owner access only).")
