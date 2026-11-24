"""Interface web de CloudPilot (Streamlit).  Lancer :  streamlit run app.py"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from cloudpilot.agents.specialists import eur
from cloudpilot.workflow import ANALYSTS, PRESETS, Command, Services, build, new_thread, sqlite_checkpointer

st.set_page_config(page_title="CloudPilot", page_icon="☁️", layout="wide")

STATUS = {"auto": ("Automatique", "🟢"), "a_valider": ("À valider", "🟠"), "bloquee": ("Bloquée par OPA", "🔴")}
SEV = {"critique": "🔴 critique", "haute": "🟠 haute", "moyenne": "🟡 moyenne", "faible": "⚪ faible"}
CLOUD_COLOR = {"aws": "#F4B183", "azure": "#9DC3E6", "gcp": "#A9D18E"}


@st.cache_resource
def services() -> tuple[Services, object]:
    svc = Services.create()
    return svc, build(svc, sqlite_checkpointer(svc.settings))


svc, app = services()
ss = st.session_state
ss.setdefault("cfg", None)
ss.setdefault("out", None)

# ------------------------------------------------------------------ barre latérale
with st.sidebar:
    st.title("☁️ CloudPilot")
    st.caption("Système multi-agents IA pour la gestion d'un parc multi-cloud")
    st.markdown("**Composants actifs**")
    st.markdown(f"- Orchestration : **LangGraph**\n"
                f"- Graphe : **{'Neo4j' if svc.graph.backend == 'neo4j' else 'en mémoire (NetworkX)'}**\n"
                f"- Garde-fous : **{ {'opa-serveur': 'OPA (serveur)', 'opa-binaire': 'OPA (binaire)'}.get(svc.policy.mode, 'règles de secours (OPA absent)') }**\n"
                f"- Exécution : **{svc.terraform.label}**\n"
                f"- LLM : **{svc.llm.label}**")
    st.divider()
    if st.button("Réinitialiser le parc de démo", width="stretch"):
        svc.reset()
        ss.cfg, ss.out = None, None
        st.rerun()
    st.caption("Parc fictif « Orbis Services » : AWS, Azure et GCP simulés.")

tab_mission, tab_parc, tab_audit, tab_archi = st.tabs(["🎯 Mission", "🗺️ Parc et graphe", "🧾 Piste d'audit", "🧩 Architecture"])

# ------------------------------------------------------------------ mission
with tab_mission:
    st.subheader("Confier une mission aux agents")
    c1, c2 = st.columns([2, 3])
    with c1:
        preset = st.radio("Mission type", list(PRESETS) + ["Mission libre"], index=3)
    with c2:
        free = st.text_area("Mission libre (comprise par le superviseur)",
                            "Trouve des économies sans toucher à la sécurité de la production",
                            disabled=preset != "Mission libre", height=110)
        approver = st.text_input("Ingénieur qui valide", "rached")
    if st.button("Lancer la mission", type="primary"):
        ss.cfg = new_thread()
        with st.spinner("Les agents analysent le parc…"):
            ss.out = app.invoke({"mission": free if preset == "Mission libre" else preset}, ss.cfg)
        st.rerun()

    out = ss.out
    if out:
        st.divider()
        st.markdown("#### Déroulement")
        for step in out.get("timeline", []):
            st.markdown(f"- {step}")
        if out.get("plan_reason"):
            st.caption(f"Raison du superviseur : {out['plan_reason']}")

        evaluated = out.get("evaluated", [])
        if evaluated:
            st.markdown("#### Propositions des agents et décision des garde-fous")
            df = pd.DataFrame([{
                "Statut": f"{STATUS[e['status']][1]} {STATUS[e['status']][0]}", "Agent": e["agent"],
                "Action": e["label"], "Ressource": f"{e['resource_name']} ({e['cloud']}, {e['env']})",
                "Gravité": SEV[e["severity"]], "€/mois": e["monthly_delta_eur"], "Pourquoi": e["reason"],
                "Règles OPA": "; ".join(e["policy"]["deny_reasons"] or e["policy"]["approval_reasons"]) or "—",
            } for e in evaluated])
            st.dataframe(df, width="stretch", hide_index=True)

        pending = out.get("__interrupt__")
        if pending:
            props = pending[0].value["propositions"]
            st.warning(f"⏸️ Le graphe est en pause : {len(props)} action(s) attendent votre validation.")
            with st.form("approval"):
                choices = {}
                for e in props:
                    deps = ", ".join(d["name"] for d in e["impact"]["dependents"]) or "aucune"
                    choices[e["id"]] = st.checkbox(
                        f"**{e['label']}** · {e['resource_name']} ({e['cloud']}, {e['env']}) · "
                        f"{e['monthly_delta_eur']:+.0f} €/mois", value=False, key=e["id"],
                        help=f"{e['reason']}\n\nDépendances (Neo4j) : {deps}\n\n"
                             f"Raisons OPA : {', '.join(e['policy']['approval_reasons'])}")
                    st.caption(f"↳ {e['reason']} · dépendants : {deps} · OPA : {', '.join(e['policy']['approval_reasons'])}")
                if st.form_submit_button("Valider mes décisions et lancer Terraform", type="primary"):
                    with st.spinner("Terraform planifie puis applique les changements…"):
                        ss.out = app.invoke(Command(resume={"by": approver or "ingenieur", "decisions": choices}), ss.cfg)
                    st.rerun()
        elif out.get("report"):
            tf = out.get("terraform") or {}
            if tf:
                st.markdown(f"#### Plan {tf['tool']}")
                c = tf["counts"]
                st.markdown(f"{c['create']} à créer · {c['update']} à modifier · {c['delete']} à supprimer — {tf.get('result', '')}")
                with st.expander("Voir le plan complet"):
                    st.code(tf["text"], language="diff")
            st.markdown(out["report"])

# ------------------------------------------------------------------ parc
with tab_parc:
    resources = svc.cloud.discover()
    cost = sum(r["monthly_cost_eur"] for r in resources)
    m = st.columns(4)
    m[0].metric("Ressources", len(resources))
    m[1].metric("Coût mensuel", f"{eur(cost)} €")
    m[2].metric("Clouds", len({r['cloud'] for r in resources}))
    m[3].metric("Dépendances (graphe)", svc.graph.stats()["dependances"])
    dot = ["digraph G {", "rankdir=LR; bgcolor=transparent; node [shape=box, style=\"rounded,filled\", fontname=Helvetica, fontsize=10];"]
    for cloud in sorted({r["cloud"] for r in resources}):
        dot.append(f'subgraph cluster_{cloud} {{ label="{cloud.upper()}"; color="#bbbbbb"; fontname=Helvetica;')
        for r in resources:
            if r["cloud"] == cloud:
                border = ', color="#c0392b", penwidth=2' if r.get("public") and r["type"] != "load_balancer" else ""
                dot.append(f'"{r["id"]}" [label="{r["name"]}\\n{r["type"]} · {r["env"]}", fillcolor="{CLOUD_COLOR[cloud]}"{border}];')
        dot.append("}")
    dot += [f'"{a}" -> "{b}";' for a, b in svc.graph.edges()]
    dot.append("}")
    st.markdown("Une flèche **A → B** signifie « A dépend de B » : supprimer B casserait A.")
    st.graphviz_chart("\n".join(dot), width="stretch")
    st.dataframe(pd.DataFrame([{
        "id": r["id"], "nom": r["name"], "cloud": r["cloud"], "type": r["type"], "région": r["region"],
        "env": r["env"], "taille": r.get("size", ""), "CPU %": r.get("cpu_avg_pct"), "€/mois": r["monthly_cost_eur"],
        "public": r.get("public"), "chiffré": r.get("encrypted"), "données": r.get("data_class"),
    } for r in resources]), width="stretch", hide_index=True)

# ------------------------------------------------------------------ audit
with tab_audit:
    check = svc.audit.verify()
    if check["ok"]:
        st.success(f"Chaîne intacte : {check['count']} événements, aucun n'a été modifié, supprimé ou inséré.")
    else:
        st.error(f"Chaîne rompue à l'événement n° {check['broken_at']} : {check['reason']}")
    entries = svc.audit.entries()[::-1]
    st.dataframe(pd.DataFrame([{"n°": e["seq"], "date (UTC)": e["at"], "acteur": e["actor"], "événement": e["event"],
                                "détails": str(e["details"])[:160], "empreinte": e["hash"][:12] + "…"} for e in entries]),
                 width="stretch", hide_index=True)

# ------------------------------------------------------------------ architecture
with tab_archi:
    st.markdown("#### Graphe LangGraph réellement compilé")
    g = app.get_graph()
    lines = ["digraph G {", "rankdir=TB; bgcolor=transparent; node [shape=box, style=\"rounded,filled\", fillcolor=\"#EEEDFE\", fontname=Helvetica];"]
    for n in g.nodes:
        if n in ("__start__", "__end__"):
            lines.append(f'"{n}" [label="{"début" if n == "__start__" else "fin"}", shape=oval, fillcolor="#eeeeee"];')
        elif n == "approbation":
            lines.append(f'"{n}" [label="approbation\\n(pause humaine)", fillcolor="#FAECE7"];')
        elif n == "garde_fous":
            lines.append(f'"{n}" [label="garde-fous\\n(OPA)", fillcolor="#FAECE7"];')
    for e in g.edges:
        lines.append(f'"{e.source}" -> "{e.target}"{" [style=dashed]" if e.conditional else ""};')
    lines.append("}")
    st.graphviz_chart("\n".join(lines))
    st.caption("Flèches en pointillés : choix du superviseur. Agents analystes : " + ", ".join(ANALYSTS) + ".")
