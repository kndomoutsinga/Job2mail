from collections import defaultdict

from flask import Flask, render_template, request, redirect, url_for, flash

import config
from models import (
    init_db, get_db, upsert_company, add_contact, add_draft,
    list_drafts, get_draft, update_draft, mark_sent, mark_replied, counts_by_status,
    list_unreplied_sent, list_followup_candidates, company_has_draft, delete_company_and_drafts,
    get_company_id_by_siren, count_api_calls_this_month, count_sent_today,
    log_api_call, update_company_enrichment,
)
from services import sirene, domain_guess, email_templates, contact_finder, apollo

app = Flask(__name__)
app.secret_key = "dev-local-only"  # app 100% locale, pas besoin d'un vrai secret

# Libellés français pour les statuts (stockés en anglais en base, affichés en
# français dans les templates via le global Jinja `status_labels`).
STATUS_LABELS = {
    "draft": "à relire",
    "ready": "prêt",
    "sent": "envoyé",
    "replied": "répondu",
    "declined": "écarté",
}
app.jinja_env.globals["status_labels"] = STATUS_LABELS

init_db()


def _quotas(conn):
    """
    État des quotas pour affichage/contrôle : envoi quotidien (sécurité
    anti-spam Gmail) + quotas mensuels des fournisseurs de contacts
    réellement configurés (clé API présente dans .env).
    """
    quotas = {
        "send": {"used": count_sent_today(conn), "limit": config.DAILY_SEND_LIMIT},
        "providers": [],
    }
    if config.HUNTER_API_KEY:
        quotas["providers"].append({
            "name": "Hunter.io",
            "used": count_api_calls_this_month(conn, "hunter"),
            "limit": config.HUNTER_MONTHLY_LIMIT,
        })
    if config.GETPROSPECT_API_KEY:
        quotas["providers"].append({
            "name": "GetProspect",
            "used": count_api_calls_this_month(conn, "getprospect"),
            "limit": config.GETPROSPECT_MONTHLY_LIMIT,
        })
    if config.APOLLO_API_KEY:
        quotas["providers"].append({
            "name": "Apollo.io (infos entreprise)",
            "used": count_api_calls_this_month(conn, "apollo"),
            "limit": config.APOLLO_MONTHLY_LIMIT,
        })
    quotas["send_reached"] = quotas["send"]["used"] >= quotas["send"]["limit"]
    return quotas


@app.route("/")
def index():
    current_status = request.args.get("statut") or None
    with get_db() as conn:
        drafts = list_drafts(conn, status=current_status)
        counts = counts_by_status(conn)
        followup_candidates = list_followup_candidates(conn, config.FOLLOWUP_DAYS)
        quotas = _quotas(conn)
    return render_template(
        "index.html", drafts=drafts, counts=counts,
        followup_candidates=followup_candidates, followup_days=config.FOLLOWUP_DAYS,
        current_status=current_status, quotas=quotas,
    )


@app.route("/verifier-reponses", methods=["POST"])
def verifier_reponses():
    from services import reply_checker

    with get_db() as conn:
        unreplied = list_unreplied_sent(conn)

        # Un seul contrôle IMAP par adresse de contact, même si plusieurs
        # brouillons (candidature + relances) partagent ce contact.
        by_contact = defaultdict(list)
        for d in unreplied:
            if d["contact_email"]:
                by_contact[d["contact_email"]].append(d)

        found = 0
        errors = []
        for contact_email, rows in by_contact.items():
            earliest_sent_at = min(r["sent_at"] for r in rows)
            try:
                result = reply_checker.check_reply(contact_email, earliest_sent_at)
            except reply_checker.ReplyCheckError as e:
                errors.append(str(e))
                break  # inutile de répéter la même erreur de connexion pour chaque contact
            if result:
                for r in rows:
                    mark_replied(conn, r["id"], result["date"], result["snippet"])
                found += 1

    if errors:
        flash(errors[0], "error")
    if found:
        flash(f"{found} réponse(s) détectée(s).", "success")
    elif not errors:
        flash("Aucune nouvelle réponse pour l'instant.", "success")
    return redirect(url_for("index"))


@app.route("/draft/<int:draft_id>/ecarter", methods=["POST"])
def ecarter_draft(draft_id):
    """Écarter rapide depuis le tableau de bord, sans ouvrir le brouillon."""
    with get_db() as conn:
        update_draft(conn, draft_id, status="declined")
    flash("Brouillon écarté.", "success")
    return redirect(url_for("index"))


@app.route("/entreprise/<int:company_id>/supprimer", methods=["POST"])
def supprimer_entreprise(company_id):
    """
    Supprime complètement une entreprise (et ses contacts/brouillons) —
    contrairement à "Écarter", rien n'est gardé en base. À utiliser pour une
    entreprise qui ne m'intéresse pas du tout.
    """
    with get_db() as conn:
        delete_company_and_drafts(conn, company_id)
    flash("Entreprise supprimée.", "success")
    return redirect(url_for("index"))


@app.route("/draft/<int:draft_id>/relancer", methods=["POST"])
def generer_relance(draft_id):
    with get_db() as conn:
        original = get_draft(conn, draft_id)
        if not original:
            flash("Brouillon introuvable.", "error")
            return redirect(url_for("index"))

        sent_date_str = original["sent_at"][:10] if original["sent_at"] else None
        subject, body = email_templates.generate_followup_email(
            original["company_name"],
            contact_first_name=original["first_name"],
            followup_number=(original["followup_number"] or 0) + 1,
            original_date=sent_date_str,
            seed=original["company_id"],
        )
        add_draft(
            conn, original["company_id"], original["contact_id"], subject, body,
            template_used="followup_auto", parent_draft_id=original["id"],
            followup_number=(original["followup_number"] or 0) + 1,
        )
    flash("Brouillon de relance créé — à relire avant envoi.", "success")
    return redirect(url_for("index"))


@app.route("/recherche", methods=["GET", "POST"])
def recherche():
    if request.method == "GET":
        return render_template(
            "recherche.html",
            default_cities=config.DEFAULT_TARGET_CITIES,
            default_naf=config.DEFAULT_NAF_CODES,
        )

    city = request.form.get("city", "").strip()
    postal_code = request.form.get("postal_code", "").strip() or None
    naf_codes = request.form.getlist("naf_codes") or config.DEFAULT_NAF_CODES
    max_results = int(request.form.get("max_results", 15))

    try:
        establishments = sirene.search_establishments(
            city=city or None, postal_code=postal_code, naf_codes=naf_codes,
            max_results=max_results,
        )
    except sirene.SireneError as e:
        flash(f"Erreur Sirene : {e}", "error")
        return redirect(url_for("recherche"))

    created = 0
    skipped_no_domain = 0
    skipped_duplicate = 0
    skipped_no_contact = 0
    provider_warnings = []

    with get_db() as conn:
        for etab in establishments:
            if not etab.get("siren") or not etab.get("name"):
                continue

            # Déjà traitée lors d'une recherche précédente (un brouillon
            # existe déjà) -> on ne refait pas le travail, pour éviter les
            # doublons et ne pas gaspiller de crédits Hunter/GetProspect.
            existing_company_id = get_company_id_by_siren(conn, etab["siren"])
            if existing_company_id and company_has_draft(conn, existing_company_id):
                skipped_duplicate += 1
                continue

            domain = domain_guess.find_live_domain(etab["name"])
            etab["domain"] = domain
            etab["domain_confidence"] = "guessed" if domain else "unknown"

            company_id = upsert_company(conn, etab)

            # Enrichissement entreprise via Apollo.io (secteur, effectif,
            # description) — bonus non bloquant : une erreur ou un quota
            # atteint ici n'empêche jamais de continuer la recherche.
            if domain and config.APOLLO_API_KEY:
                apollo_used = count_api_calls_this_month(conn, "apollo")
                if apollo_used >= config.APOLLO_MONTHLY_LIMIT:
                    provider_warnings.append(
                        f"Apollo.io : quota mensuel atteint ({apollo_used}/{config.APOLLO_MONTHLY_LIMIT}) "
                        "— enrichissement entreprise suspendu jusqu'au mois prochain."
                    )
                else:
                    try:
                        log_api_call(conn, "apollo")
                        info = apollo.enrich_company(domain)
                        if info:
                            update_company_enrichment(conn, company_id, **info)
                    except apollo.ApolloError as e:
                        provider_warnings.append(f"Apollo.io (enrichissement) : {e}")

            contact = None
            if domain:
                contact = contact_finder.find_best_contact(conn, domain, warnings=provider_warnings)

            contact_id = None
            if contact:
                contact_id = add_contact(conn, company_id, contact)

            if not domain:
                skipped_no_domain += 1
                continue  # pas de mail généré sans domaine identifié

            to_addr = contact["email"] if contact else None
            first_name = contact.get("first_name") if contact else None

            if not to_addr:
                skipped_no_contact += 1
                continue  # domaine trouvé mais aucun contact (quota atteint ou personne trouvée)

            subject, body = email_templates.generate_email(
                etab["name"], contact_first_name=first_name, seed=etab["siren"]
            )
            add_draft(conn, company_id, contact_id, subject, body, template_used="auto")
            created += 1

    msg = f"{created} brouillon(s) créé(s)."
    if skipped_no_domain:
        msg += f" {skipped_no_domain} entreprise(s) ignorée(s) (site web non identifié)."
    if skipped_no_contact:
        msg += f" {skipped_no_contact} entreprise(s) ignorée(s) (aucun contact trouvé)."
    if skipped_duplicate:
        msg += f" {skipped_duplicate} entreprise(s) déjà traitée(s) précédemment (ignorée(s))."
    flash(msg, "success")

    for w in dict.fromkeys(provider_warnings):  # dédoublonne en gardant l'ordre
        flash(w, "warning")

    return redirect(url_for("index"))


@app.route("/draft/<int:draft_id>", methods=["GET", "POST"])
def draft_detail(draft_id):
    with get_db() as conn:
        if request.method == "POST":
            action = request.form.get("action")
            if action == "save":
                update_draft(
                    conn, draft_id,
                    subject=request.form.get("subject", ""),
                    body=request.form.get("body", ""),
                )
                flash("Brouillon enregistré.", "success")
            elif action == "mark_ready":
                update_draft(conn, draft_id, status="ready")
                flash("Marqué comme prêt à l'envoi.", "success")
            elif action == "decline":
                update_draft(conn, draft_id, status="declined")
                flash("Brouillon écarté.", "success")
            elif action == "send":
                d = get_draft(conn, draft_id)
                if count_sent_today(conn) >= config.DAILY_SEND_LIMIT:
                    flash(
                        f"Quota quotidien de {config.DAILY_SEND_LIMIT} candidatures atteint "
                        "— revenez demain pour continuer (sécurité pour ne pas faire repérer "
                        "votre compte Gmail comme spam).",
                        "error",
                    )
                elif not d["contact_email"]:
                    flash("Aucune adresse email pour ce contact — impossible d'envoyer.", "error")
                else:
                    from services.mailer import send_email, MailerError

                    # Pour une relance, on rattache le mail au fil d'origine
                    # (In-Reply-To) si on a le Message-ID du mail précédent.
                    in_reply_to = None
                    if d["parent_draft_id"]:
                        parent = get_draft(conn, d["parent_draft_id"])
                        if parent and parent["message_id"]:
                            in_reply_to = parent["message_id"]

                    try:
                        message_id = send_email(
                            d["contact_email"], d["subject"], d["body"], in_reply_to=in_reply_to
                        )
                        mark_sent(conn, draft_id, message_id=message_id)
                        flash(f"Mail envoyé à {d['contact_email']}.", "success")
                    except MailerError as e:
                        flash(f"Échec de l'envoi : {e}", "error")
            return redirect(url_for("draft_detail", draft_id=draft_id))

        d = get_draft(conn, draft_id)
        quotas = _quotas(conn)
    if not d:
        flash("Brouillon introuvable.", "error")
        return redirect(url_for("index"))
    return render_template("draft.html", d=d, quotas=quotas)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
