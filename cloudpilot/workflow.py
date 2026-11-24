"""Orchestration multi-agents avec LangGraph (patron « superviseur »).

    START -> superviseur -> {inventaire, finops, securite, conformite, capacite} -> superviseur ...
          -> garde_fous (OPA) -> approbation (pause, validation humaine) -> provisioning (Terraform)
          -> reporting -> END

Le superviseur choisit l'agent suivant. L'approbation utilise `interrupt()` : le graphe
s'arrête, son état est sauvegardé (checkpoint SQLite), et il reprend quand l'ingénieur
répond, même après un redémarrage de l'application.
"""
from __future__ import annotations

import operator
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .actions import ACTION_LABELS, apply_actions
from .agents import specialists as sp
from .audit import AuditTrail
from .config import Settings
from .graph import GraphStore, open_graph
from .inventory import SimulatedCloud
from .llm import LLM
from .policy import PolicyEngine
from .terraform import Terraform

ANALYSTS = ["finops", "securite", "conformite", "capacite"]
AGENT_DESCRIPTIONS = {
    "finops": "réduit les coûts (machines surdimensionnées, ressources oubliées, arrêt la nuit)",
    "securite": "détecte les accès publics, les ports ouverts à Internet, l'absence de chiffrement",
    "conformite": "vérifie les tags obligatoires et le RGPD (données personnelles dans l'UE)",
    "capacite": "prévoit les disques qui vont se remplir",
}
PRESETS = {
    "Réduire les coûts du cloud": ["finops"],
    "Audit de sécurité et de conformité": ["securite", "conformite"],
    "Prévoir les problèmes de capacité": ["capacite"],
    "Audit complet du parc": ANALYSTS,
}
KEYWORDS = {
    "finops": ("coût", "cout", "cost", "finops", "économ", "econom", "factur", "budget", "€"),
    "securite": ("sécur", "secur", "faille", "public", "port", "chiffr", "attaque"),
    "conformite": ("conform", "rgpd", "gdpr", "tag", "règle", "regle", "audit"),
    "capacite": ("capacit", "disque", "stockage", "plein", "saturat", "prévoi", "prevoi"),
}


class State(TypedDict, total=False):
    mission: str
    plan: list[str]
    plan_source: str
    plan_reason: str
    done: list[str]
    next: str
    inventory: dict
    findings: Annotated[list, operator.add]
    proposals: Annotated[list, operator.add]
    evaluated: list
    decisions: dict
    applied: list
    terraform: dict
    report: str
    timeline: Annotated[list, operator.add]


@dataclass
class Services:
    settings: Settings
    cloud: SimulatedCloud
    graph: GraphStore
    policy: PolicyEngine
    terraform: Terraform
    audit: AuditTrail
    llm: LLM

    @classmethod
    def create(cls, settings: Settings | None = None) -> "Services":
        s = settings or Settings()
        svc = cls(s, SimulatedCloud(s), open_graph(s), PolicyEngine(s), Terraform(s),
                  AuditTrail(s.audit_file), LLM(s))
        resources = svc.cloud.discover()
        svc.graph.load(resources)
        if svc.terraform.available and not (s.tf_dir / "terraform.tfstate").exists():
            svc.terraform.sync(resources)
        return svc

    def reset(self) -> None:
        import shutil
        self.cloud.reset()
        shutil.rmtree(self.settings.tf_dir, ignore_errors=True)
        self.graph.load(self.cloud.discover())
        if self.terraform.available:
            self.terraform.sync(self.cloud.discover())
        self.audit.record("systeme", "parc_reinitialise", {"ressources": len(self.cloud.discover())})


def keyword_plan(mission: str) -> list[str]:
    m = mission.lower()
    chosen = [a for a in ANALYSTS if any(k in m for k in KEYWORDS[a])]
    if "complet" in m or "tout" in m or not chosen:
        return list(ANALYSTS)
    return chosen


def build(svc: Services, checkpointer=None):
    def supervisor(state: State) -> dict:
        if "plan" not in state:
            plan, source, reason = None, "regles", ""
            for label, agents in PRESETS.items():
                if state["mission"].strip() == label:
                    plan, source, reason = list(agents), "mission-type", f"Mission type « {label} »"
            if plan is None and svc.llm.available:
                answer = svc.llm.complete_json(
                    "Tu es le superviseur d'une équipe d'agents qui gèrent un parc multi-cloud. "
                    "Choisis les agents utiles pour la mission. Réponds en JSON : "
                    '{"agents": [...], "raison": "..."}. Agents possibles : '
                    + "; ".join(f"{k} = {v}" for k, v in AGENT_DESCRIPTIONS.items()),
                    f"Mission : {state['mission']}")
                agents = [a for a in (answer or {}).get("agents", []) if a in ANALYSTS]
                if agents:
                    plan, source = list(dict.fromkeys(agents)), "llm"
                    reason = str((answer or {}).get("raison", ""))[:300]
            if plan is None:
                plan, source = keyword_plan(state["mission"]), "regles"
                reason = "Choix par mots-clés de la mission"
            full = ["inventaire", *plan]
            svc.audit.record("superviseur", "plan_etabli", {"mission": state["mission"], "agents": full,
                                                            "source": source, "raison": reason})
            return {"plan": full, "plan_source": source, "plan_reason": reason, "done": [],
                    "next": full[0], "timeline": [f"Superviseur : plan {' → '.join(full)} ({source})"]}
        remaining = [a for a in state["plan"] if a not in state["done"]]
        return {"next": remaining[0] if remaining else "garde_fous"}

    def route(state: State) -> str:
        return state["next"]

    def inventaire(state: State) -> dict:
        resources = svc.cloud.discover()
        svc.graph.load(resources)
        res = sp.inventory(resources, svc.graph.stats())
        svc.audit.record("agent:inventaire", "inventaire", res["summary"])
        return {"inventory": res["summary"], "findings": res["findings"], "done": state["done"] + ["inventaire"],
                "timeline": [f"Inventaire : {res['summary']['total']} ressources, graphe {svc.graph.backend}"]}

    def analyst(name: str):
        def node(state: State) -> dict:
            res = sp.ANALYSTS[name](svc.cloud.discover(), svc.graph)
            svc.audit.record(f"agent:{name}", "analyse", {"constats": [f["text"] for f in res["findings"]],
                                                         "propositions": [p["id"] for p in res["proposals"]]})
            return {"findings": res["findings"], "proposals": res["proposals"], "done": state["done"] + [name],
                    "timeline": [f"{name.capitalize()} : {len(res['proposals'])} proposition(s)"]}
        node.__name__ = name
        return node

    def garde_fous(state: State) -> dict:
        by_id = {r["id"]: r for r in svc.cloud.discover()}
        evaluated, proposals = [], state.get("proposals", [])
        deleted = {p["resource_id"] for p in proposals if p["action"] == "delete"}
        merged = [p for p in proposals if p["action"] == "delete" or p["resource_id"] not in deleted]
        for p in sorted(merged, key=lambda x: sp.SEVERITY_ORDER[x["severity"]]):
            r = by_id[p["resource_id"]]
            impact = {"dependents": svc.graph.dependents(r["id"])}
            d = svc.policy.evaluate(p, r, impact)
            status = "bloquee" if not d["allow"] else ("a_valider" if d["require_approval"] else "auto")
            evaluated.append({**p, "label": ACTION_LABELS[p["action"]], "impact": impact, "policy": d, "status": status})
            svc.audit.record("opa", "decision", {"proposition": p["id"], "statut": status, "moteur": d["engine"],
                                                 "raisons": d["deny_reasons"] or d["approval_reasons"]})
        counts = {s: sum(1 for e in evaluated if e["status"] == s) for s in ("auto", "a_valider", "bloquee")}
        return {"evaluated": evaluated,
                "timeline": [f"Garde-fous OPA : {counts['auto']} automatique(s), {counts['a_valider']} à valider, "
                             f"{counts['bloquee']} bloquée(s)"]}

    def approbation(state: State) -> dict:
        pending = [e for e in state["evaluated"] if e["status"] == "a_valider"]
        if not pending:
            return {"decisions": {}}
        answer = interrupt({"type": "approbation", "propositions": pending})
        approver = answer.get("by", "ingenieur")
        decisions = {pid: bool(answer.get("decisions", {}).get(pid, False)) for pid in (e["id"] for e in pending)}
        for pid, ok in decisions.items():
            svc.audit.record(f"humain:{approver}", "approuvee" if ok else "refusee", {"proposition": pid})
        n_ok = sum(decisions.values())
        return {"decisions": decisions,
                "timeline": [f"Validation humaine ({approver}) : {n_ok} approuvée(s), {len(decisions) - n_ok} refusée(s)"]}

    def provisioning(state: State) -> dict:
        decisions = state.get("decisions", {})
        selected = [e for e in state.get("evaluated", [])
                    if e["status"] == "auto" or (e["status"] == "a_valider" and decisions.get(e["id"]))]
        if not selected:
            return {"applied": [], "terraform": {}, "timeline": ["Provisioning : aucune action à appliquer"]}
        current = svc.cloud.discover()
        desired = apply_actions(current, selected)
        plan = svc.terraform.plan(current, desired)
        svc.audit.record("agent:provisioning", "terraform_plan", {"outil": plan["tool"], "changements": plan["counts"],
                                                                 "actions": [e["id"] for e in selected]})
        result = svc.terraform.apply()
        svc.cloud.save(desired)
        svc.graph.load(desired)
        svc.audit.record("agent:provisioning", "terraform_apply", {"resultat": result})
        return {"applied": [e["id"] for e in selected], "terraform": {**plan, "result": result},
                "timeline": [f"Provisioning ({plan['tool']}) : {len(selected)} action(s) appliquée(s)"]}

    def reporting(state: State) -> dict:
        report = build_report(state, svc)
        svc.audit.record("agent:reporting", "rapport", {"longueur": len(report)})
        return {"report": report, "timeline": ["Reporting : rapport prêt"]}

    g = StateGraph(State)
    g.add_node("superviseur", supervisor)
    g.add_node("inventaire", inventaire)
    for name in ANALYSTS:
        g.add_node(name, analyst(name))
    g.add_node("garde_fous", garde_fous)
    g.add_node("approbation", approbation)
    g.add_node("provisioning", provisioning)
    g.add_node("reporting", reporting)
    g.add_edge(START, "superviseur")
    g.add_conditional_edges("superviseur", route, ["inventaire", *ANALYSTS, "garde_fous"])
    for name in ["inventaire", *ANALYSTS]:
        g.add_edge(name, "superviseur")
    g.add_edge("garde_fous", "approbation")
    g.add_edge("approbation", "provisioning")
    g.add_edge("provisioning", "reporting")
    g.add_edge("reporting", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


def sqlite_checkpointer(settings: Settings):
    from langgraph.checkpoint.sqlite import SqliteSaver

    settings.work_dir.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(settings.checkpoint_db, check_same_thread=False))


def build_report(state: State, svc: Services) -> str:
    ev = state.get("evaluated", [])
    applied = set(state.get("applied", []))
    saved = -sum(e["monthly_delta_eur"] for e in ev if e["id"] in applied and e["monthly_delta_eur"] < 0)
    potential = -sum(e["monthly_delta_eur"] for e in ev if e["monthly_delta_eur"] < 0)
    blocked = [e for e in ev if e["status"] == "bloquee"]
    refused = [e for e in ev if e["status"] == "a_valider" and e["id"] not in applied]
    lines = [f"# Rapport CloudPilot", "", f"**Mission :** {state['mission']}", "",
             f"**Agents :** {' → '.join(state.get('plan', []))} (plan : {state.get('plan_source')})", "",
             "## Chiffres clés",
             f"- Propositions : {len(ev)} · appliquées : {len(applied)} · bloquées par OPA : {len(blocked)} · "
             f"refusées ou en attente : {len(refused)}",
             f"- Économies appliquées : {sp.eur(saved)} €/mois (potentiel identifié : {sp.eur(potential)} €/mois)",
             "", "## Constats"]
    lines += [f"- [{f['agent']}] {f['text']}" for f in state.get("findings", [])]
    if applied:
        lines += ["", "## Actions appliquées"]
        lines += [f"- {e['label']} · {e['resource_name']} ({e['cloud']}) — {e['reason']}" for e in ev if e["id"] in applied]
    if blocked:
        lines += ["", "## Bloquées par les garde-fous"]
        lines += [f"- {e['label']} · {e['resource_name']} — {'; '.join(e['policy']['deny_reasons'])}" for e in blocked]
    if refused:
        lines += ["", "## Non appliquées (refusées par l'ingénieur)"]
        lines += [f"- {e['label']} · {e['resource_name']}" for e in refused]
    facts = "\n".join(lines)
    summary = svc.llm.complete(
        "Tu rédiges pour un directeur informatique. En français, 4 phrases maximum, sans inventer de chiffres : "
        "utilise uniquement ceux du rapport fourni.", facts) if svc.llm.available else None
    if summary:
        facts = facts.replace("## Chiffres clés", f"## Synthèse (rédigée par le LLM)\n{summary}\n\n## Chiffres clés", 1)
    return facts


def new_thread() -> dict:
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


__all__ = ["Services", "build", "sqlite_checkpointer", "new_thread", "Command", "PRESETS", "ANALYSTS"]
