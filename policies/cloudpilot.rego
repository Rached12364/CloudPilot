# Garde-fous de CloudPilot (Open Policy Agent)
#
# Entrée : une proposition d'un agent, la ressource visée et l'impact calculé dans Neo4j.
# Sortie : { allow, require_approval, deny_reasons, approval_reasons }
#   - allow = false            -> l'action est bloquée, aucun humain ne peut la forcer
#   - require_approval = true  -> l'action attend la validation d'un ingénieur
#   - sinon                    -> l'action peut être appliquée automatiquement
package cloudpilot

import rego.v1

default allow := false

default require_approval := false

allow if count(deny_reasons) == 0

require_approval if count(approval_reasons) > 0

eu_regions := {"eu-west-3", "eu-central-1", "francecentral", "westeurope", "europe-west1", "europe-west9"}

destructive := {"delete", "stop"}

# ---------- Interdictions absolues ----------

deny_reasons contains "Interdit de supprimer ou d'arrêter une ressource de production" if {
	input.proposal.action in destructive
	input.resource.env == "production"
}

deny_reasons contains msg if {
	input.proposal.action in destructive
	count(input.impact.dependents) > 0
	msg := sprintf("Interdit : %d ressource(s) dépendent de celle-ci", [count(input.impact.dependents)])
}

deny_reasons contains "Interdit : des données personnelles ne peuvent pas quitter l'Union européenne" if {
	input.proposal.action == "move_region"
	input.resource.data_class == "personal"
	not input.proposal.params.target_region in eu_regions
}

deny_reasons contains "Interdit : rendre une ressource publique doit passer par une revue de sécurité" if {
	input.proposal.action == "make_public"
}

# ---------- Validation humaine obligatoire ----------

approval_reasons contains "Ressource de production" if input.resource.env == "production"

approval_reasons contains "Action destructive" if input.proposal.action in destructive

approval_reasons contains "Déplacement de données" if input.proposal.action == "move_region"

approval_reasons contains msg if {
	count(input.impact.dependents) > 0
	msg := sprintf("%d ressource(s) dépendante(s)", [count(input.impact.dependents)])
}

approval_reasons contains "Économie ou coût supérieur à 300 €/mois" if input.proposal.monthly_delta_eur <= -300

approval_reasons contains "Données personnelles" if input.resource.data_class == "personal"

decision := {
	"allow": allow,
	"require_approval": require_approval,
	"deny_reasons": sort(deny_reasons),
	"approval_reasons": sort(approval_reasons),
}
