"""
Client pour des API publiques et gratuites de France Travail (ex-Pôle
emploi), utilisées uniquement pour enrichir les entreprises trouvées avec
des signaux utiles à une candidature spontanée :

- "Offres d'emploi v2" (check_hiring) : l'entreprise a-t-elle des offres
  publiées en ce moment ("signal recrutement", comme le fait Jobea).
- "Synthèse des pages employeurs v1" (get_employer_page) : l'entreprise
  a-t-elle une page employeur sur France Travail, avec quels badges/labels/
  avantages — une source d'infos vraies sur l'entreprise, gratuite, sans
  scraper son site ni payer un appel IA.
- "La Bonne Boîte v2" (get_hiring_potential) : score de "potentiel
  d'embauche" (0-100, calculé par France Travail à partir de données ADS)
  pour cette entreprise précise — un signal en plus de "recrute
  actuellement" : une entreprise qui n'a pas d'offre publiée MAINTENANT
  peut quand même avoir un fort potentiel d'embauche dans les 6 prochains
  mois, ce qui reste pertinent pour une candidature spontanée.

Inscription gratuite : https://francetravail.io -> créer un compte -> "Mes
applications" -> créer une application -> l'abonner à chaque API voulue ->
récupérer l'Identifiant client et la Clé secrète (les mêmes pour toutes les
API de la même application, seul le "scope" demandé au jeton change), à
mettre dans .env (FRANCE_TRAVAIL_CLIENT_ID / FRANCE_TRAVAIL_CLIENT_SECRET).

Authentification : OAuth2 client_credentials, un jeton distinct par scope
(donc par API) — chacun valable ~25 min, gardé en mémoire et renouvelé
seulement quand il expire.

Tous les scopes ci-dessous (SCOPE, SCOPE_PAGES_EMPLOYEURS, SCOPE_LBB) sont
confirmés par une vraie capture du panneau "Security: OAuth 2.0" de la
documentation officielle de chaque API sur francetravail.io — ce ne sont
plus des suppositions. Certaines API exigent PLUSIEURS scopes à la fois
(ex : "Synthèse pages employeurs" et "La Bonne Boîte" en demandent chacune
plusieurs) : dans ce cas ils sont envoyés ensemble, séparés par un espace,
dans une seule chaîne "scope" au moment de demander le jeton.
"""
import time

import requests

import config

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"

SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
SCOPE = "api_offresdemploiv2 o2dsoffre"

PAGES_EMPLOYEURS_SEARCH_URL = (
    "https://api.francetravail.io/partenaire/synthese-pages-employeurs/v1/page-employeur/recherche"
)
# Deux scopes obligatoires, confirmés via la doc officielle.
SCOPE_PAGES_EMPLOYEURS = "pages-employeurs-synthese api_synthese-pages-employeursv1"

LBB_SEARCH_URL = "https://api.francetravail.io/partenaire/labonneboite/v2/recherche"
# Trois scopes obligatoires, confirmés via la doc officielle.
SCOPE_LBB = "search office api_labonneboitev2"


class FranceTravailError(Exception):
    pass


# Un jeton par scope (chaque API a le sien), gardé en mémoire (process
# Flask) entre les appels, pour ne pas en redemander un à chaque entreprise
# vérifiée lors d'une même recherche.
_token_cache = {}


def _get_token(scope=SCOPE):
    if not config.FRANCE_TRAVAIL_CLIENT_ID or not config.FRANCE_TRAVAIL_CLIENT_SECRET:
        raise FranceTravailError(
            "Identifiants France Travail manquants : renseignez "
            "FRANCE_TRAVAIL_CLIENT_ID et FRANCE_TRAVAIL_CLIENT_SECRET dans "
            "votre fichier .env (compte gratuit sur francetravail.io)."
        )

    now = time.time()
    cached = _token_cache.get(scope)
    if cached and now < cached["expires_at"]:
        return cached["value"]

    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": config.FRANCE_TRAVAIL_CLIENT_ID,
                "client_secret": config.FRANCE_TRAVAIL_CLIENT_SECRET,
                "scope": scope,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
    except requests.RequestException as e:
        raise FranceTravailError(f"Connexion à France Travail impossible : {e}")

    if resp.status_code != 200:
        raise FranceTravailError(
            f"Authentification France Travail refusée ({resp.status_code}) pour le "
            f"scope \"{scope}\" : {resp.text[:300]}"
        )

    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise FranceTravailError(
            "Réponse d'authentification France Travail inattendue (pas de jeton)."
        )
    expires_in = data.get("expires_in", 1499)
    # Marge de sécurité de 60s pour ne jamais utiliser un jeton tout juste expiré.
    _token_cache[scope] = {"value": token, "expires_at": now + expires_in - 60}
    return token


def check_hiring(siret):
    """
    Retourne le nombre d'offres actuellement publiées par cette entreprise
    (0 si aucune), ou None si le SIRET est vide/inconnu. Lève
    FranceTravailError en cas de souci (identifiants manquants, API en erreur...).
    """
    if not siret:
        return None

    token = _get_token()
    try:
        resp = requests.get(
            SEARCH_URL,
            params={"siret": siret, "range": "0-0"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
    except requests.RequestException as e:
        raise FranceTravailError(f"Connexion à France Travail impossible : {e}")

    # 204 = recherche valide mais aucun résultat (comportement documenté de
    # cette API pour une recherche vide, ce n'est pas une erreur).
    if resp.status_code == 204:
        return 0
    if resp.status_code not in (200, 206):
        raise FranceTravailError(
            f"Erreur API France Travail ({resp.status_code}): {resp.text[:300]}"
        )

    # Le total réel est dans l'en-tête Content-Range ("offres 0-0/<total>"),
    # plus fiable que de compter les résultats de la page (limitée à 1 ici).
    content_range = resp.headers.get("Content-Range", "")
    if "/" in content_range:
        try:
            return int(content_range.rsplit("/", 1)[-1])
        except ValueError:
            pass
    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {}
    return len(data.get("resultats", []))


def get_employer_page(siret, postal_code=None, departement_code=None):
    """
    Retourne un résumé de la page employeur France Travail de cette
    entreprise (badges/labels/avantages qu'elle met en avant), ou None si
    elle n'en a pas ou si son SIRET est inconnu. Lève FranceTravailError en
    cas de souci (identifiants manquants, API en erreur...).

    Le paramètre "where" est OBLIGATOIRE côté API (région/département/code
    postal) — on lui donne le code postal ou, à défaut, le département déjà
    connu de l'entreprise pour cibler la recherche, complété par son SIRET
    pour ne récupérer QUE cette entreprise précise et pas toutes celles du
    secteur.
    """
    if not siret:
        return None
    where = postal_code or departement_code
    if not where:
        return None  # l'API exige "where" ; sans ville/département connu, on ne peut pas chercher

    token = _get_token(scope=SCOPE_PAGES_EMPLOYEURS)
    try:
        resp = requests.post(
            PAGES_EMPLOYEURS_SEARCH_URL,
            json={"where": where, "sirets": [siret], "pageMaxSize": 1},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=20,
        )
    except requests.RequestException as e:
        raise FranceTravailError(f"Connexion à France Travail (pages employeurs) impossible : {e}")

    if resp.status_code not in (200,):
        raise FranceTravailError(
            f"Erreur API France Travail (pages employeurs) ({resp.status_code}): {resp.text[:300]}"
        )

    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {}

    results = data.get("pageEmployeurResults") or []
    if not results:
        return None

    page = (results[0] or {}).get("pageEmployeur") or {}
    return {
        "badges": page.get("badges") or [],
        "labels": page.get("labels") or [],
        "avantages": page.get("avantages") or [],
    }


def get_hiring_potential(siret, naf_code=None):
    """
    Retourne le score "La Bonne Boîte" de potentiel d'embauche de cette
    entreprise dans les 6 prochains mois : {"hiring_potential": 0-100,
    "is_high_potential": bool}, ou None si l'entreprise n'apparaît pas dans
    La Bonne Boîte (SIRET inconnu de cet outil, ou pas de potentiel calculé
    — les deux sont normaux et fréquents, ce n'est pas une erreur) ou si le
    SIRET ou le code NAF sont vides. Lève FranceTravailError en cas de souci
    (identifiants manquants, API en erreur...).

    Le paramètre `naf_code` est OBLIGATOIRE côté API en plus du SIRET : elle
    refuse une recherche par SIRET seul (erreur 422 "Vous devez préciser au
    moins un de ces éléments: job | granddomain | domain | rome | naf" —
    découvert au premier vrai appel, le 2026-09-16, avec des identifiants
    valides — donc pas un souci de scope/authentification, juste une
    contrainte de validation de la requête). On lui donne le code NAF déjà
    connu de l'entreprise (via Sirene) pour continuer à cibler précisément
    CE SIRET (le NAF seul remonterait toutes les entreprises du secteur).
    """
    if not siret or not naf_code:
        return None

    token = _get_token(scope=SCOPE_LBB)
    try:
        resp = requests.get(
            LBB_SEARCH_URL,
            params={"siret": siret, "naf": naf_code, "page": 1, "page_size": 1},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=20,
        )
    except requests.RequestException as e:
        raise FranceTravailError(f"Connexion à France Travail (La Bonne Boîte) impossible : {e}")

    if resp.status_code not in (200,):
        raise FranceTravailError(
            f"Erreur API France Travail (La Bonne Boîte) ({resp.status_code}): {resp.text[:300]}"
        )

    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {}

    results = data.get("results") or []
    if not results:
        return None

    item = results[0] or {}
    potential = item.get("hiring_potential")
    if potential is None:
        return None
    return {
        "hiring_potential": potential,
        "is_high_potential": bool(item.get("is_high_potential")),
    }
