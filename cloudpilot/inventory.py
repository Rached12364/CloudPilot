"""Connecteurs multi-cloud.

Le parc est simulé : chaque connecteur lit sa part d'un fichier d'état local, comme le
ferait un vrai connecteur avec l'API du fournisseur (boto3 pour AWS, azure-mgmt-* pour
Azure, google-cloud-* pour GCP). Remplacer un connecteur ne change rien au reste du système.
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from .config import Settings


class CloudConnector:
    cloud = ""

    def __init__(self, state_file: Path):
        self.state_file = state_file

    def list_resources(self) -> list[dict]:
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        return [copy.deepcopy(r) for r in data["resources"] if r["cloud"] == self.cloud]


class AwsConnector(CloudConnector):
    cloud = "aws"


class AzureConnector(CloudConnector):
    cloud = "azure"


class GcpConnector(CloudConnector):
    cloud = "gcp"


CONNECTORS = (AwsConnector, AzureConnector, GcpConnector)


class SimulatedCloud:
    """État du parc simulé : lecture par les connecteurs, écriture uniquement par Terraform."""

    def __init__(self, settings: Settings):
        self.s = settings
        self.s.work_dir.mkdir(parents=True, exist_ok=True)
        if not self.s.state_file.exists():
            self.reset()

    def reset(self) -> None:
        self.s.work_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.s.parc_seed, self.s.state_file)

    def discover(self) -> list[dict]:
        resources: list[dict] = []
        for cls in CONNECTORS:
            resources.extend(cls(self.s.state_file).list_resources())
        return resources

    def save(self, resources: list[dict]) -> None:
        data = json.loads(self.s.state_file.read_text(encoding="utf-8"))
        data["resources"] = resources
        tmp = self.s.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.s.state_file)
