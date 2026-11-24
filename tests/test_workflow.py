"""Scénario complet : superviseur -> agents -> OPA -> pause humaine -> Terraform -> rapport."""
import pytest

from cloudpilot.workflow import Command, Services, build, keyword_plan, new_thread, sqlite_checkpointer
from conftest import has


def run_until_pause(svc, mission="Audit complet du parc", checkpointer=None):
    app = build(svc, checkpointer)
    cfg = new_thread()
    return app, cfg, app.invoke({"mission": mission}, cfg)


def test_plan_par_mots_cles():
    assert keyword_plan("Réduis nos coûts AWS") == ["finops"]
    assert keyword_plan("Vérifie la sécurité et le RGPD") == ["securite", "conformite"]
    assert keyword_plan("Fais le point") == ["finops", "securite", "conformite", "capacite"]


def test_scenario_complet_avec_refus(settings):
    svc = Services.create(settings)
    app, cfg, out = run_until_pause(svc)
    assert out["plan"] == ["inventaire", "finops", "securite", "conformite", "capacite"]
    status = {e["id"]: e["status"] for e in out["evaluated"]}
    assert status["finops:azure-st-93:delete"] == "bloquee"
    assert status["securite:gcp-st-24:restrict_public"] == "auto"
    pending = out["__interrupt__"][0].value["propositions"]
    assert {e["status"] for e in pending} == {"a_valider"}

    refuse = "finops:aws-vm-90:delete"
    decisions = {e["id"]: e["id"] != refuse for e in pending}
    final = app.invoke(Command(resume={"by": "rached", "decisions": decisions}), cfg)

    ids_after = {r["id"] for r in svc.cloud.discover()}
    assert "aws-vm-90" in ids_after             # refusée par l'humain
    assert "azure-st-93" in ids_after           # bloquée par OPA
    assert "azure-disk-91" not in ids_after     # approuvée puis supprimée
    crm_us = next(r for r in svc.cloud.discover() if r["id"] == "aws-db-92")
    assert crm_us["region"] == "eu-west-3"
    assert "Rapport CloudPilot" in final["report"]
    assert svc.audit.verify()["ok"]
    events = [e["event"] for e in svc.audit.entries()]
    assert "approuvee" in events and "refusee" in events and "terraform_apply" in events


def test_reprise_apres_redemarrage(settings):
    svc = Services.create(settings)
    app, cfg, out = run_until_pause(svc, "Réduire les coûts du cloud", sqlite_checkpointer(settings))
    assert "__interrupt__" in out
    # nouvelle application, même base de checkpoints : la pause est retrouvée
    app2 = build(Services.create(settings), sqlite_checkpointer(settings))
    snap = app2.get_state(cfg)
    assert snap.next == ("approbation",)
    final = app2.invoke(Command(resume={"by": "rached", "decisions": {}}), cfg)
    assert final["report"]


def test_superviseur_llm(settings, monkeypatch):
    svc = Services.create(settings)
    svc.llm.available = True
    monkeypatch.setattr(svc.llm, "complete_json", lambda *a, **k: {"agents": ["securite", "inconnu"], "raison": "test"})
    monkeypatch.setattr(svc.llm, "complete", lambda *a, **k: "Synthèse de test.")
    _, _, out = run_until_pause(svc, "Une mission en langage libre")
    assert out["plan"] == ["inventaire", "securite"]  # l'agent inventé par le LLM est ignoré
    assert out["plan_source"] == "llm"


@pytest.mark.skipif(not (has("terraform") or has("tofu")), reason="terraform absent")
def test_terraform_plan_reel(settings):
    svc = Services.create(settings)
    assert svc.terraform.available
    app, cfg, out = run_until_pause(svc, "Réduire les coûts du cloud")
    pending = out["__interrupt__"][0].value["propositions"]
    final = app.invoke(Command(resume={"by": "t", "decisions": {e["id"]: True for e in pending}}), cfg)
    tf = final["terraform"]
    assert tf["counts"]["delete"] == 2 and "destroyed" in tf["result"]
