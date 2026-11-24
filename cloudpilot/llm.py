"""LLM local via Ollama (optionnel).

Le LLM sert au superviseur (comprendre la mission et choisir les agents) et au rapport
(rédiger la synthèse). Il ne décide jamais seul d'une action : les constats viennent des
données réelles du parc, les actions passent par OPA et la validation humaine.
Sans Ollama, un mode déterministe prend le relais et l'interface l'indique.
"""
from __future__ import annotations

import json
import re

import requests

from .config import Settings


class LLM:
    def __init__(self, settings: Settings):
        self.s = settings
        self.available = False
        if settings.llm_enabled:
            try:
                tags = requests.get(f"{settings.ollama_url}/api/tags", timeout=2).json()
                names = {m.get("name") for m in tags.get("models", [])}
                self.available = settings.ollama_model in names
            except Exception:
                self.available = False

    @property
    def label(self) -> str:
        return f"Ollama · {self.s.ollama_model}" if self.available else "déterministe (sans LLM)"

    def complete(self, system: str, prompt: str, as_json: bool = False, timeout: int = 90) -> str | None:
        if not self.available:
            return None
        body = {"model": self.s.ollama_model, "system": system, "prompt": prompt, "stream": False,
                "options": {"temperature": 0}}
        if as_json:
            body["format"] = "json"
        try:
            r = requests.post(f"{self.s.ollama_url}/api/generate", json=body, timeout=timeout)
            r.raise_for_status()
            return r.json().get("response", "").strip()
        except Exception:
            return None

    def complete_json(self, system: str, prompt: str) -> dict | None:
        raw = self.complete(system, prompt, as_json=True)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.S)
            try:
                return json.loads(m.group(0)) if m else None
            except json.JSONDecodeError:
                return None
