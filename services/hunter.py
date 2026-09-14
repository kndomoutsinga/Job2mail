"""
Client pour l'API Hunter.io — recherche de contacts/emails pour un domaine
d'entreprise.

Inscription : https://hunter.io -> compte gratuit -> clé API sur
https://hunter.io/api-keys

Plan gratuit : un pool mensuel de crédits partagé entre "Domain Search",
"Email Finder" et "Email Verifier" (vérifiez le nombre exact sur votre
tableau de bord, il évolue selon les offres). Chaque recherche de domaine
consomme un crédit — d'où l'intérêt de ne l'utiliser qu'une fois le domaine
de l'entreprise confirmé.
"""
import requests

import config

DOMAIN_SEARCH_URL = "https://api.hunter.io/v2/domain-search"


class HunterError(Exception):
    pass


def find_contacts(domain, max_contacts=3):
    """
    Retourne une liste de contacts probables pour un domaine, triés par
    "confidence" décroissante. Chaque contact : email, first_name,
    last_name, position, department, confidence.
    """
    if not config.HUNTER_API_KEY:
        raise HunterError(
            "Clé API Hunter.io manquante : renseignez HUNTER_API_KEY dans votre fichier .env"
        )

    params = {"domain": domain, "api_key": config.HUNTER_API_KEY, "limit": max_contacts}
    try:
        resp = requests.get(DOMAIN_SEARCH_URL, params=params, timeout=15)
    except requests.RequestException as e:
        raise HunterError(f"Connexion à Hunter.io impossible : {e}")

    if resp.status_code == 401:
        raise HunterError("Clé API Hunter.io invalide.")
    if resp.status_code == 429:
        raise HunterError("Quota Hunter.io atteint pour ce mois — réessayez plus tard.")
    if resp.status_code != 200:
        raise HunterError(f"Erreur API Hunter.io ({resp.status_code}): {resp.text[:300]}")

    data = resp.json().get("data", {})
    emails = data.get("emails", [])

    # Priorité aux départements RH / direction / management, sinon on garde
    # les mieux notés tels quels.
    priority_depts = {"hr", "management", "executive"}
    emails.sort(
        key=lambda e: (
            0 if (e.get("department") or "").lower() in priority_depts else 1,
            -(e.get("confidence") or 0),
        )
    )

    contacts = []
    for e in emails[:max_contacts]:
        contacts.append(
            {
                "email": e.get("value"),
                "first_name": e.get("first_name"),
                "last_name": e.get("last_name"),
                "position": e.get("position"),
                "department": e.get("department"),
                "confidence": e.get("confidence"),
                "source": "hunter",
            }
        )

    # Repli : pas de contact nommé mais un pattern générique connu pour le domaine
    if not contacts and data.get("pattern"):
        generic = _apply_pattern(data["pattern"], domain, "contact")
        if generic:
            contacts.append(
                {
                    "email": generic,
                    "first_name": None,
                    "last_name": None,
                    "position": None,
                    "department": None,
                    "confidence": None,
                    "source": "generic_pattern",
                }
            )
    return contacts


def _apply_pattern(pattern, domain, fallback_local_part):
    # Les patterns Hunter type "{first}.{last}" nécessitent un nom réel ;
    # sans contact nommé on retombe sur une adresse générique plausible.
    generic_candidates = ["contact", "recrutement", "rh", "contact@" + domain]
    for candidate in generic_candidates:
        if "@" in candidate:
            return candidate
    return f"{fallback_local_part}@{domain}"