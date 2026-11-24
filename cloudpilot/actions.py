"""Effet de chaque type d'action sur l'état désiré du parc.

Les agents proposent, ce module calcule l'état cible, et Terraform applique la différence.
"""
from __future__ import annotations

import copy

SIZES = ["small", "medium", "large", "xlarge"]

ACTION_LABELS = {
    "resize": "Réduire la taille",
    "delete": "Supprimer",
    "stop": "Arrêter",
    "schedule": "Arrêt automatique la nuit et le week-end",
    "restrict_public": "Retirer l'accès public",
    "close_port": "Fermer un port ouvert à Internet",
    "enable_encryption": "Activer le chiffrement",
    "add_tags": "Compléter les tags",
    "move_region": "Déplacer vers une autre région",
    "extend_disk": "Agrandir le disque",
    "make_public": "Rendre public",
}


def smaller(size: str | None, steps: int = 1) -> str:
    i = SIZES.index(size) if size in SIZES else 2
    return SIZES[max(0, i - steps)]


def apply_actions(resources: list[dict], proposals: list[dict]) -> list[dict]:
    out = {r["id"]: copy.deepcopy(r) for r in resources}
    for p in proposals:
        rid, a, params = p["resource_id"], p["action"], p.get("params", {})
        if rid not in out:
            continue
        r = out[rid]
        if a in ("delete",):
            del out[rid]
            for other in out.values():
                other["depends_on"] = [d for d in other.get("depends_on", []) if d != rid]
            continue
        if a == "stop":
            r["state"] = "stopped"
        elif a == "resize":
            r["size"] = params.get("target_size", smaller(r.get("size")))
        elif a == "schedule":
            r["schedule"] = params.get("schedule", "lun-ven 08:00-19:00")
        elif a == "restrict_public":
            r["public"] = False
        elif a == "close_port":
            port = params.get("port")
            r["open_ports"] = [x if not (x["port"] == port and x["source"] == "0.0.0.0/0")
                               else {"port": port, "source": params.get("new_source", "10.0.0.0/8")}
                               for x in r.get("open_ports", [])]
        elif a == "enable_encryption":
            r["encrypted"] = True
        elif a == "add_tags":
            r["tags"] = {**r.get("tags", {}), **params.get("tags", {})}
        elif a == "move_region":
            r["region"] = params["target_region"]
        elif a == "extend_disk":
            factor = params.get("factor", 1.5)
            r["disk_used_history"] = [round(v / factor, 1) for v in r.get("disk_used_history", [])]
        r["monthly_cost_eur"] = round(max(0, r.get("monthly_cost_eur", 0) + p.get("monthly_delta_eur", 0)), 2)
    return list(out.values())
