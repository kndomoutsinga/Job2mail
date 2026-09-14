"""
Script de test MANUEL qui contourne l'API Sirene (le temps qu'elle remarche)
pour vérifier que le reste du pipeline fonctionne : recherche de contact
(Hunter/Apollo/GetProspect) + génération du brouillon de mail.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import init_db, get_db, upsert_company, add_contact, add_draft
from services import email_templates, contact_finder

# --- À MODIFIER ---
COMPANY_NAME = "Capgemini"
COMPANY_DOMAIN = "capgemini.com"
# ------------------

init_db()

fake_siren = f"TEST{abs(hash(COMPANY_DOMAIN)) % 10**8}"

with get_db() as conn:
    company_id = upsert_company(conn, {
        "siren": fake_siren,
        "siret": None,
        "name": COMPANY_NAME,
        "naf_code": None,
        "naf_label": None,
        "city": None,
        "postal_code": None,
        "address": None,
        "domain": COMPANY_DOMAIN,
        "domain_confidence": "confirmed",
    })
    print(f"Entreprise inseree (id={company_id}).")

    warnings = []
    print("Recherche d'un contact (Hunter -> Apollo -> GetProspect)...")
    contact = contact_finder.find_best_contact(COMPANY_DOMAIN, warnings=warnings)

    for w in warnings:
        print(f"  [avertissement] {w}")

    if not contact:
        print("Aucun contact trouve pour ce domaine. Essaie une autre entreprise, "
              "ou verifie que HUNTER_API_KEY est bien dans .env.")
    else:
        print(f"Contact trouve : {contact.get('email')} "
              f"({contact.get('first_name') or '?'} {contact.get('last_name') or ''}) "
              f"- source: {contact.get('source')}")

        contact_id = add_contact(conn, company_id, contact)
        subject, body = email_templates.generate_email(
            COMPANY_NAME, contact_first_name=contact.get("first_name"), seed=fake_siren
        )
        add_draft(conn, company_id, contact_id, subject, body, template_used="test_manuel")
        print("Brouillon cree ! Va voir http://localhost:5000")
