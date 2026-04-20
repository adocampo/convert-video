"""Authentication and authorization module for Clutch."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import smtplib
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional, Tuple

# ── Constants ──

ROLES = ("admin", "operator", "viewer")
ROLE_LEVELS = {"admin": 3, "operator": 2, "viewer": 1}
MIN_PASSWORD_LENGTH = 8
TOKEN_EXPIRY_DAYS = 30
RESET_TOKEN_EXPIRY_HOURS = 1

# ── Password hashing (scrypt — memory-hard, no external deps) ──


def _hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """Hash a password using scrypt. Returns ``scrypt$n$r$p$salt_hex$key_hex``."""
    if salt is None:
        salt = os.urandom(32)
    n, r, p = 16384, 8, 1
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=64)
    return f"scrypt${n}${r}${p}${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored scrypt hash."""
    try:
        parts = stored_hash.split("$")
        if parts[0] != "scrypt" or len(parts) != 6:
            return False
        n, r, p_val = int(parts[1]), int(parts[2]), int(parts[3])
        salt = bytes.fromhex(parts[4])
        expected_key = bytes.fromhex(parts[5])
        dk = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p_val, dklen=len(expected_key)
        )
        return hmac.compare_digest(dk, expected_key)
    except (ValueError, IndexError):
        return False


def _hash_token(token: str) -> str:
    """Hash a bearer token for storage (SHA-256)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── Validation helpers ──


def validate_password(password: str) -> Optional[str]:
    """Return an error message if the password is too weak, or ``None`` if valid."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if not any(c.isupper() for c in password):
        return "Password must contain at least one uppercase letter."
    if not any(c.islower() for c in password):
        return "Password must contain at least one lowercase letter."
    if not any(c.isdigit() for c in password):
        return "Password must contain at least one digit."
    if all(c.isalnum() for c in password):
        return "Password must contain at least one special character."
    return None


def validate_email(email: str) -> Optional[str]:
    """Basic structural email validation."""
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return "Invalid email address."
    if len(email) > 254:
        return "Email address too long."
    return None


def validate_username(username: str) -> Optional[str]:
    """Validate a username string."""
    if not username or len(username) < 3:
        return "Username must be at least 3 characters."
    if len(username) > 64:
        return "Username must be at most 64 characters."
    if not username[0].isalpha():
        return "Username must start with a letter."
    if not all(c.isalnum() or c in "-_" for c in username):
        return "Username may only contain letters, digits, hyphens, and underscores."
    return None


# ── In-memory rate limiter ──


class LoginRateLimiter:
    """Tracks failed login attempts per key (IP address)."""

    MAX_ATTEMPTS = 5
    WINDOW_SECONDS = 900  # 15 minutes

    def __init__(self):
        self._attempts: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def record_attempt(self, key: str):
        now = time.monotonic()
        with self._lock:
            bucket = self._attempts.setdefault(key, [])
            bucket.append(now)
            cutoff = now - self.WINDOW_SECONDS
            self._attempts[key] = [t for t in bucket if t > cutoff]

    def is_blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._attempts.get(key, [])
            cutoff = now - self.WINDOW_SECONDS
            recent = [t for t in bucket if t > cutoff]
            self._attempts[key] = recent
            return len(recent) >= self.MAX_ATTEMPTS

    def clear(self, key: str):
        with self._lock:
            self._attempts.pop(key, None)


# ── Persistent auth store (SQLite) ──


class AuthStore:
    """Manages users, tokens, password resets and SMTP config in SQLite.

    Shares the same connection and lock as ``JobStore`` so that all tables
    live in the single service database.
    """

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock):
        self._conn = conn
        self._lock = lock
        self._rate_limiter = LoginRateLimiter()
        self._ensure_schema()

    # ── Schema ──

    def _ensure_schema(self):
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                    email TEXT UNIQUE NOT NULL COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'viewer',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS password_resets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS smtp_config (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    host TEXT NOT NULL DEFAULT '',
                    port INTEGER NOT NULL DEFAULT 587,
                    username TEXT NOT NULL DEFAULT '',
                    password TEXT NOT NULL DEFAULT '',
                    use_tls INTEGER NOT NULL DEFAULT 1,
                    from_address TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id INTEGER PRIMARY KEY,
                    theme TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL DEFAULT '',
                    date_format TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            # Add auth_skipped flag to service_config (may already exist)
            svc_cols = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(service_config)").fetchall()
            }
            if "auth_skipped" not in svc_cols:
                self._conn.execute(
                    "ALTER TABLE service_config ADD COLUMN auth_skipped INTEGER NOT NULL DEFAULT 0"
                )

    # ── Setup state ──

    def needs_setup(self) -> bool:
        """True when no users exist and auth has not been explicitly skipped."""
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if count > 0:
                return False
            row = self._conn.execute(
                "SELECT auth_skipped FROM service_config WHERE singleton = 1"
            ).fetchone()
            return not (row and row["auth_skipped"])

    def is_auth_enabled(self) -> bool:
        """True when at least one user exists and auth was not skipped."""
        with self._lock:
            row = self._conn.execute(
                "SELECT auth_skipped FROM service_config WHERE singleton = 1"
            ).fetchone()
            if row and row["auth_skipped"]:
                return False
            return self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0

    def skip_auth(self):
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE service_config SET auth_skipped = 1 WHERE singleton = 1"
            )

    def enable_auth(self):
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE service_config SET auth_skipped = 0 WHERE singleton = 1"
            )

    def user_count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # ── User CRUD ──

    def create_user(
        self, username: str, email: str, password: str, role: str = "viewer"
    ) -> Dict[str, object]:
        err = validate_username(username)
        if err:
            raise ValueError(err)
        err = validate_email(email)
        if err:
            raise ValueError(err)
        err = validate_password(password)
        if err:
            raise ValueError(err)
        if role not in ROLES:
            raise ValueError(f"Role must be one of: {', '.join(ROLES)}")

        now = datetime.now(timezone.utc).isoformat()
        password_hash = _hash_password(password)

        with self._lock, self._conn:
            try:
                self._conn.execute(
                    "INSERT INTO users (username, email, password_hash, role, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (username, email, password_hash, role, now, now),
                )
                user_id = self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            except sqlite3.IntegrityError as exc:
                msg = str(exc).lower()
                if "username" in msg:
                    raise ValueError("Username already exists.") from exc
                if "email" in msg:
                    raise ValueError("Email already in use.") from exc
                raise ValueError("User already exists.") from exc

        return {"id": user_id, "username": username, "email": email, "role": role, "created_at": now}

    def list_users(self) -> List[Dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, username, email, role, created_at, updated_at FROM users ORDER BY id"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_user(self, user_id: int) -> Optional[Dict[str, object]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, username, email, role, created_at, updated_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, object]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, username, email, password_hash, role, created_at, updated_at "
                "FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            return dict(row) if row else None

    def update_user(
        self,
        user_id: int,
        *,
        username: Optional[str] = None,
        email: Optional[str] = None,
        role: Optional[str] = None,
    ) -> Optional[Dict[str, object]]:
        updates: List[str] = []
        params: List[object] = []
        if username is not None:
            err = validate_username(username)
            if err:
                raise ValueError(err)
            updates.append("username = ?")
            params.append(username)
        if email is not None:
            err = validate_email(email)
            if err:
                raise ValueError(err)
            updates.append("email = ?")
            params.append(email)
        if role is not None:
            if role not in ROLES:
                raise ValueError(f"Role must be one of: {', '.join(ROLES)}")
            updates.append("role = ?")
            params.append(role)
        if not updates:
            raise ValueError("No fields to update.")

        updates.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(user_id)

        with self._lock, self._conn:
            try:
                self._conn.execute(
                    f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
            except sqlite3.IntegrityError as exc:
                msg = str(exc).lower()
                if "username" in msg:
                    raise ValueError("Username already exists.") from exc
                if "email" in msg:
                    raise ValueError("Email already in use.") from exc
                raise ValueError("Conflict.") from exc

        return self.get_user(user_id)

    def delete_user(self, user_id: int) -> bool:
        with self._lock, self._conn:
            row = self._conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                return False
            if row["role"] == "admin":
                admin_count = self._conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin'"
                ).fetchone()[0]
                if admin_count <= 1:
                    raise ValueError("Cannot delete the last admin user.")
            self._conn.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
            self._conn.execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))
            self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            return True

    def change_password(self, user_id: int, old_password: str, new_password: str):
        err = validate_password(new_password)
        if err:
            raise ValueError(err)
        with self._lock:
            row = self._conn.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if not row:
                raise ValueError("User not found.")
            if not _verify_password(old_password, row["password_hash"]):
                raise ValueError("Current password is incorrect.")
            new_hash = _hash_password(new_password)
            with self._conn:
                self._conn.execute(
                    "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                    (new_hash, datetime.now(timezone.utc).isoformat(), user_id),
                )
                # Invalidate every token so the user must re-authenticate
                self._conn.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))

    def set_password_admin(self, user_id: int, new_password: str):
        """Admin-level password reset (no old password required)."""
        err = validate_password(new_password)
        if err:
            raise ValueError(err)
        new_hash = _hash_password(new_password)
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (new_hash, datetime.now(timezone.utc).isoformat(), user_id),
            )
            self._conn.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))

    # ── User preferences ──

    def get_user_preferences(self, user_id: int) -> Dict[str, str]:
        """Return user preferences or empty defaults."""
        with self._lock:
            row = self._conn.execute(
                "SELECT theme, language, date_format FROM user_preferences WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row:
            return {"theme": row["theme"], "language": row["language"], "date_format": row["date_format"]}
        return {"theme": "", "language": "", "date_format": ""}

    def update_user_preferences(
        self, user_id: int, *, theme: str = "", language: str = "", date_format: str = ""
    ) -> Dict[str, str]:
        """Upsert user preferences."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO user_preferences (user_id, theme, language, date_format)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    theme = excluded.theme,
                    language = excluded.language,
                    date_format = excluded.date_format
                """,
                (user_id, theme, language, date_format),
            )
        return {"theme": theme, "language": language, "date_format": date_format}

    # ── Authentication ──

    def authenticate(
        self, username: str, password: str, client_ip: str = ""
    ) -> Tuple[Optional[Dict[str, object]], Optional[str]]:
        """Authenticate credentials. Returns ``(user, token)`` or ``(None, error_message)``."""
        rate_key = client_ip or username
        if self._rate_limiter.is_blocked(rate_key):
            return None, "Too many login attempts. Please try again later."

        user = self.get_user_by_username(username)
        if not user or not _verify_password(password, user.pop("password_hash", "")):
            self._rate_limiter.record_attempt(rate_key)
            return None, "Invalid username or password."

        self._rate_limiter.clear(rate_key)

        token = secrets.token_urlsafe(32)
        token_hash = _hash_token(token)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=TOKEN_EXPIRY_DAYS)

        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO auth_tokens (user_id, token_hash, name, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user["id"], token_hash, "_session", now.isoformat(), expires.isoformat()),
            )

        safe_user = {k: v for k, v in user.items() if k != "password_hash"}
        return safe_user, token

    def validate_token(self, token: str) -> Optional[Dict[str, object]]:
        """Return the owning user dict if *token* is valid, else ``None``."""
        token_hash = _hash_token(token)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            row = self._conn.execute(
                "SELECT u.id, u.username, u.email, u.role "
                "FROM auth_tokens t JOIN users u ON u.id = t.user_id "
                "WHERE t.token_hash = ? AND t.expires_at > ?",
                (token_hash, now),
            ).fetchone()
            return dict(row) if row else None

    def revoke_token(self, token: str):
        token_hash = _hash_token(token)
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))

    def revoke_all_tokens(self, user_id: int):
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))

    def list_tokens(self, user_id: int) -> List[Dict[str, object]]:
        """List API tokens only (excludes internal session tokens)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            # Migrate legacy session tokens that were created with empty name
            self._conn.execute(
                "UPDATE auth_tokens SET name = '_session' "
                "WHERE user_id = ? AND name = '' AND id NOT IN ("
                "  SELECT id FROM auth_tokens WHERE user_id = ? AND name != '' AND name != '_session'"
                ")",
                (user_id, user_id),
            )
            rows = self._conn.execute(
                "SELECT id, name, created_at, expires_at FROM auth_tokens "
                "WHERE user_id = ? AND expires_at > ? AND name != '_session' AND name != '' "
                "ORDER BY created_at DESC",
                (user_id, now),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_api_token(
        self, user_id: int, name: str = "", days: int = 365
    ) -> Tuple[str, Dict[str, object]]:
        """Create a named API token. Returns ``(plain_token, info_dict)``."""
        token = secrets.token_urlsafe(32)
        token_hash = _hash_token(token)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=days)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO auth_tokens (user_id, token_hash, name, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, token_hash, name, now.isoformat(), expires.isoformat()),
            )
            token_id = self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return token, {
            "id": token_id,
            "name": name,
            "created_at": now.isoformat(),
            "expires_at": expires.isoformat(),
        }

    def delete_token_by_id(self, token_id: int, user_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM auth_tokens WHERE id = ? AND user_id = ?",
                (token_id, user_id),
            )
            return cur.rowcount > 0

    def admin_delete_token(self, token_id: int) -> bool:
        """Delete any token by ID regardless of owner (admin-only)."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM auth_tokens WHERE id = ?",
                (token_id,),
            )
            return cur.rowcount > 0

    def list_all_tokens(self) -> List[Dict[str, object]]:
        """List all API tokens across all users (admin view)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            rows = self._conn.execute(
                "SELECT t.id, t.name, t.created_at, t.expires_at, t.user_id, u.username "
                "FROM auth_tokens t JOIN users u ON t.user_id = u.id "
                "WHERE t.expires_at > ? AND t.name != '_session' AND t.name != '' "
                "ORDER BY t.created_at DESC",
                (now,),
            ).fetchall()
            return [dict(row) for row in rows]

    # ── Password reset ──

    def create_password_reset(self, email: str) -> Optional[Tuple[str, Dict[str, object]]]:
        """Return ``(plain_token, user_dict)`` or ``None`` if email not found."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, username, email FROM users WHERE email = ?", (email,)
            ).fetchone()
            if not row:
                return None
            user = dict(row)

        token = secrets.token_urlsafe(32)
        token_hash = _hash_token(token)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=RESET_TOKEN_EXPIRY_HOURS)

        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE password_resets SET used = 1 WHERE user_id = ? AND used = 0",
                (user["id"],),
            )
            self._conn.execute(
                "INSERT INTO password_resets (user_id, token_hash, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (user["id"], token_hash, now.isoformat(), expires.isoformat()),
            )

        return token, user

    def confirm_password_reset(self, token: str, new_password: str):
        err = validate_password(new_password)
        if err:
            raise ValueError(err)

        token_hash = _hash_token(token)
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            row = self._conn.execute(
                "SELECT id, user_id FROM password_resets "
                "WHERE token_hash = ? AND used = 0 AND expires_at > ?",
                (token_hash, now),
            ).fetchone()
            if not row:
                raise ValueError("Invalid or expired reset token.")

            reset_id = row["id"]
            user_id = row["user_id"]
            new_hash = _hash_password(new_password)

            with self._conn:
                self._conn.execute(
                    "UPDATE password_resets SET used = 1 WHERE id = ?", (reset_id,)
                )
                self._conn.execute(
                    "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                    (new_hash, now, user_id),
                )
                self._conn.execute(
                    "DELETE FROM auth_tokens WHERE user_id = ?", (user_id,)
                )

    # ── SMTP ──

    def get_smtp_config(self) -> Dict[str, object]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM smtp_config WHERE singleton = 1"
            ).fetchone()
            if not row:
                return {
                    "host": "", "port": 587, "username": "", "password": "",
                    "use_tls": True, "from_address": "",
                }
            return {
                "host": row["host"],
                "port": row["port"],
                "username": row["username"],
                "password": row["password"],
                "use_tls": bool(row["use_tls"]),
                "from_address": row["from_address"],
            }

    def get_smtp_config_safe(self) -> Dict[str, object]:
        """Same as ``get_smtp_config`` but masks the password."""
        cfg = self.get_smtp_config()
        cfg["password"] = "••••••••" if cfg["password"] else ""
        return cfg

    def update_smtp_config(self, config: Dict[str, object]):
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO smtp_config (singleton, host, port, username, password, use_tls, from_address)
                VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    host = excluded.host,
                    port = excluded.port,
                    username = excluded.username,
                    password = excluded.password,
                    use_tls = excluded.use_tls,
                    from_address = excluded.from_address
                """,
                (
                    str(config.get("host") or ""),
                    int(config.get("port") or 587),
                    str(config.get("username") or ""),
                    str(config.get("password") or ""),
                    int(bool(config.get("use_tls", True))),
                    str(config.get("from_address") or ""),
                ),
            )

    def test_smtp(self, recipient: str):
        """Send a test email to *recipient* using the saved SMTP settings."""
        smtp = self.get_smtp_config()
        if not smtp["host"]:
            raise ValueError("SMTP is not configured.")

        msg = MIMEText(
            "This is a test email from Clutch.\n\n"
            "If you received this message, your SMTP settings are working correctly.",
            "plain",
        )
        msg["Subject"] = "Clutch \u2014 SMTP Test"
        msg["From"] = smtp["from_address"] or smtp["username"]
        msg["To"] = recipient

        self._send_smtp(smtp, recipient, msg)

    def _send_smtp(self, smtp: Dict[str, object], recipient: str, msg):
        """Send *msg* via *smtp* config. Picks SMTP_SSL for port 465, STARTTLS otherwise."""
        host = str(smtp["host"])
        port = int(smtp["port"])
        try:
            if port == 465:
                server = smtplib.SMTP_SSL(host, port, timeout=10)
            else:
                server = smtplib.SMTP(host, port, timeout=10)
                if smtp["use_tls"]:
                    server.starttls()
            if smtp["username"]:
                server.login(str(smtp["username"]), str(smtp["password"]))
            server.sendmail(str(msg["From"]), [recipient], msg.as_string())
            server.quit()
        except Exception as exc:
            raise ValueError(f"SMTP error: {exc}") from exc

    def send_password_reset_email(self, user: Dict[str, object], reset_token: str, base_url: str):
        smtp = self.get_smtp_config()
        if not smtp["host"]:
            raise ValueError("SMTP is not configured. Please contact an administrator.")

        reset_url = f"{base_url}/login#reset-password?token={reset_token}"
        username = user["username"]
        recipient = str(user["email"])

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Clutch \u2014 Password Reset"
        msg["From"] = smtp["from_address"] or smtp["username"]
        msg["To"] = recipient

        text_body = (
            f"Password Reset Request\n\n"
            f"Hello {username},\n\n"
            f"A password reset was requested for your Clutch account.\n\n"
            f"Reset your password using this link:\n{reset_url}\n\n"
            f"This link expires in {RESET_TOKEN_EXPIRY_HOURS} hour(s). "
            f"If you did not request this, please ignore this email.\n\n"
            f"\u2014 Clutch"
        )
        html_body = (
            '<!DOCTYPE html>'
            '<html><body style="font-family:sans-serif;color:#222;max-width:480px;margin:0 auto">'
            '<h2 style="color:#0d6b61">Password Reset</h2>'
            f'<p>Hello <strong>{username}</strong>,</p>'
            '<p>A password reset was requested for your Clutch account.</p>'
            f'<p><a href="{reset_url}" style="display:inline-block;padding:10px 24px;'
            'background:#0d6b61;color:#fff;border-radius:6px;text-decoration:none;'
            'font-weight:bold">Reset Password</a></p>'
            '<p style="font-size:13px;color:#888">This link expires in '
            f'{RESET_TOKEN_EXPIRY_HOURS} hour(s). If you did not request this, ignore this email.</p>'
            '</body></html>'
        )
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        self._send_smtp(smtp, recipient, msg)

    # ── Cleanup ──

    def purge_expired_tokens(self):
        """Remove expired tokens and used password resets."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM auth_tokens WHERE expires_at <= ?", (now,))
            self._conn.execute(
                "DELETE FROM password_resets WHERE used = 1 OR expires_at <= ?", (now,)
            )


# ── Role checking utilities ──


def has_role(user: Optional[Dict[str, object]], minimum_role: str) -> bool:
    """Check if *user* has at least *minimum_role* level."""
    if not user:
        return False
    user_level = ROLE_LEVELS.get(str(user.get("role", "")), 0)
    required_level = ROLE_LEVELS.get(minimum_role, 999)
    return user_level >= required_level
