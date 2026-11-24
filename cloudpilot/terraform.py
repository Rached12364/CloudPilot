"""Exécution des changements avec Terraform (ou OpenTofu, compatible).

Le parc étant simulé, chaque ressource est décrite par une ressource intégrée
`terraform_data` (aucun fournisseur à télécharger) : Terraform calcule un vrai plan
(création / modification / suppression), le garde dans un fichier, puis l'applique
seulement après validation. Avec un vrai cloud, on remplacerait `terraform_data` par
`aws_instance`, `azurerm_linux_virtual_machine`, `google_compute_instance`…
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .config import Settings

TRACKED = ("name", "cloud", "type", "region", "env", "size", "state", "schedule", "public",
           "encrypted", "open_ports", "tags", "monthly_cost_eur")


def _tf_name(rid: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", rid)


def render_config(resources: list[dict]) -> dict:
    body = {}
    for r in sorted(resources, key=lambda x: x["id"]):
        attrs = {k: r[k] for k in TRACKED if k in r}
        attrs["id"] = r["id"]
        attrs["open_ports"] = json.dumps(attrs.get("open_ports", []), sort_keys=True)
        attrs["tags"] = json.dumps(attrs.get("tags", {}), sort_keys=True, ensure_ascii=False)
        body[_tf_name(r["id"])] = {"input": attrs}
    return {"terraform": {"required_version": ">= 1.4"}, "resource": {"terraform_data": body}}


class Terraform:
    def __init__(self, settings: Settings):
        self.s = settings
        self.dir: Path = settings.tf_dir
        self.bin = settings.terraform_bin or shutil.which("terraform") or shutil.which("tofu")
        self.available = bool(self.bin)

    @property
    def label(self) -> str:
        if not self.available:
            return "absent (plan calculé par CloudPilot)"
        return "OpenTofu" if Path(self.bin).name.startswith("tofu") else "Terraform"

    def _run(self, *args: str) -> str:
        env = {**os.environ, "TF_IN_AUTOMATION": "1", "TF_INPUT": "0", "CHECKPOINT_DISABLE": "1"}
        proc = subprocess.run([self.bin, *args, "-no-color"], cwd=self.dir, capture_output=True,
                              text=True, timeout=300, env=env)
        if proc.returncode not in (0, 2):
            raise RuntimeError(f"{self.label} {' '.join(args)} a échoué :\n{proc.stderr or proc.stdout}")
        return proc.stdout

    def _write(self, resources: list[dict]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "main.tf.json").write_text(json.dumps(render_config(resources), indent=2, ensure_ascii=False),
                                              encoding="utf-8")

    def sync(self, resources: list[dict]) -> None:
        """Aligne l'état Terraform sur le parc actuel (au premier lancement)."""
        if not self.available:
            return
        self._write(resources)
        if not (self.dir / ".terraform").exists() and not (self.dir / ".terraform.lock.hcl").exists():
            self._run("init")
        self._run("apply", "-auto-approve")

    def plan(self, current: list[dict], desired: list[dict]) -> dict:
        summary = diff_summary(current, desired)
        if not self.available:
            return {"tool": self.label, "text": summary["text"], "counts": summary["counts"]}
        self._write(desired)
        text = self._run("plan", "-out=plan.bin")
        shown = json.loads(self._run("show", "-json", "plan.bin"))
        counts = {"create": 0, "update": 0, "delete": 0}
        for rc in shown.get("resource_changes", []):
            acts = rc["change"]["actions"]
            if acts == ["create"]:
                counts["create"] += 1
            elif acts == ["update"]:
                counts["update"] += 1
            elif "delete" in acts:
                counts["delete"] += 1
        return {"tool": self.label, "text": _trim_plan(text), "counts": counts}

    def apply(self) -> str:
        if not self.available:
            return "Terraform absent : l'état simulé a été mis à jour directement."
        out = self._run("apply", "plan.bin")
        return out.strip().splitlines()[-1] if out.strip() else "Apply terminé."


def _trim_plan(text: str) -> str:
    start = text.find("Terraform will perform") if "Terraform will perform" in text else text.find("OpenTofu will perform")
    return text[start:].strip() if start >= 0 else text.strip()


def diff_summary(current: list[dict], desired: list[dict]) -> dict:
    cur, des = {r["id"]: r for r in current}, {r["id"]: r for r in desired}
    lines, counts = [], {"create": 0, "update": 0, "delete": 0}
    for rid in sorted(cur.keys() - des.keys()):
        counts["delete"] += 1
        lines.append(f"  - {rid} sera supprimée")
    for rid in sorted(des.keys() & cur.keys()):
        changed = [k for k in TRACKED if cur[rid].get(k) != des[rid].get(k)]
        if changed:
            counts["update"] += 1
            lines.append(f"  ~ {rid} : " + ", ".join(f"{k} {cur[rid].get(k)!r} -> {des[rid].get(k)!r}" for k in changed))
    lines.append(f"\nPlan : {counts['create']} à créer, {counts['update']} à modifier, {counts['delete']} à supprimer.")
    return {"text": "\n".join(lines), "counts": counts}
