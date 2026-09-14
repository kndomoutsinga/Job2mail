"""
Client pour l'API Apollo.io.

Inscription : https://apollo.io -> compte -> Settings -> API Keys.

Sur mon plan gratuit :
  - search_people_by_domain() / reveal_email() ci-dessous (recherche et
    révélation de contacts) sont VERROUILLÉS : Apollo répond 403. Je les
    garde dans ce fichier au cas où je passe à un plan payant un jour, mais
    elles ne sont pas appelées par services/contact_finder.py actuellement.
  - J'ai aussi essayé une API interne non documentée
    (mixed_people/organization_top_people, visible dans le sélecteur de
    permissions de la clé API), avec plusieurs formats de paramètres en GET
    et en POST : elle renvoie systématiquement la même erreur, verrouillée
    elle aussi côté clé API seule.
  - enrich_company() (organizations/enrich) fonctionne et sert à afficher
    des infos publiques sur l'entreprise (secteur, taille, description) —
    voir app.py (route /recherche).

Si vos appels échouent avec une erreur 403/401 malgré une clé correcte,
désactivez Apollo en laissant APOLLO_API_KEY vide dans le .env, l'outil
l'ignorera simplement.
"""
import requests

import config

SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
MATCH_URL = "https://api.apollo.io/api/v1/people/match"
ENRICH_URL = "https://api.apollo.io/api/v1/organizations/enrich"


class ApolloError(Exception):
    pass


def _headers():
    return {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "x-api-key": config.APOLLO_API_KEY,
    }


def search_people_by_domain(domain, max_results=3):
    """Retourne une liste de candidats {first_name, last_name, title} pour un domaine."""
    if not config.APOLLO_API_KEY:
        raise ApolloError("Clé API Apollo manquante : renseignez APOLLO_API_KEY dans .env")

    payload = {
        "q_organization_domains_list": [domain],
        "page": 1,
        "per_page": max_results,
    }
    try:
        resp = requests.post(SEARCH_URL, json=payload, headers=_headers(), timeout=20)
    except requests.RequestException as e:
        raise ApolloError(f"Connexion à Apollo impossible : {e}")

    if resp.status_code in (401, 403):
        raise ApolloError(
            "Accès refusé par Apollo (401/403) — votre plan ne permet probablement pas "
            "l'accès API. Vous pouvez désactiver Apollo en vidant APOLLO_API_KEY dans .env."
        )
    if resp.status_code != 200:
        raise ApolloError(f"Erreur API Apollo ({resp.status_code}): {resp.text[:300]}")

    people = resp.json().get("people", [])
    candidates = []
    for p in people[:max_results]:
        candidates.append(
            {
                "first_name": p.get("first_name"),
                "last_name": p.get("last_name"),
                "title": p.get("title"),
                "has_email": p.get("has_email", False),
            }
        )
    return candidates


def reveal_email(first_name, last_name, domain):
    """Révèle l'email d'une personne déjà identifiée (consomme un crédit Apollo)."""
    if not config.APOLLO_API_KEY:
        raise ApolloError("Clé API Apollo manquante : renseignez APOLLO_API_KEY dans .env")

    payload = {
        "first_name": first_name,
        "last_name": last_name,
        "domain": domain,
        "reveal_personal_emails": True,
    }
    try:
        resp = requests.post(MATCH_URL, json=payload, headers=_headers(), timeout=20)
    except requests.RequestException as e:
        raise ApolloError(f"Connexion à Apollo impossible : {e}")

    if resp.status_code in (401, 403):
        raise ApolloError("Accès refusé par Apollo (401/403) lors de la révélation d'email.")
    if resp.status_code != 200:
        raise ApolloError(f"Erreur API Apollo ({resp.status_code}): {resp.text[:300]}")

    person = resp.json().get("person") or {}
    email = person.get("email")
    if not email or person.get("email_status") == "not_found":
        return None
    return email


def enrich_company(domain):
    """
    Récupère des infos publiques sur une entreprise à partir de son domaine
    (secteur d'activité, effectif estimé, courte description) — PAS de
    recherche de contact ici. Contrairement à search_people_by_domain() /
    reveal_email() ci-dessus, cette route fonctionne sur le plan gratuit.

    Retourne un dict {industry, employee_count, short_description} (valeurs
    éventuellement None si Apollo ne les connaît pas), ou None si
    l'entreprise n'est pas dans la base d'Apollo (404, ce n'est pas une
    erreur en soi).
    """
    if not config.APOLLO_API_KEY:
        raise ApolloError("Clé API Apollo manquante : renseignez APOLLO_API_KEY dans .env")

    try:
        resp = requests.get(
            ENRICH_URL, params={"domain": domain}, headers=_headers(), timeout=20
        )
    except requests.RequestException as e:
        raise ApolloError(f"Connexion à Apollo impossible : {e}")

    if resp.status_code in (401, 403):
        raise ApolloError(
            "Accès refusé par Apollo (401/403) lors de l'enrichissement entreprise."
        )
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise ApolloError(f"Erreur API Apollo ({resp.status_code}): {resp.text[:300]}")

    org = resp.json().get("organization") or {}
    if not org:
        return None
    return {
        "industry": org.get("industry"),
        "employee_count": org.get("estimated_num_employees"),
        "short_description": org.get("short_description"),
    }
