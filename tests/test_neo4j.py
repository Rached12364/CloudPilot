"""Test d'intégration Neo4j : lancé seulement si NEO4J_URI est défini (ex. docker compose up neo4j)."""
import os

import pytest

from cloudpilot.graph import MemoryGraph, Neo4jGraph
from cloudpilot.inventory import SimulatedCloud

URI = os.environ.get("NEO4J_URI", "")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
pytestmark = pytest.mark.skipif(not URI, reason="NEO4J_URI non défini")


def test_neo4j_identique_au_graphe_memoire(settings):
    res = SimulatedCloud(settings).discover()
    neo = Neo4jGraph(URI, USER, PASSWORD)
    mem = MemoryGraph()
    neo.load(res)
    mem.load(res)
    assert neo.stats() == mem.stats()
    assert neo.edges() == mem.edges()
    for r in res:
        assert neo.dependents(r["id"]) == mem.dependents(r["id"])
    neo.load([r for r in res if r["id"] != "azure-st-93"])
    assert neo.stats()["ressources"] == len(res) - 1
    neo.close()
