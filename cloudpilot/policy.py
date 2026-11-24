"""Client des garde-fous OPA.

Ordre de préférence : serveur OPA (OPA_URL), puis binaire `opa eval`. Si OPA est absent,
un moteur de secours applique les mêmes règles en Python et l'interface l'affiche
clairement (« mode secours ») : le projet reste démontrable, sans prétendre utiliser OPA.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import requests

from .config import Settings

EU_REGIONS = {"eu-west-3", "eu-central-1", "francecentral", "westeurope", "europe-west1", "europe-west9"}


class PolicyEngine:
    def __init__(self, settings: Settings):
        self.s = settings
        self.mode = "secours"
        self.bin = None
        if settings.opa_url:
            self.mode = "opa-serveur"
        else:
            local = settings.opa_bin or shutil.which("opa") or _local_opa(settings)
            if local:
                self.bin, self.mode = local, "opa-binaire"

    def evaluate(self, proposal: dict, resource: dict, impact: dict) -> dict:
        payload = {"proposal": {k: proposal[k] for k in ("action", "monthly_delta_eur", "params")},
                   "resource": {k: resource.get(k) for k in ("id", "env", "data_class", "type", "region")},
                   "impact": impact}
        if self.mode == "opa-serveur":
            r = requests.post(f"{self.s.opa_url.rstrip('/')}/v1/data/cloudpilot/decision",
                              json={"input": payload}, timeout=10)
            r.raise_for_status()
            out = r.json().get("result")
        elif self.mode == "opa-binaire":
            proc = subprocess.run([self.bin, "eval", "--format", "json", "--stdin-input", "-d",
                                   str(self.s.policy_dir / "cloudpilot.rego"), "data.cloudpilot.decision"],
                                  input=json.dumps(payload), capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                raise RuntimeError(f"OPA a échoué : {proc.stderr.strip()}")
            out = json.loads(proc.stdout)["result"][0]["expressions"][0]["value"]
        else:
            out = fallback_decision(payload)
        out["engine"] = self.mode
        return out


def _local_opa(settings: Settings) -> str | None:
    for name in ("opa.exe", "opa"):
        p = Path(settings.policy_dir).parent / "tools" / name
        if p.exists():
            return str(p)
    return None


def fallback_decision(inp: dict) -> dict:
    """Copie fidèle de policies/cloudpilot.rego (vérifiée par les tests)."""
    p, r, deps = inp["proposal"], inp["resource"], inp["impact"]["dependents"]
    destructive = p["action"] in ("delete", "stop")
    deny, approval = set(), set()
    if destructive and r["env"] == "production":
        deny.add("Interdit de supprimer ou d'arrêter une ressource de production")
    if destructive and deps:
        deny.add(f"Interdit : {len(deps)} ressource(s) dépendent de celle-ci")
    if p["action"] == "move_region" and r["data_class"] == "personal" \
            and p["params"].get("target_region") not in EU_REGIONS:
        deny.add("Interdit : des données personnelles ne peuvent pas quitter l'Union européenne")
    if p["action"] == "make_public":
        deny.add("Interdit : rendre une ressource publique doit passer par une revue de sécurité")
    if r["env"] == "production":
        approval.add("Ressource de production")
    if destructive:
        approval.add("Action destructive")
    if p["action"] == "move_region":
        approval.add("Déplacement de données")
    if deps:
        approval.add(f"{len(deps)} ressource(s) dépendante(s)")
    if p["monthly_delta_eur"] <= -300:
        approval.add("Économie ou coût supérieur à 300 €/mois")
    if r["data_class"] == "personal":
        approval.add("Données personnelles")
    return {"allow": not deny, "require_approval": bool(approval),
            "deny_reasons": sorted(deny), "approval_reasons": sorted(approval)}
