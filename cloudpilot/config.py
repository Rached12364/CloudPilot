"""Configuration lue depuis les variables d'environnement (aucun secret dans le code)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Settings:
    # Parc simulé (en production : connecteurs boto3 / azure-sdk / google-cloud)
    parc_seed: Path = ROOT / "data" / "parc_demo.json"
    work_dir: Path = field(default_factory=lambda: Path(_env("CLOUDPILOT_WORK_DIR", str(ROOT / "work"))))

    # Neo4j : si NEO4J_URI est vide, le graphe tourne en mémoire (NetworkX)
    neo4j_uri: str = field(default_factory=lambda: _env("NEO4J_URI"))
    neo4j_user: str = field(default_factory=lambda: _env("NEO4J_USER", "neo4j"))
    neo4j_password: str = field(default_factory=lambda: _env("NEO4J_PASSWORD"))

    # OPA : serveur REST (OPA_URL) ou binaire local (OPA_BIN / opa dans le PATH)
    opa_url: str = field(default_factory=lambda: _env("OPA_URL"))
    opa_bin: str = field(default_factory=lambda: _env("OPA_BIN"))
    policy_dir: Path = ROOT / "policies"

    # Terraform (ou OpenTofu) : binaire détecté automatiquement
    terraform_bin: str = field(default_factory=lambda: _env("TERRAFORM_BIN"))

    # LLM local (Ollama) : optionnel, le système fonctionne sans
    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "llama3.2:3b"))
    llm_enabled: bool = field(default_factory=lambda: _env("CLOUDPILOT_LLM", "auto") != "off")

    @property
    def state_file(self) -> Path:
        return self.work_dir / "parc_etat.json"

    @property
    def audit_file(self) -> Path:
        return self.work_dir / "audit.jsonl"

    @property
    def tf_dir(self) -> Path:
        return self.work_dir / "terraform"

    @property
    def checkpoint_db(self) -> Path:
        return self.work_dir / "checkpoints.sqlite"
