import json

from cloudpilot.audit import AuditTrail


def test_chaine_et_falsification(tmp_path):
    a = AuditTrail(tmp_path / "audit.jsonl")
    for i in range(5):
        a.record("agent:test", "evenement", {"i": i})
    assert a.verify() == {"ok": True, "count": 5}
    lines = a.path.read_text(encoding="utf-8").splitlines()

    tampered = json.loads(lines[2]); tampered["details"]["i"] = 99
    a.path.write_text("\n".join(lines[:2] + [json.dumps(tampered)] + lines[3:]) + "\n", encoding="utf-8")
    assert a.verify() == {"ok": False, "broken_at": 3, "reason": "contenu modifié après coup"}

    a.path.write_text("\n".join(lines[:2] + lines[3:]) + "\n", encoding="utf-8")
    assert a.verify()["broken_at"] == 3
