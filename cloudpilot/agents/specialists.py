"""Agents spécialisés.

Chaque agent lit l'état réel du parc (connecteurs + graphe Neo4j), produit des constats
chiffrés et propose des actions. Les règles d'analyse sont explicites et testées : un agent
ne peut pas « inventer » une ressource, il ne travaille que sur ce que les connecteurs
renvoient. Le LLM, quand il est disponible, sert à piloter et à rédiger, pas à calculer.
"""
from __future__ import annotations

from collections import Counter
from statistics import mean

from ..actions import smaller

REQUIRED_TAGS = ("owner", "env", "cost_center")
EU_REGIONS = {"eu-west-3", "eu-central-1", "francecentral", "westeurope", "europe-west1", "europe-west9"}
SEVERITY_ORDER = {"critique": 0, "haute": 1, "moyenne": 2, "faible": 3}


def proposal(agent: str, r: dict, action: str, reason: str, severity: str,
             delta: float = 0.0, params: dict | None = None, evidence: str = "") -> dict:
    return {"id": f"{agent}:{r['id']}:{action}", "agent": agent, "resource_id": r["id"],
            "resource_name": r["name"], "cloud": r["cloud"], "env": r["env"], "action": action,
            "params": params or {}, "monthly_delta_eur": round(delta, 2), "severity": severity,
            "reason": reason, "evidence": evidence}


def eur(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def finding(agent: str, text: str, severity: str = "faible", resource_id: str | None = None) -> dict:
    return {"agent": agent, "text": text, "severity": severity, "resource_id": resource_id}


# ---------------------------------------------------------------- Inventaire
def inventory(resources: list[dict], graph_stats: dict) -> dict:
    by_cloud = Counter(r["cloud"] for r in resources)
    by_type = Counter(r["type"] for r in resources)
    cost = sum(r.get("monthly_cost_eur", 0) for r in resources)
    summary = {"total": len(resources), "par_cloud": dict(by_cloud), "par_type": dict(by_type),
               "cout_mensuel_eur": round(cost, 2), "graphe": graph_stats}
    text = (f"{len(resources)} ressources découvertes ("
            + ", ".join(f"{n} {c.upper()}" for c, n in sorted(by_cloud.items()))
            + f"), {graph_stats.get('dependances', 0)} dépendances, coût total {eur(cost)} €/mois")
    return {"summary": summary, "findings": [finding("inventaire", text)]}


# ---------------------------------------------------------------- FinOps
def finops(resources: list[dict], graph) -> dict:
    out_f, out_p = [], []
    for r in resources:
        deps = graph.dependents(r["id"])
        cost = r.get("monthly_cost_eur", 0)
        if r["type"] == "disk" and r.get("state") == "unattached":
            out_p.append(proposal("finops", r, "delete", f"Disque attaché à aucune machine depuis {r.get('last_activity_days')} jours",
                                  "moyenne", -cost, evidence="state = unattached"))
        elif r["type"] == "storage" and r.get("last_activity_days", 0) >= 180:
            out_p.append(proposal("finops", r, "delete", f"Aucun accès depuis {r['last_activity_days']} jours",
                                  "faible", -cost, evidence=f"last_activity_days = {r['last_activity_days']}"))
        elif r["type"] == "vm" and r.get("cpu_avg_pct", 100) < 1 and r.get("last_activity_days", 0) >= 30 and not deps:
            out_p.append(proposal("finops", r, "delete", f"Machine inactive depuis {r['last_activity_days']} jours (CPU {r['cpu_avg_pct']} %)",
                                  "moyenne", -cost, evidence=f"cpu_avg_pct = {r['cpu_avg_pct']}"))
        elif r["type"] == "storage" and r.get("last_activity_days", 0) >= 180:
            out_p.append(proposal("finops", r, "delete", f"Aucun accès depuis {r['last_activity_days']} jours",
                                  "faible", -cost, evidence=f"last_activity_days = {r['last_activity_days']}"))
        elif r["type"] == "vm" and r.get("cpu_avg_pct", 100) < 10 and r.get("size") in ("large", "xlarge"):
            target = smaller(r["size"], 2 if r["cpu_avg_pct"] < 5 else 1)
            ratio = 0.25 if target == "medium" and r["size"] == "xlarge" else 0.5
            out_p.append(proposal("finops", r, "resize", f"Surdimensionnée : CPU moyen {r['cpu_avg_pct']} % sur 30 jours",
                                  "moyenne", -cost * (1 - ratio), {"target_size": target},
                                  f"{r['size']} -> {target}"))
        elif r["type"] == "vm" and r["env"] in ("dev", "staging") and not r.get("schedule") and r.get("state") == "running":
            out_p.append(proposal("finops", r, "schedule", "Environnement hors production allumé 24h/24",
                                  "faible", -cost * 0.55, {"schedule": "lun-ven 08:00-19:00"},
                                  "55 % du temps hors heures ouvrées"))
    total = sum(p["monthly_delta_eur"] for p in out_p)
    out_f.append(finding("finops", f"{len(out_p)} optimisations trouvées, économie potentielle {eur(-total)} €/mois",
                         "moyenne" if out_p else "faible"))
    return {"findings": out_f, "proposals": out_p}


# ---------------------------------------------------------------- Sécurité
def security(resources: list[dict], graph) -> dict:
    out_p = []
    for r in resources:
        if r.get("public") and r["type"] in ("storage", "database"):
            out_p.append(proposal("securite", r, "restrict_public", "Stockage ou base accessible publiquement sur Internet",
                                  "critique", evidence="public = true"))
        for port in r.get("open_ports", []):
            if port["source"] == "0.0.0.0/0" and port["port"] in (22, 3389, 3306, 5432):
                out_p.append(proposal("securite", r, "close_port", f"Port {port['port']} ouvert à tout Internet",
                                      "haute", params={"port": port["port"], "new_source": "10.0.0.0/8"},
                                      evidence=f"{port['port']} <- 0.0.0.0/0"))
        if r["type"] in ("database", "storage", "disk") and not r.get("encrypted", True):
            out_p.append(proposal("securite", r, "enable_encryption", "Données stockées sans chiffrement",
                                  "haute", evidence="encrypted = false"))
    out_f = [finding("securite", f"{len(out_p)} problèmes de sécurité détectés", "haute" if out_p else "faible")]
    return {"findings": out_f, "proposals": out_p}


# ---------------------------------------------------------------- Conformité
def compliance(resources: list[dict], graph) -> dict:
    out_p, out_f = [], []
    for r in resources:
        missing = [t for t in REQUIRED_TAGS if t not in r.get("tags", {})]
        if missing:
            guess = {"env": r["env"]}
            if "owner" in missing:
                guess["owner"] = "a-attribuer"
            if "cost_center" in missing:
                guess["cost_center"] = r.get("tags", {}).get("app", "a-attribuer")
            out_p.append(proposal("conformite", r, "add_tags", f"Tags obligatoires manquants : {', '.join(missing)}",
                                  "faible", params={"tags": {k: v for k, v in guess.items() if k in missing}}))
        if r.get("data_class") == "personal" and r["region"] not in EU_REGIONS:
            target = "eu-west-3" if r["cloud"] == "aws" else ("francecentral" if r["cloud"] == "azure" else "europe-west9")
            out_p.append(proposal("conformite", r, "move_region",
                                  f"Données personnelles hébergées hors UE ({r['region']}) : non conforme au RGPD",
                                  "critique", params={"target_region": target}, evidence=f"region = {r['region']}"))
    out_f.append(finding("conformite", f"{len(out_p)} écarts de conformité (tags, RGPD)", "moyenne" if out_p else "faible"))
    return {"findings": out_f, "proposals": out_p}


# ---------------------------------------------------------------- Capacité
def days_until_full(history: list[float], limit: float = 95.0) -> float | None:
    """Régression linéaire simple sur l'historique quotidien d'occupation du disque."""
    if len(history) < 3:
        return None
    xs = list(range(len(history)))
    mx, my = mean(xs), mean(history)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, history)) / sum((x - mx) ** 2 for x in xs)
    if slope <= 0.05:
        return None
    return max(0.0, (limit - history[-1]) / slope)


def capacity(resources: list[dict], graph) -> dict:
    out_p, out_f = [], []
    for r in resources:
        days = days_until_full(r.get("disk_used_history", []))
        if days is not None and days < 21:
            sev = "critique" if days < 7 else "haute"
            out_p.append(proposal("capacite", r, "extend_disk",
                                  f"Disque plein dans environ {days:.0f} jours (aujourd'hui {r['disk_used_history'][-1]} %)",
                                  sev, delta=round(r.get("monthly_cost_eur", 0) * 0.08, 2), params={"factor": 1.5},
                                  evidence="tendance linéaire sur 14 jours"))
    out_f.append(finding("capacite", f"{len(out_p)} ressources vont manquer d'espace sous 3 semaines",
                         "haute" if out_p else "faible"))
    return {"findings": out_f, "proposals": out_p}


ANALYSTS = {"finops": finops, "securite": security, "conformite": compliance, "capacite": capacity}
