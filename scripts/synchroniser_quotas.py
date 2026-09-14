"""
Recale le compteur interne de Job2Mail sur les chiffres réels affichés sur
vos tableaux de bord Hunter.io (hunter.io -> Aperçu -> "Crédits"),
GetProspect (compte -> "Crédits") et Apollo.io (compte -> "Credits", en bas
à gauche du menu).

Pourquoi c'est nécessaire : Job2Mail ne peut pas lire vos comptes Hunter.io
/ GetProspect / Apollo directement, il compte seulement les appels qu'il
fait lui-même. Si vous avez utilisé ces services avant que ce suivi existe,
ou en dehors de Job2Mail (tests manuels, appel direct à l'API...), son
compteur est en retard par rapport au vrai quota. Ce script comble l'écart
en une fois.

À relancer chaque fois que vous remarquez que le chiffre affiché sur le
tableau de bord de Job2Mail ne correspond plus à celui de votre compte
Hunter.io / GetProspect / Apollo.io.

À lancer depuis PyCharm (clic droit sur ce fichier > Run) ou en terminal :
    python scripts/synchroniser_quotas.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import get_db, log_api_call, count_api_calls_this_month


def _ask_int(prompt):
    while True:
        raw = input(prompt).strip()
        if raw == "":
            return None
        if raw.isdigit():
            return int(raw)
        print("  -> entrez un nombre entier (ex: 3), ou laissez vide pour ne rien changer.")


def sync_provider(conn, provider, label, dashboard_hint):
    current = count_api_calls_this_month(conn, provider)
    print(f"\n{label} ({dashboard_hint})")
    print(f"  Job2Mail affiche actuellement : {current} utilisé(s) ce mois-ci.")
    real = _ask_int(f"  Chiffre réel sur votre tableau de bord {label} ? (Entrée pour ignorer) ")
    if real is None:
        print("  (ignoré)")
        return
    missing = real - current
    if missing <= 0:
        print(f"  Déjà à jour ({current} >= {real}) — rien à ajouter.")
        return
    for _ in range(missing):
        log_api_call(conn, provider)
    print(f"  {missing} entrée(s) ajoutée(s) — Job2Mail affiche maintenant {real}.")


def main():
    with get_db() as conn:
        sync_provider(conn, "hunter", "Hunter.io", "hunter.io -> Aperçu -> Crédits")
        sync_provider(conn, "getprospect", "GetProspect", "compte GetProspect -> Crédits")
        sync_provider(conn, "apollo", "Apollo.io", "app.apollo.io -> en bas à gauche -> Credits")
    print("\nTerminé.")


if __name__ == "__main__":
    main()
