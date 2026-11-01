"""Phone pairing and request authorisation.

Model (no account, no cloud):

* Requests coming from the computer itself (loopback) are the **desktop** user.
* Any other client (a phone on the LAN) is a **device** and must present a
  token obtained through pairing:

  1. the desktop creates a pairing session -> 6-digit code + QR (URL contains the code);
  2. the phone sends the code with a device name -> a *pending* request;
  3. the desktop user **explicitly approves** (or rejects) the request;
  4. the phone polls its request (with a per-request secret) and receives its
     token once, which it then sends as ``Authorization: Bearer``.

Codes expire after ``pairing_ttl_s`` and allow 5 wrong attempts per session.
Tokens are stored hashed (SHA-256) and expire after ``device_token_ttl_s``.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field

from .config import Settings
from .db import Database


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class PairingSession:
    id: str
    code: str
    expires_at: float
    attempts: int = 0


@dataclass
class PairingRequest:
    id: str
    secret: str
    device_name: str
    created_at: float
    status: str = "pending"        # pending | approved | rejected | delivered
    token: str | None = field(default=None, repr=False)


class PairingError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class PairingManager:
    MAX_ATTEMPTS = 5

    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self._lock = threading.Lock()
        self._sessions: dict[str, PairingSession] = {}
        self._requests: dict[str, PairingRequest] = {}

    def _purge(self) -> None:
        t = time.time()
        for sid in [k for k, s in self._sessions.items() if s.expires_at < t]:
            del self._sessions[sid]
        for rid in [k for k, r in self._requests.items() if r.created_at + self.settings.pairing_ttl_s < t]:
            del self._requests[rid]

    def create_session(self) -> PairingSession:
        with self._lock:
            self._purge()
            s = PairingSession(secrets.token_hex(8), f"{secrets.randbelow(10**6):06d}", time.time() + self.settings.pairing_ttl_s)
            self._sessions[s.id] = s
            return s

    def claim(self, code: str, device_name: str) -> PairingRequest:
        code = (code or "").strip()
        device_name = (device_name or "Téléphone").strip()[:60] or "Téléphone"
        with self._lock:
            self._purge()
            match = next((s for s in self._sessions.values() if secrets.compare_digest(s.code, code)), None)
            if match is None:
                for s in self._sessions.values():  # count a failed attempt against every live session
                    s.attempts += 1
                for sid in [k for k, s in self._sessions.items() if s.attempts >= self.MAX_ATTEMPTS]:
                    del self._sessions[sid]
                raise PairingError("Code d'appairage invalide ou expiré", 403)
            del self._sessions[match.id]  # one code = one device
            r = PairingRequest(secrets.token_hex(8), secrets.token_urlsafe(24), device_name, time.time())
            self._requests[r.id] = r
            return r

    def pending(self) -> list[PairingRequest]:
        with self._lock:
            self._purge()
            return [r for r in self._requests.values() if r.status == "pending"]

    def decide(self, request_id: str, approve: bool) -> PairingRequest:
        with self._lock:
            r = self._requests.get(request_id)
            if r is None or r.status != "pending":
                raise PairingError("Demande introuvable ou déjà traitée", 404)
            if approve:
                token = secrets.token_urlsafe(32)
                t = time.time()
                self.db.insert("devices", {"token_hash": _hash(token), "name": r.device_name, "created_at": t,
                                           "expires_at": t + self.settings.device_token_ttl_s, "last_seen": None})
                r.token, r.status = token, "approved"
            else:
                r.status = "rejected"
            return r

    def poll(self, request_id: str, secret: str) -> dict:
        with self._lock:
            r = self._requests.get(request_id)
            if r is None or not secrets.compare_digest(r.secret, secret or ""):
                raise PairingError("Demande introuvable", 404)
            if r.status == "approved":
                token, r.token, r.status = r.token, None, "delivered"  # token handed out exactly once
                return {"status": "approved", "token": token, "device_name": r.device_name}
            return {"status": r.status}

    # ------------------------------------------------------------- tokens
    def check_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        row = self.db.one("SELECT * FROM devices WHERE token_hash = ?", (_hash(token),))
        if not row or row["expires_at"] < time.time():
            return None
        self.db.update("devices", {"token_hash": row["token_hash"]}, {"last_seen": time.time()})
        return row

    def list_devices(self) -> list[dict]:
        rows = self.db.all("SELECT token_hash, name, created_at, expires_at, last_seen FROM devices ORDER BY created_at DESC")
        for r in rows:
            r["id"] = r.pop("token_hash")[:16]
        return rows

    def revoke(self, device_id: str) -> None:
        rows = self.db.all("SELECT token_hash FROM devices")
        for r in rows:
            if r["token_hash"].startswith(device_id) and len(device_id) >= 8:
                self.db.execute("DELETE FROM devices WHERE token_hash = ?", (r["token_hash"],))
                return
        raise PairingError("Appareil introuvable", 404)
