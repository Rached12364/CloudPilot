"""Chaque agent trouve exactement les situations préparées dans le parc de démo."""
from cloudpilot.agents import specialists as sp
from cloudpilot.graph import MemoryGraph
from cloudpilot.inventory import SimulatedCloud


def _parc(settings):
    res = SimulatedCloud(settings).discover()
    g = MemoryGraph()
    g.load(res)
    return res, g


def ids(out, action):
    return sorted(p["resource_name"] for p in out["proposals"] if p["action"] == action)


def test_finops(settings):
    res, g = _parc(settings)
    out = sp.finops(res, g)
    assert ids(out, "resize") == ["analytics-app-1", "crm-app-2"]
    assert ids(out, "delete") == ["disque-orphelin-ancien-erp", "paie-archives-2019", "test-migration-2025"]
    assert ids(out, "schedule") == ["ci-app-1", "labo-ia-app-1"]
    assert all(p["monthly_delta_eur"] < 0 for p in out["proposals"])


def test_securite(settings):
    res, g = _parc(settings)
    out = sp.security(res, g)
    assert ids(out, "restrict_public") == ["labo-ia-backups"]
    assert ids(out, "close_port") == ["analytics-app-1"]
    assert ids(out, "enable_encryption") == ["disque-orphelin-ancien-erp", "labo-ia-db"]


def test_conformite(settings):
    res, g = _parc(settings)
    out = sp.compliance(res, g)
    assert ids(out, "move_region") == ["crm-export-us"]
    move = next(p for p in out["proposals"] if p["action"] == "move_region")
    assert move["params"]["target_region"] == "eu-west-3"


def test_capacite_regression():
    assert round(sp.days_until_full([50, 52, 54, 56, 58]), 1) == 18.5
    assert sp.days_until_full([40, 40, 40, 40]) is None


def test_capacite(settings):
    res, g = _parc(settings)
    assert ids(sp.capacity(res, g), "extend_disk") == ["paie-db", "site-web-app-1"]


def test_graphe_dependances(settings):
    res, g = _parc(settings)
    deps = {d["name"] for d in g.dependents("azure-st-93")}
    assert deps == {"paie-app-1", "paie-lb"}
