"""Les garde-fous : OPA réel quand il est installé, et le moteur de secours doit donner exactement la même chose."""
import itertools
import subprocess

import pytest

from cloudpilot.policy import PolicyEngine, fallback_decision
from conftest import ROOT, has

ACTIONS = ["delete", "stop", "resize", "schedule", "move_region", "make_public", "add_tags"]
CASES = [
    {"proposal": {"action": a, "monthly_delta_eur": delta, "params": {"target_region": reg}},
     "resource": {"id": "x", "env": env, "data_class": dc, "type": "vm", "region": "us-east-1"},
     "impact": {"dependents": [{"id": "d"}] * n}}
    for a, env, dc, n, delta, reg in itertools.product(
        ACTIONS, ["production", "dev"], ["personal", "internal"], [0, 2], [0, -400], ["eu-west-3", "us-east-1"])
]


@pytest.mark.skipif(not has("opa"), reason="binaire opa absent")
def test_tests_rego():
    out = subprocess.run(["opa", "test", str(ROOT / "policies")], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


@pytest.mark.skipif(not has("opa"), reason="binaire opa absent")
def test_secours_identique_a_opa(settings):
    engine = PolicyEngine(settings)
    assert engine.mode == "opa-binaire"
    for case in CASES[::3]:
        opa = engine.evaluate(case["proposal"], case["resource"], case["impact"])
        opa.pop("engine")
        assert opa == fallback_decision(case), case


def test_regles_principales():
    prod_delete = CASES[0]
    assert not fallback_decision(prod_delete)["allow"]
    personal_us = {"proposal": {"action": "move_region", "monthly_delta_eur": 0, "params": {"target_region": "us-east-1"}},
                   "resource": {"env": "production", "data_class": "personal"}, "impact": {"dependents": []}}
    assert "Union européenne" in fallback_decision(personal_us)["deny_reasons"][0]
