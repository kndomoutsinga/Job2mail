"""
Nettoyage ponctuel des candidatures en double créées AVANT la correction
anti-doublons (les recherches précédentes ne vérifiaient pas encore si une
entreprise avait déjà un brouillon, donc relancer une recherche sur une
zone qui se chevauchait recréait un brouillon pour la même entreprise).

Pour chaque entreprise, si plusieurs candidatures INITIALES existent (pas
les relances, qui sont légitimes), on garde une seule : en priorité celle
déjà envoyée/répondue, sinon la plus ancienne. Les autres sont supprimées.

À lancer UNE SEULE FOIS, depuis PyCharm (clic droit sur ce fichier > Run)
ou dans le terminal :
    python scripts/dedupliquer.py

Le fichier reste dans le projet mais n'a plus besoin d'être relancé après
ce premier passage : la correction déjà en place empêche les nouveaux
doublons d'apparaître.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import get_db

# Priorité pour choisir quel brouillon garder (0 = on garde en premier).
STATUS_PRIORITY = {"replied": 0, "sent": 1, "ready": 2, "draft": 3, "declined": 4}


def main():
    with get_db() as conn:
        rows = conn.execute(
            """SELECT d.id, d.company_id, d.status, d.created_at, c.name AS company_name
               FROM drafts d
               JOIN companies c ON c.id = d.company_id
               WHERE d.parent_draft_id IS NULL
                 AND (d.followup_number IS NULL OR d.followup_number = 0)
               ORDER BY d.company_id"""
        ).fetchall()

        by_company = {}
        for r in rows:
            by_company.setdefault(r["company_id"], []).append(r)

        to_delete = []
        details = []
        for company_id, drafts in by_company.items():
            if len(drafts) <= 1:
                continue
            drafts_sorted = sorted(
                drafts, key=lambda d: (STATUS_PRIORITY.get(d["status"], 9), d["created_at"])
            )
            keep = drafts_sorted[0]
            removed = drafts_sorted[1:]
            details.append(
                f"  - {keep['company_name']} : garde le brouillon #{keep['id']} "
                f"({keep['status']}), supprime {[d['id'] for d in removed]}"
            )
            to_delete.extend(d["id"] for d in removed)

        for draft_id in to_delete:
            conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))

    if details:
        print("Doublons nettoyés :")
        print("\n".join(details))
    print(f"\n{len(to_delete)} brouillon(s) en double supprimé(s).")


if __name__ == "__main__":
    main()
