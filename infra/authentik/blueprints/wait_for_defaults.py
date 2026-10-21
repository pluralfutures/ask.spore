# Exits 0 once Authentik has applied the three default blueprints ask-spore.yaml depends
# on (its metaapplyblueprint entries); CI polls it before applying ours (P1b-08). Run in
# the worker with `ak shell < wait_for_defaults.py`. Not a .yaml file, so
# Authentik's blueprint discovery ignores it.
from authentik.blueprints.models import BlueprintInstance

NAMES = (
    "Default - Provider authorization flow (implicit consent)",
    "Default - Provider invalidation flow",
    "System - OAuth2 Provider - Scopes",
)
found = {i.name: i.status for i in BlueprintInstance.objects.filter(name__in=NAMES)}
print("default blueprints:", found)
if any(found.get(name) != "successful" for name in NAMES):
    raise SystemExit(1)
