"""
Script de DIAGNOSTIC (temporaire) pour explorer deux API Apollo que ton
compte gratuit autorise, mais qui ne sont pas documentées officiellement
par Apollo (organization_top_people) — donc on ne connaît pas encore le
format exact de leur réponse.

Il fait deux appels avec ta vraie clé Apollo (lue depuis .env, jamais
affichée ici) sur un domaine de test (Capgemini, déjà utilisé comme test
dans le projet), et affiche tout ce que Apollo répond. Aucune donnée
sensible n'est affichée à part des infos publiques sur l'entreprise/ses
dirigeants.

À lancer depuis PyCharm (clic droit > Run) ou terminal :
    python scripts/test_apollo_top_people.py

Une fois qu'on aura vu le résultat, ce script sera remplacé par du vrai
code dans services/apollo.py — il ne sert que le temps du diagnostic.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import config

TEST_DOMAIN = "capgemini.com"


def _headers():
    return {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "x-api-key": config.APOLLO_API_KEY,
    }


def _print_response(label, resp):
    print(f"\n--- {label} ---")
    print(f"Status: {resp.status_code}")
    try:
        print(json.dumps(resp.json(), indent=2, ensure_ascii=False)[:3000])
    except ValueError:
        print(resp.text[:1000])


def main():
    if not config.APOLLO_API_KEY:
        print("APOLLO_API_KEY est vide dans .env — rien à tester.")
        return

    # 1) organizations/enrich : domaine -> infos entreprise + organization_id
    resp = requests.get(
        "https://api.apollo.io/api/v1/organizations/enrich",
        params={"domain": TEST_DOMAIN},
        headers=_headers(),
        timeout=20,
    )
    _print_response("organizations/enrich", resp)

    org_id = None
    if resp.status_code == 200:
        org = resp.json().get("organization") or {}
        org_id = org.get("id")
        print(f"\n=> organization_id trouvé : {org_id}")

    if not org_id:
        print("\nPas d'organization_id récupéré, on ne peut pas tester l'étape suivante.")
        return

    # 2) organization_top_people : essais précédents (4x) avec organization_id
    #    en query GET ont tous renvoyé la même erreur 422 "total_entries for
    #    nil" — signe que la route existe mais que les paramètres essayés ne
    #    sont pas les bons. Dernière hypothèse avant de conclure : cette API
    #    interne utilise peut-être le même format que la vraie recherche
    #    documentée (mixed_people/api_search), qui accepte des domaines
    #    directement (q_organization_domains_list) et se fait en POST avec
    #    un corps JSON plutôt qu'en paramètres d'URL.
    url = "https://api.apollo.io/api/v1/mixed_people/organization_top_people"
    attempts = [
        ("POST-JSON", {"q_organization_domains_list": [TEST_DOMAIN], "page": 1, "per_page": 10}),
        ("POST-JSON", {"organization_ids": [org_id], "page": 1, "per_page": 10}),
        ("POST-JSON", {"q_organization_ids": [org_id], "page": 1, "per_page": 10}),
        ("GET", [("q_organization_domains_list[]", TEST_DOMAIN), ("page", 1), ("per_page", 10)]),
    ]
    for i, (method, payload) in enumerate(attempts, start=1):
        try:
            if method == "POST-JSON":
                resp = requests.post(url, json=payload, headers=_headers(), timeout=20)
            else:
                resp = requests.get(url, params=payload, headers=_headers(), timeout=20)
        except requests.RequestException as e:
            print(f"\n--- essai {i} : {method} {url} payload={payload} ---")
            print(f"Erreur de connexion : {e}")
            continue
        _print_response(f"essai {i} : {method} {url} payload={payload}", resp)
        if resp.status_code == 200:
            print("\n>>> SUCCÈS ! On a trouvé le bon format.")
            break

    print("\nTerminé — copie-colle tout ce qui s'affiche ci-dessus dans le chat.")


if __name__ == "__main__":
    main()
