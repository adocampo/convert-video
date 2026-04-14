from __future__ import annotations

import json
import os
import threading
import uuid
from typing import TYPE_CHECKING, Dict, List, Optional
from urllib import request
from urllib.parse import urlparse

from clutch.output import warning

if TYPE_CHECKING:
    from clutch.store import JobStore


class NotificationManager:
    """Sends notifications via Telegram Bot API or generic webhooks."""

    VALID_EVENTS = {"job_succeeded", "job_failed", "job_cancelled", "queue_empty"}

    def __init__(self, store: "JobStore"):
        self._store = store
        self._lock = threading.Lock()
        self._channels: List[Dict[str, object]] = []
        self._reload()

    # ── Channel CRUD ──

    def _reload(self):
        with self._lock:
            with self._store._lock, self._store._conn:
                rows = self._store._conn.execute(
                    "SELECT id, type, name, enabled, config_json, events_json "
                    "FROM notification_channels ORDER BY rowid"
                ).fetchall()
            self._channels = [
                {
                    "id": r["id"],
                    "type": r["type"],
                    "name": r["name"],
                    "enabled": bool(r["enabled"]),
                    "config": json.loads(r["config_json"]),
                    "events": json.loads(r["events_json"]),
                }
                for r in rows
            ]

    def list_channels(self) -> List[Dict[str, object]]:
        self._reload()
        safe = []
        for ch in self._channels:
            c = dict(ch)
            cfg = dict(c.get("config") or {})
            # Mask sensitive fields
            if cfg.get("bot_token"):
                cfg["bot_token"] = "••••" + str(cfg["bot_token"])[-4:]
            if cfg.get("headers"):
                cfg["headers"] = {k: "••••" for k in cfg["headers"]}
            c["config"] = cfg
            safe.append(c)
        return safe

    def get_channel(self, channel_id: str) -> Optional[Dict[str, object]]:
        self._reload()
        for ch in self._channels:
            if ch["id"] == channel_id:
                return ch
        return None

    def save_channel(self, payload: Dict[str, object]) -> Dict[str, object]:
        ch_type = str(payload.get("type") or "").strip().lower()
        if ch_type not in ("telegram", "webhook"):
            raise ValueError("Type must be 'telegram' or 'webhook'.")

        name = str(payload.get("name") or "").strip() or ch_type.title()
        enabled = bool(payload.get("enabled", True))
        events = payload.get("events") or []
        if not isinstance(events, list):
            events = []
        events = [e for e in events if e in self.VALID_EVENTS]

        config = payload.get("config") or {}
        if not isinstance(config, dict):
            raise ValueError("Config must be an object.")

        if ch_type == "telegram":
            if not config.get("bot_token"):
                raise ValueError("Telegram bot_token is required.")
            if not config.get("chat_id"):
                raise ValueError("Telegram chat_id is required.")
        elif ch_type == "webhook":
            url = str(config.get("url") or "").strip()
            if not url:
                raise ValueError("Webhook URL is required.")
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                raise ValueError("Webhook URL must use http or https.")
            config["url"] = url

        channel_id = str(payload.get("id") or "").strip()
        is_new = not channel_id

        if is_new:
            channel_id = uuid.uuid4().hex[:12]

        # Merge bot_token: keep old value when masked
        if ch_type == "telegram" and not is_new:
            existing = self.get_channel(channel_id)
            if existing and str(config.get("bot_token", "")).startswith("••••"):
                config["bot_token"] = existing["config"].get("bot_token", "")

        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "INSERT INTO notification_channels (id, type, name, enabled, config_json, events_json) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET type=excluded.type, name=excluded.name, "
                "enabled=excluded.enabled, config_json=excluded.config_json, events_json=excluded.events_json",
                (channel_id, ch_type, name, int(enabled), json.dumps(config), json.dumps(events)),
            )
        self._reload()
        return {"id": channel_id, "saved": True}

    def delete_channel(self, channel_id: str) -> bool:
        with self._store._lock, self._store._conn:
            cur = self._store._conn.execute(
                "DELETE FROM notification_channels WHERE id = ?", (channel_id,)
            )
        self._reload()
        return cur.rowcount > 0

    # ── Sending ──

    def notify(self, event: str, job_record: Dict[str, object]):
        """Fire-and-forget notification for a job event."""
        if event not in self.VALID_EVENTS:
            return
        threading.Thread(
            target=self._send_all, args=(event, job_record), daemon=True
        ).start()

    def _send_all(self, event: str, job_record: Dict[str, object]):
        self._reload()
        for ch in self._channels:
            if not ch["enabled"]:
                continue
            if event not in ch.get("events", []):
                continue
            try:
                if ch["type"] == "telegram":
                    self._send_telegram(ch["config"], event, job_record)
                elif ch["type"] == "webhook":
                    self._send_webhook(ch["config"], event, job_record)
            except Exception as exc:
                warning(f"Notification error ({ch['type']} {ch['id'][:8]}): {exc}")

    def _build_message(self, event: str, job_record: Dict[str, object]) -> str:
        fname = os.path.basename(str(job_record.get("input_file") or "unknown"))
        status = event.replace("job_", "").upper()
        msg = job_record.get("message") or ""
        codec = str(job_record.get("codec") or "")
        lines = [f"<b>Clutch — {status}</b>", f"File: <code>{self._html_escape(fname)}</code>"]
        if codec:
            lines.append(f"Codec: {self._html_escape(codec)}")
        if msg:
            lines.append(f"Message: {self._html_escape(msg)}")
        return "\n".join(lines)

    @staticmethod
    def _html_escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _send_telegram(self, config: Dict, event: str, job_record: Dict[str, object]):
        token = config["bot_token"]
        chat_id = config["chat_id"]
        text = self._build_message(event, job_record)
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with request.urlopen(req, timeout=10) as resp:
            resp.read()

    def _send_webhook(self, config: Dict, event: str, job_record: Dict[str, object]):
        url = config["url"]
        headers = dict(config.get("headers") or {})
        headers.setdefault("Content-Type", "application/json")
        fname = os.path.basename(str(job_record.get("input_file") or "unknown"))
        status = event.replace("job_", "").upper()
        msg = job_record.get("message") or ""
        codec = str(job_record.get("codec") or "")
        text_parts = [f"Clutch — {status}", f"File: {fname}"]
        if codec:
            text_parts.append(f"Codec: {codec}")
        if msg:
            text_parts.append(f"Message: {msg}")
        text = "\n".join(text_parts)
        payload = {
            "text": text,
            "event": event,
            "job": {
                "id": job_record.get("id"),
                "input_file": job_record.get("input_file"),
                "output_file": job_record.get("output_file"),
                "codec": job_record.get("codec"),
                "status": event.replace("job_", ""),
                "message": job_record.get("message"),
            },
        }
        data = json.dumps(payload).encode()
        req = request.Request(url, data=data, headers=headers, method="POST")
        with request.urlopen(req, timeout=10) as resp:
            resp.read()

    def test_channel(self, channel_id: str) -> Dict[str, object]:
        """Send a test notification to verify channel configuration."""
        ch = self.get_channel(channel_id)
        if not ch:
            raise ValueError("Channel not found.")
        dummy_record = {
            "id": "test-000",
            "input_file": "test_file.mkv",
            "output_file": "test_file.mp4",
            "codec": "nvenc_h265",
            "message": "This is a test notification from Clutch.",
        }
        try:
            if ch["type"] == "telegram":
                self._send_telegram(ch["config"], "job_succeeded", dummy_record)
            elif ch["type"] == "webhook":
                self._send_webhook(ch["config"], "job_succeeded", dummy_record)
            return {"ok": True, "message": "Test notification sent."}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}


