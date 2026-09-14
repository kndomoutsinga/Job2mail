"""
Devine le nom de domaine d'une entreprise à partir de sa raison sociale,
puis vérifie s'il répond réellement (heuristique — ce n'est pas fiable à
100%, d'où le statut "guessed" à revoir manuellement dans l'interface).
"""
import re
import unicodedata
import requests

STOPWORDS = {
    "sarl", "sas", "sasu", "eurl", "sci", "sa", "société", "societe",
    "entreprise", "et", "de", "du", "la", "le", "les", "des", "groupe",
    "france", "compagnie", "cie",
}


def _slugify(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-zA-Z0-9]+", name.lower())
    words = [w for w in words if w not in STOPWORDS]
    if not words:
        return None
    return "".join(words[:3])  # limite pour éviter des slugs à rallonge


def guess_candidates(company_name):
    slug = _slugify(company_name)
    if not slug:
        return []
    return [f"{slug}.fr", f"{slug}.com"]


def find_live_domain(company_name, timeout=4):
    """
    Essaie quelques variantes de domaine et retourne la première qui répond
    (statut HTTP < 500). Retourne None si rien ne répond — dans ce cas,
    laisser le champ domaine vide et le compléter à la main est plus fiable.
    """
    for candidate in guess_candidates(company_name):
        for scheme in ("https://", "http://"):
            url = f"{scheme}{candidate}"
            try:
                resp = requests.head(url, timeout=timeout, allow_redirects=True)
                if resp.status_code < 500:
                    return candidate
            except requests.RequestException:
                continue
    return None
