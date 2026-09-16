"""
Résout un nom de département ou de région (tel que tapé par l'utilisatrice,
ex : "Essonne", "Île-de-France") vers son code INSEE officiel (ex : "91",
"11"), qui est ce qu'attend le paramètre `departement`/`region` de l'API
recherche-entreprises.api.gouv.fr (voir services/sirene.py).

Si ce qui est tapé ressemble déjà à un code valide (ex : "91", "2A", "11"),
on l'utilise directement sans appeler d'API. Sinon, on interroge l'API
publique et gratuite geo.api.gouv.fr (aucune clé requise) qui fait
correspondre un nom, même partiel/mal accentué, à son code — évite de
maintenir "à la main" une liste des 101 départements et de risquer une
faute de frappe dans le code.
"""
import re

import requests

GEO_BASE_URL = "https://geo.api.gouv.fr"


class GeoError(Exception):
    pass


def _normalize_departement_code(value):
    v = value.strip().upper()
    if v in ("2A", "2B"):
        return v
    if re.match(r"^\d{1,3}$", v):
        # 1-2 chiffres -> département métropolitain (complété à 2 chiffres,
        # ex : "9" -> "09") ; 3 chiffres -> département d'outre-mer (971...).
        return v.zfill(2) if len(v) <= 2 else v
    return None


def _normalize_region_code(value):
    v = value.strip()
    if re.match(r"^\d{1,2}$", v):
        return v.zfill(2)
    return None


def _lookup(endpoint, nom):
    try:
        resp = requests.get(f"{GEO_BASE_URL}/{endpoint}", params={"nom": nom}, timeout=6)
    except requests.RequestException as e:
        raise GeoError(f"Connexion à l'API géographique (geo.api.gouv.fr) impossible : {e}")
    if resp.status_code != 200:
        raise GeoError(
            f"Erreur API géographique ({resp.status_code}) en cherchant \"{nom}\"."
        )
    return resp.json()


def resolve_departement(value):
    """
    Retourne le code département INSEE (ex : "91", "2A", "971"), ou None si
    rien ne correspond à `value` (nom introuvable). `value` vide -> None.
    Peut lever GeoError si l'API géographique est injoignable.
    """
    value = (value or "").strip()
    if not value:
        return None
    code = _normalize_departement_code(value)
    if code:
        return code
    results = _lookup("departements", value)
    return results[0]["code"] if results else None


def resolve_region(value):
    """Idem resolve_departement, mais pour une région (ex : "Île-de-France" -> "11")."""
    value = (value or "").strip()
    if not value:
        return None
    code = _normalize_region_code(value)
    if code:
        return code
    results = _lookup("regions", value)
    return results[0]["code"] if results else None
