"""
Client pour l'API "Recherche d'entreprises" (data.gouv.fr / Etalab) —
récupération d'établissements par zone géographique et activité (code NAF).

C'est une API PUBLIQUE GRATUITE, sans clé ni compte, basée sur les mêmes
données Sirene que l'API officielle de l'INSEE : https://recherche-entreprises.api.gouv.fr

On l'utilise à la place de l'ancienne API OAuth de l'INSEE (api.insee.fr),
qui posait des soucis de connexion récurrents (coupures réseau) chez moi.
Documentation : https://recherche-entreprises.api.gouv.fr/docs/

Limite : 7 requêtes/seconde (largement suffisant ici, une recherche fait
au plus une requête par code NAF).
"""
import re

import requests

SEARCH_URL = "https://recherche-entreprises.api.gouv.fr/search"


class SireneError(Exception):
    pass


def _normalize_naf(code):
    """
    Cette API attend le format officiel avec un point ("62.01Z"), alors que
    les codes NAF sont souvent stockés/saisis sans point ("6201Z"). On
    accepte les deux formats en entrée.
    """
    if not code:
        return code
    code = code.strip().upper()
    if "." in code:
        return code
    m = re.match(r"^(\d{2})(\d{2})([A-Z])$", code)
    if m:
        return f"{m.group(1)}.{m.group(2)}{m.group(3)}"
    return code


def _extract_result(item):
    """Normalise un résultat de l'API vers le format simplifié utilisé par le reste de l'outil."""
    siege = item.get("siege") or {}

    nom = item.get("nom_complet") or item.get("denomination") or siege.get("nom_complet") or "Nom inconnu"

    naf = item.get("activite_principale") or siege.get("activite_principale")

    adresse = siege.get("adresse") or siege.get("geo_adresse")
    postal_code = siege.get("code_postal")
    city = siege.get("libelle_commune") or siege.get("commune")
    siret = siege.get("siret") or item.get("siret")

    return {
        "siren": item.get("siren"),
        "siret": siret,
        "name": str(nom).strip().title() if nom else "Nom inconnu",
        "naf_code": naf,
        "naf_label": None,
        "city": city,
        "postal_code": postal_code,
        "address": adresse,
    }


def _search_one_naf(postal_code=None, city=None, naf_code=None, company_name=None,
                     departement=None, region=None, per_page=25):
    params = {
        "etat_administratif": "A",  # établissements actifs uniquement
        "per_page": min(per_page, 25),
        "page": 1,
    }
    if naf_code:
        params["activite_principale"] = _normalize_naf(naf_code)
    if postal_code:
        params["code_postal"] = postal_code
    if departement:
        params["departement"] = departement
    if region:
        params["region"] = region

    # Recherche texte libre : l'API fait une recherche floue sur la
    # dénomination et l'adresse, donc nom d'entreprise et ville (en fallback
    # si pas de code postal) peuvent se combiner dans une seule requête "q".
    q_parts = []
    if company_name:
        q_parts.append(company_name)
    if city and not postal_code:
        q_parts.append(city)
    if q_parts:
        params["q"] = " ".join(q_parts)

    try:
        resp = requests.get(SEARCH_URL, params=params, timeout=20)
    except requests.RequestException as e:
        raise SireneError(f"Connexion à l'API Recherche d'entreprises impossible : {e}")

    if resp.status_code == 429:
        raise SireneError("Trop de requêtes envoyées à l'API Recherche d'entreprises — réessayez dans un instant.")
    if resp.status_code != 200:
        raise SireneError(f"Erreur API Recherche d'entreprises ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    return data.get("results", [])


def search_establishments(city=None, postal_code=None, company_name=None, naf_codes=None,
                           departement=None, region=None, max_results=50):
    """
    Recherche des établissements actifs. Usages combinables :
    - par ville/code postal + codes NAF, pour explorer un secteur/une zone ;
    - par département ou région (codes INSEE — voir services/geo.py pour la
      résolution nom -> code), pour couvrir toute une zone administrative
      d'un coup sans lister ses villes une à une ;
    - par company_name, pour retrouver une entreprise précise repérée par
      ailleurs (nom qui plaît, offre vue quelque part...), quel que soit
      son secteur — dans ce cas naf_codes est généralement laissé à None
      par l'appelant pour ne pas filtrer par erreur.
    Retourne une liste de dicts simplifiés, prêts pour models.upsert_company().
    """
    naf_codes = naf_codes or [None]  # None = pas de filtre NAF, une seule passe

    seen_sirets = set()
    results = []

    for naf_code in naf_codes:
        if len(results) >= max_results:
            break
        raw_items = _search_one_naf(
            postal_code=postal_code, city=city, naf_code=naf_code,
            company_name=company_name, departement=departement, region=region,
            per_page=min(max_results, 25),
        )
        for item in raw_items:
            simplified = _extract_result(item)
            key = simplified["siret"] or simplified["siren"]
            if not key or key in seen_sirets:
                continue
            seen_sirets.add(key)
            results.append(simplified)
            if len(results) >= max_results:
                break

    return results
