"""
Client pour l'API GetProspect — utilisé ici comme dernier recours pour
retrouver/vérifier l'email d'une personne DÉJÀ IDENTIFIÉE par ailleurs
(via Apollo, par exemple).

Contrairement à Hunter.io ou Apollo, l'API publique de GetProspect ne
propose pas de vraie recherche "par domaine seul" — il faut déjà connaître
prénom + nom de la personne. D'où son usage en dernier maillon de la
chaîne plutôt qu'en recherche indépendante.

Inscription : https://getprospect.com -> compte gratuit -> clé API dans
les paramètres du compte.
"""
import requests

import config

BULK_ENRICH_URL = "https://api.getprospect.com/v2/people/bulk-enrich"


class GetProspectError(Exception):
    pass


def enrich_person(first_name, last_name, domain):
    """Retourne un email (str) si trouvé, sinon None."""
    if not config.GETPROSPECT_API_KEY:
        raise GetProspectError(
            "Clé API GetProspect manquante : renseignez GETPROSPECT_API_KEY dans .env"
        )
    if not first_name or not last_name:
        return None  # cet endpoint a besoin d'un nom, pas seulement d'un domaine

    headers = {"Content-Type": "application/json", "x-api-key": config.GETPROSPECT_API_KEY}
    payload = {
        "data": [
            {
                "identifier": "lookup-1",
                "first_name": first_name,
                "last_name": last_name,
                "company_domain": domain,
            }
        ],
        "enrich_email": True,
        "enrich_phone": False,
    }
    try:
        resp = requests.post(BULK_ENRICH_URL, json=payload, headers=headers, timeout=20)
    except requests.RequestException as e:
        raise GetProspectError(f"Connexion à GetProspect impossible : {e}")

    if resp.status_code in (401, 403):
        raise GetProspectError("Clé API GetProspect refusée (401/403).")
    if resp.status_code != 200:
        raise GetProspectError(f"Erreur API GetProspect ({resp.status_code}): {resp.text[:300]}")

    data = resp.json().get("data", {})
    matched = data.get("matched", [])
    if not matched:
        return None

    person = matched[0].get("person", {})
    email_info = person.get("email", {})
    if email_info.get("status") == "valid" and email_info.get("address"):
        return email_info["address"]
    return None