"""CloudPilot en ligne de commande.

    python cli.py                          # audit complet, validation interactive
    python cli.py "Réduis nos coûts AWS"   # mission libre
    python cli.py --reset                  # remet le parc de démo à zéro
"""
from __future__ import annotations

import sys

from cloudpilot.workflow import Command, Services, build, new_thread

ICON = {"auto": "AUTO   ", "a_valider": "VALIDER", "bloquee": "BLOQUÉE"}


def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    svc = Services.create()
    if "--reset" in sys.argv:
        svc.reset()
        print("Parc de démo réinitialisé.")
        return
    mission = " ".join(a for a in sys.argv[1:] if not a.startswith("--")) or "Audit complet du parc"
    print(f"Graphe : {svc.graph.backend} · OPA : {svc.policy.mode} · Exécution : {svc.terraform.label} · LLM : {svc.llm.label}\n")
    app, cfg = build(svc), new_thread()
    out = app.invoke({"mission": mission}, cfg)
    for step in out["timeline"]:
        print("•", step)
    print()
    for e in out.get("evaluated", []):
        why = "; ".join(e["policy"]["deny_reasons"] or e["policy"]["approval_reasons"]) or "-"
        print(f"[{ICON[e['status']]}] {e['label']} · {e['resource_name']} ({e['cloud']}) "
              f"{e['monthly_delta_eur']:+.0f} €/mois\n            {e['reason']} | OPA : {why}")
    if out.get("__interrupt__"):
        print("\n--- Validation humaine ---")
        decisions = {}
        for e in out["__interrupt__"][0].value["propositions"]:
            deps = ", ".join(d["name"] for d in e["impact"]["dependents"]) or "aucune"
            ans = input(f"Approuver « {e['label']} · {e['resource_name']} » (dépendants : {deps}) ? [o/N] ")
            decisions[e["id"]] = ans.strip().lower() in ("o", "oui", "y", "yes")
        out = app.invoke(Command(resume={"by": "cli", "decisions": decisions}), cfg)
    if out.get("terraform"):
        print(f"\n--- Plan {out['terraform']['tool']} ---\n{out['terraform']['text']}\n")
    print(out["report"])
    print(f"\nPiste d'audit : {svc.audit.verify()}")


if __name__ == "__main__":
    main()
