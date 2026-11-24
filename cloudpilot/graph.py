"""Carte du parc sous forme de graphe.

Neo4jGraph est l'implémentation principale (requêtes Cypher). MemoryGraph offre les mêmes
méthodes avec NetworkX, pour lancer la démo sans serveur Neo4j.

Modèle :
  (:Cloud {name})<-[:HEBERGE_PAR]-(:Resource {id, name, type, env, region, ...})
  (:Resource)-[:DEPEND_DE]->(:Resource)
  (:Resource)-[:APPARTIENT_A]->(:Application {name})
"""
from __future__ import annotations

import json
from typing import Protocol

import networkx as nx

from .config import Settings

SCALARS = ("name", "cloud", "type", "region", "env", "state", "monthly_cost_eur", "data_class", "public", "encrypted")


class GraphStore(Protocol):
    backend: str

    def load(self, resources: list[dict]) -> None: ...
    def dependents(self, resource_id: str) -> list[dict]: ...
    def dependencies(self, resource_id: str) -> list[dict]: ...
    def edges(self) -> list[tuple[str, str]]: ...
    def stats(self) -> dict: ...
    def close(self) -> None: ...


class Neo4jGraph:
    backend = "neo4j"

    def __init__(self, uri: str, user: str, password: str):
        from neo4j import GraphDatabase

        self.driver = GraphDatabase.driver(uri, auth=(user, password) if password else None)
        self.driver.verify_connectivity()
        with self.driver.session() as s:
            s.run("CREATE CONSTRAINT resource_id IF NOT EXISTS FOR (r:Resource) REQUIRE r.id IS UNIQUE")

    def load(self, resources: list[dict]) -> None:
        rows = [{"id": r["id"], "props": {k: r.get(k) for k in SCALARS},
                 "tags": json.dumps(r.get("tags", {}), ensure_ascii=False),
                 "app": r.get("tags", {}).get("app"), "deps": r.get("depends_on", [])} for r in resources]
        with self.driver.session() as s:
            s.run("MATCH (r:Resource) WHERE NOT r.id IN $ids DETACH DELETE r", ids=[r["id"] for r in rows])
            s.run("""
                UNWIND $rows AS row
                MERGE (r:Resource {id: row.id})
                SET r += row.props, r.tags = row.tags
                MERGE (c:Cloud {name: row.props.cloud})
                MERGE (r)-[:HEBERGE_PAR]->(c)
                WITH r, row
                OPTIONAL MATCH (r)-[old:DEPEND_DE|APPARTIENT_A]->()
                DELETE old
                WITH r, row
                FOREACH (_ IN CASE WHEN row.app IS NULL THEN [] ELSE [1] END |
                    MERGE (a:Application {name: row.app}) MERGE (r)-[:APPARTIENT_A]->(a))
            """, rows=rows)
            s.run("""
                UNWIND $rows AS row
                UNWIND row.deps AS dep
                MATCH (r:Resource {id: row.id}), (d:Resource {id: dep})
                MERGE (r)-[:DEPEND_DE]->(d)
            """, rows=rows)

    def dependents(self, resource_id: str) -> list[dict]:
        """Tout ce qui casse si cette ressource disparaît (dépendances transitives)."""
        q = """MATCH (x:Resource)-[:DEPEND_DE*1..5]->(r:Resource {id: $id})
               RETURN DISTINCT x.id AS id, x.name AS name, x.env AS env ORDER BY id"""
        with self.driver.session() as s:
            return [dict(rec) for rec in s.run(q, id=resource_id)]

    def dependencies(self, resource_id: str) -> list[dict]:
        q = """MATCH (r:Resource {id: $id})-[:DEPEND_DE*1..5]->(x:Resource)
               RETURN DISTINCT x.id AS id, x.name AS name, x.env AS env ORDER BY id"""
        with self.driver.session() as s:
            return [dict(rec) for rec in s.run(q, id=resource_id)]

    def edges(self) -> list[tuple[str, str]]:
        with self.driver.session() as s:
            return [(rec["a"], rec["b"]) for rec in
                    s.run("MATCH (a:Resource)-[:DEPEND_DE]->(b:Resource) RETURN a.id AS a, b.id AS b ORDER BY a, b")]

    def stats(self) -> dict:
        with self.driver.session() as s:
            rec = s.run("""MATCH (r:Resource) WITH count(r) AS n
                           OPTIONAL MATCH (:Resource)-[d:DEPEND_DE]->() RETURN n, count(d) AS deps""").single()
            return {"ressources": rec["n"], "dependances": rec["deps"]}

    def close(self) -> None:
        self.driver.close()


class MemoryGraph:
    backend = "memoire"

    def __init__(self):
        self.g = nx.DiGraph()

    def load(self, resources: list[dict]) -> None:
        self.g.clear()
        for r in resources:
            self.g.add_node(r["id"], **{k: r.get(k) for k in SCALARS})
        for r in resources:
            for dep in r.get("depends_on", []):
                if dep in self.g:
                    self.g.add_edge(r["id"], dep)

    def _rows(self, ids) -> list[dict]:
        return [{"id": i, "name": self.g.nodes[i]["name"], "env": self.g.nodes[i]["env"]} for i in sorted(ids)]

    def dependents(self, resource_id: str) -> list[dict]:
        return self._rows(nx.ancestors(self.g, resource_id)) if resource_id in self.g else []

    def dependencies(self, resource_id: str) -> list[dict]:
        return self._rows(nx.descendants(self.g, resource_id)) if resource_id in self.g else []

    def edges(self) -> list[tuple[str, str]]:
        return sorted(self.g.edges())

    def stats(self) -> dict:
        return {"ressources": self.g.number_of_nodes(), "dependances": self.g.number_of_edges()}

    def close(self) -> None:
        pass


def open_graph(settings: Settings) -> GraphStore:
    if settings.neo4j_uri:
        return Neo4jGraph(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    return MemoryGraph()
