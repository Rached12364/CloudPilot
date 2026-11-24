"""Piste d'audit chaînée.

Chaque événement contient l'empreinte SHA-256 du précédent : modifier, supprimer ou
insérer une ligne après coup casse la chaîne à cet endroit, et `verify()` le détecte.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64
_lock = threading.Lock()


def _digest(entry: dict) -> str:
    body = {k: entry[k] for k in ("seq", "at", "actor", "event", "details", "prev")}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class AuditTrail:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def entries(self) -> list[dict]:
        with self.path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def record(self, actor: str, event: str, details: dict | None = None) -> dict:
        with _lock:
            entries = self.entries()
            prev = entries[-1]["hash"] if entries else GENESIS
            entry = {"seq": len(entries) + 1, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "actor": actor, "event": event, "details": details or {}, "prev": prev}
            entry["hash"] = _digest(entry)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return entry

    def verify(self) -> dict:
        prev = GENESIS
        for i, e in enumerate(self.entries(), start=1):
            if e.get("seq") != i or e.get("prev") != prev:
                return {"ok": False, "broken_at": i, "reason": "chaînage rompu (ligne supprimée, insérée ou déplacée)"}
            if _digest(e) != e.get("hash"):
                return {"ok": False, "broken_at": i, "reason": "contenu modifié après coup"}
            prev = e["hash"]
        return {"ok": True, "count": len(self.entries())}
