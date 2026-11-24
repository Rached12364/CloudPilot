"""Génère le parc multi-cloud de démonstration (données fictives, reproductibles)."""
import json
import random
from pathlib import Path

random.seed(7)

CLOUDS = {
    "aws": ["eu-west-3", "eu-central-1", "us-east-1"],
    "azure": ["francecentral", "westeurope"],
    "gcp": ["europe-west1", "europe-west9"],
}
APPS = [
    ("paie", "production", "rh", "personal"),
    ("crm", "production", "commercial", "personal"),
    ("site-web", "production", "marketing", "public"),
    ("analytics", "staging", "data", "internal"),
    ("ci", "dev", "it", "internal"),
    ("labo-ia", "dev", "rd", "internal"),
]
OWNERS = {"paie": "s.benali", "crm": "m.trabelsi", "site-web": "a.gharbi",
          "analytics": "y.mejri", "ci": "k.ayari", "labo-ia": "n.jaziri"}

resources = []


def add(r):
    resources.append(r)
    return r["id"]


def history(start, slope):
    return [round(min(100, max(1, start + slope * d + random.uniform(-0.6, 0.6))), 1) for d in range(14)]


n = 0
for app, env, cc, data_class in APPS:
    cloud = {"paie": "azure", "crm": "aws", "site-web": "gcp", "analytics": "aws",
             "ci": "azure", "labo-ia": "gcp"}[app]
    region = CLOUDS[cloud][0]
    tags = {"owner": OWNERS[app], "env": env, "cost_center": cc, "app": app}
    n += 1
    db = add({
        "id": f"{cloud}-db-{n:02d}", "name": f"{app}-db", "cloud": cloud, "type": "database",
        "region": region, "env": env, "tags": dict(tags), "monthly_cost_eur": random.choice([180, 240, 320, 410]),
        "cpu_avg_pct": round(random.uniform(18, 55), 1), "state": "running", "public": False,
        "open_ports": [], "encrypted": True, "data_class": data_class,
        "disk_used_history": history(random.uniform(40, 60), random.uniform(0.2, 0.8)), "depends_on": [],
        "last_activity_days": 0,
    })
    apps = []
    for i in range(2 if env == "production" else 1):
        n += 1
        apps.append(add({
            "id": f"{cloud}-vm-{n:02d}", "name": f"{app}-app-{i + 1}", "cloud": cloud, "type": "vm",
            "region": region, "env": env, "tags": dict(tags), "size": random.choice(["large", "xlarge"]),
            "monthly_cost_eur": random.choice([140, 190, 260]), "cpu_avg_pct": round(random.uniform(25, 70), 1),
            "state": "running", "public": False, "open_ports": [{"port": 443, "source": "10.0.0.0/8"}],
            "encrypted": True, "data_class": data_class,
            "disk_used_history": history(random.uniform(30, 55), random.uniform(0.1, 0.6)),
            "depends_on": [db], "last_activity_days": 0,
        }))
    if env == "production":
        n += 1
        add({"id": f"{cloud}-lb-{n:02d}", "name": f"{app}-lb", "cloud": cloud, "type": "load_balancer",
             "region": region, "env": env, "tags": dict(tags), "monthly_cost_eur": 35, "state": "running",
             "public": True, "open_ports": [{"port": 443, "source": "0.0.0.0/0"}], "encrypted": True,
             "data_class": "public", "depends_on": apps, "last_activity_days": 0})
    n += 1
    add({"id": f"{cloud}-st-{n:02d}", "name": f"{app}-backups", "cloud": cloud, "type": "storage",
         "region": region, "env": env, "tags": dict(tags), "monthly_cost_eur": random.choice([12, 25, 48]),
         "state": "running", "public": False, "open_ports": [], "encrypted": True, "data_class": data_class,
         "depends_on": [db], "last_activity_days": 1})


def find(name):
    return next(r for r in resources if r["name"] == name)


# --- Situations à détecter (chaque agent doit en trouver) ---
# FinOps : machines surdimensionnées, ressources oubliées, disques orphelins
find("analytics-app-1").update(cpu_avg_pct=3.2, size="xlarge", monthly_cost_eur=420)
find("crm-app-2").update(cpu_avg_pct=6.8, size="xlarge", monthly_cost_eur=380)
add({"id": "aws-vm-90", "name": "test-migration-2025", "cloud": "aws", "type": "vm", "region": "us-east-1",
     "env": "dev", "tags": {"owner": "k.ayari", "env": "dev"}, "size": "large", "monthly_cost_eur": 210,
     "cpu_avg_pct": 0.4, "state": "running", "public": False, "open_ports": [], "encrypted": True,
     "data_class": "internal", "disk_used_history": history(12, 0), "depends_on": [], "last_activity_days": 74})
add({"id": "azure-disk-91", "name": "disque-orphelin-ancien-erp", "cloud": "azure", "type": "disk",
     "region": "westeurope", "env": "dev", "tags": {"env": "dev"}, "monthly_cost_eur": 64, "state": "unattached",
     "public": False, "open_ports": [], "encrypted": False, "data_class": "internal", "depends_on": [],
     "last_activity_days": 190})
find("ci-app-1").update(cpu_avg_pct=11.5, note="tourne 24h/24 alors que l'équipe travaille 8h-18h")
# Sécurité : stockage public, port SSH ouvert à Internet, chiffrement absent
find("labo-ia-backups").update(public=True)
find("analytics-app-1")["open_ports"].append({"port": 22, "source": "0.0.0.0/0"})
find("labo-ia-db").update(encrypted=False)
# Conformité : tags manquants, données personnelles hors UE
add({"id": "aws-db-92", "name": "crm-export-us", "cloud": "aws", "type": "database", "region": "us-east-1",
     "env": "production", "tags": {"env": "production", "app": "crm"}, "monthly_cost_eur": 150,
     "cpu_avg_pct": 22.0, "state": "running", "public": False, "open_ports": [], "encrypted": True,
     "data_class": "personal", "disk_used_history": history(35, 0.3), "depends_on": [], "last_activity_days": 0})
find("crm-app-1")["depends_on"].append("aws-db-92")
# Garde-fous : vieille archive en production dont dépend encore une application (OPA doit bloquer)
add({"id": "azure-st-93", "name": "paie-archives-2019", "cloud": "azure", "type": "storage",
     "region": "francecentral", "env": "production", "tags": {"owner": "s.benali", "env": "production",
     "cost_center": "rh", "app": "paie"}, "monthly_cost_eur": 95, "state": "running", "public": False,
     "open_ports": [], "encrypted": True, "data_class": "personal", "depends_on": [], "last_activity_days": 412})
find("paie-app-1")["depends_on"].append("azure-st-93")
# Capacité : disques qui se remplissent vite
find("paie-db").update(disk_used_history=history(71, 1.6))
find("site-web-app-1").update(disk_used_history=history(80, 0.9))

out = Path(__file__).resolve().parents[1] / "data" / "parc_demo.json"
out.write_text(json.dumps({"description": "Parc multi-cloud fictif de démonstration (société « Orbis Services »)",
                           "resources": resources}, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(resources), "ressources ->", out)
