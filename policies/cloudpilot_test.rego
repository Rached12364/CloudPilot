package cloudpilot_test

import data.cloudpilot
import rego.v1

dev_vm := {"env": "dev", "data_class": "internal"}

prod_db := {"env": "production", "data_class": "personal"}

no_impact := {"dependents": []}

test_resize_dev_sans_dependance_est_automatique if {
	d := cloudpilot.decision with input as {
		"proposal": {"action": "resize", "monthly_delta_eur": -105, "params": {}},
		"resource": dev_vm, "impact": no_impact,
	}
	d.allow
	not d.require_approval
}

test_suppression_en_production_interdite if {
	d := cloudpilot.decision with input as {
		"proposal": {"action": "delete", "monthly_delta_eur": -150, "params": {}},
		"resource": prod_db, "impact": no_impact,
	}
	not d.allow
}

test_suppression_avec_dependances_interdite if {
	d := cloudpilot.decision with input as {
		"proposal": {"action": "delete", "monthly_delta_eur": -50, "params": {}},
		"resource": dev_vm, "impact": {"dependents": [{"id": "x"}]},
	}
	not d.allow
}

test_donnees_personnelles_hors_ue_interdites if {
	d := cloudpilot.decision with input as {
		"proposal": {"action": "move_region", "monthly_delta_eur": 0, "params": {"target_region": "us-east-1"}},
		"resource": prod_db, "impact": no_impact,
	}
	not d.allow
}

test_rapatriement_ue_demande_validation if {
	d := cloudpilot.decision with input as {
		"proposal": {"action": "move_region", "monthly_delta_eur": 0, "params": {"target_region": "eu-west-3"}},
		"resource": prod_db, "impact": no_impact,
	}
	d.allow
	d.require_approval
}

test_suppression_dev_isolee_demande_validation if {
	d := cloudpilot.decision with input as {
		"proposal": {"action": "delete", "monthly_delta_eur": -210, "params": {}},
		"resource": dev_vm, "impact": no_impact,
	}
	d.allow
	d.require_approval
}
