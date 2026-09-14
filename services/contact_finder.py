"""
Enchaîne les différentes sources de contacts pour un domaine donné.

  1. Hunter.io       — recherche directe par domaine (email + nom si dispo)
  2. GetProspect      — vérifie/complète un nom déjà identifié (voir NOTE)

La recherche de contacts d'Apollo.io (people search / email reveal) est
verrouillée sur mon plan gratuit (voir services/apollo.py pour le détail),
donc je ne l'appelle plus ici. Apollo reste utilisé ailleurs (route
/recherche dans app.py) pour la seule partie qui fonctionne :
l'enrichissement d'infos entreprise (secteur, taille, description) via
organizations/enrich.
GetProspect a besoin d'un prénom+nom déjà identifié pour fonctionner (il ne
sait pas chercher par domaine seul) — sans Apollo pour fournir ce nom, cet
étage ne se déclenche pas pour l'instant ; je le garde prêt pour le jour où
j'ajoute une autre source de noms.

Chaque étage est ignoré silencieusement si sa clé API n'est pas configurée
dans .env, et les erreurs (quota épuisé, accès refusé...) d'un étage ne
bloquent pas les suivants — elles sont juste remontées comme avertissements
à l'appelant.
"""
import config
import models
from services import hunter, getprospect


def find_best_contact(conn, domain, warnings=None):
    """
    Retourne un dict contact (ou None) : email, first_name, last_name,
    position, department, confidence, source.
    `conn` : connexion DB (sert à vérifier/enregistrer la consommation des
    quotas mensuels Hunter.io / GetProspect).
    `warnings` : liste optionnelle dans laquelle empiler les messages
    d'erreur non bloquants (pour affichage à l'utilisatrice).
    """
    if warnings is None:
        warnings = []

    # 1) Hunter.io
    if config.HUNTER_API_KEY:
        used = models.count_api_calls_this_month(conn, "hunter")
        if used >= config.HUNTER_MONTHLY_LIMIT:
            warnings.append(
                f"Hunter.io : quota mensuel atteint ({used}/{config.HUNTER_MONTHLY_LIMIT}) — "
                "recherche Hunter suspendue jusqu'au mois prochain."
            )
        else:
            try:
                models.log_api_call(conn, "hunter")
                contacts = hunter.find_contacts(domain, max_contacts=1)
                if contacts:
                    return contacts[0]
            except hunter.HunterError as e:
                warnings.append(f"Hunter.io : {e}")

    # 2) GetProspect — seulement utile si une étape précédente a donné un nom
    #    sans email (voir NOTE en tête de fichier : aujourd'hui, aucune ne le
    #    fait, cet étage est donc en attente d'une future source de noms).
    apollo_candidate = None
    if config.GETPROSPECT_API_KEY and apollo_candidate:
        used = models.count_api_calls_this_month(conn, "getprospect")
        if used >= config.GETPROSPECT_MONTHLY_LIMIT:
            warnings.append(
                f"GetProspect : quota mensuel atteint ({used}/{config.GETPROSPECT_MONTHLY_LIMIT}) — "
                "suspendu jusqu'au mois prochain."
            )
        else:
            try:
                models.log_api_call(conn, "getprospect")
                email = getprospect.enrich_person(
                    apollo_candidate["first_name"], apollo_candidate["last_name"], domain
                )
                if email:
                    return {
                        "email": email,
                        "first_name": apollo_candidate["first_name"],
                        "last_name": apollo_candidate["last_name"],
                        "position": apollo_candidate.get("title"),
                        "department": None,
                        "confidence": None,
                        "source": "getprospect",
                    }
            except getprospect.GetProspectError as e:
                warnings.append(f"GetProspect : {e}")

    return None
