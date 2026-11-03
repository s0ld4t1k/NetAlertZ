"""In-app alerts plus optional webhook / Telegram delivery."""

from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request

from .utils import now_str

LEVELS = {"info", "success", "warn", "alert"}


class Notifier:
    """Creates notification records and fans out to external gateways."""

    def __init__(self, db, settings, emit=None, log=None) -> None:
        self.db = db
        self.settings = settings
        self.emit = emit or (lambda *a, **k: None)
        self.log = log or (lambda *a, **k: None)

    def push(self, level: str, content: str, dispatch: bool = True) -> int:
        """Store an in-app notification and optionally send it externally."""
        level = level if level in LEVELS else "info"
        notification_id = self.db.x(
            "INSERT INTO notifications(level, content, created_at) VALUES (?, ?, ?)",
            (level, content, now_str()),
        )
        self.emit("notification", level=level, content=content)
        if dispatch and not self.settings.get_bool("in_app_only"):
            thread = threading.Thread(
                target=self._dispatch, args=(level, content), daemon=True
            )
            thread.start()
        return notification_id

    def _dispatch(self, level: str, content: str) -> None:
        """Send to configured gateways, swallowing transport errors."""
        webhook = str(self.settings.get("webhook_url") or "").strip()
        if webhook:
            try:
                payload = json.dumps(
                    {
                        "app": "NetAlertZ",
                        "level": level,
                        "message": content,
                        "timestamp": now_str(),
                    }
                ).encode()
                request = urllib.request.Request(
                    webhook,
                    data=payload,
                    headers={"Content-Type": "application/json", "User-Agent": "NetAlertZ"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=6):
                    pass
            except Exception as exc:
                self.log("WARN", f"webhook delivery failed: {exc}")

        token = str(self.settings.get("telegram_token") or "").strip()
        chat = str(self.settings.get("telegram_chat") or "").strip()
        if token and chat:
            try:
                body = urllib.parse.urlencode(
                    {"chat_id": chat, "text": f"[NetAlertZ] {content}"}
                ).encode()
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                request = urllib.request.Request(url, data=body, method="POST")
                with urllib.request.urlopen(request, timeout=6):
                    pass
            except Exception as exc:
                self.log("WARN", f"telegram delivery failed: {exc}")

    # ----------------------------------------------------------------- queries
    def list(self, unread_only: bool = False, limit: int = 300) -> list[dict]:
        """Return notifications newest first."""
        where = "WHERE read=0" if unread_only else ""
        return self.db.q(
            f"SELECT * FROM notifications {where} ORDER BY id DESC LIMIT ?", (limit,)
        )

    def unread_count(self) -> int:
        """Return the number of unread notifications."""
        return int(self.db.scalar("SELECT COUNT(*) FROM notifications WHERE read=0", default=0) or 0)

    def mark_read(self, notification_id: int) -> None:
        """Mark a single notification as read."""
        self.db.x("UPDATE notifications SET read=1 WHERE id=?", (notification_id,))

    def mark_all_read(self) -> None:
        """Mark every notification as read."""
        self.db.x("UPDATE notifications SET read=1")

    def delete(self, notification_id: int) -> None:
        """Delete one notification."""
        self.db.x("DELETE FROM notifications WHERE id=?", (notification_id,))

    def clear(self) -> None:
        """Delete all notifications."""
        self.db.x("DELETE FROM notifications")
