import json
import os
from collections import defaultdict

from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename

import config
from models import (
    init_db, get_db, upsert_company, add_contact, add_draft,
    list_drafts, get_draft, update_draft, mark_sent, mark_replied, counts_by_status,
    list_unreplied_sent, list_followup_candidates, delete_company_and_drafts,
    get_company_id_by_siren, count_api_calls_this_month, count_sent_today,
    log_api_call, update_company_enrichment, update_company_hiring_signal,
    update_company_employer_page, update_company_hiring_potential,
    get_contact_by_domain, get_draft_by_contact_email, add_merged_site,
)
from services import sirene, domain_guess, email_templates, contact_finder, apollo, geo, france_travail

app = Flask(__name__)
app.secret_key = "dev-local-only"  # app 100% locale, pas besoin d'un vrai secret

# Limite globale de taille de requête = ce qui protège contre une pièce
# jointe trop lourde (voir _too_large ci-dessous) ; marge de 2 Mo pour le
# reste du formulaire (objet/message) en plus du fichier lui-même.
app.config["MAX_CONTENT_LENGTH"] = (config.MAX_ATTACHMENT_SIZE_MB + 2) * 1024 * 1024

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


def _fromjson_filter(value):
    """Filtre Jinja pour relire une liste stockée en JSON (badges/labels/
    avantages de la page employeur France Travail) — liste vide si absent
    ou invalide plutôt que de faire planter le rendu de la page."""
    if not value:
        return []
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return []


app.jinja_env.filters["fromjson"] = _fromjson_filter


def _merged_cities_filter(d):
    """Filtre Jinja : ville principale du brouillon + villes des sites
    fusionnés dessus (même contact, voir add_merged_site dans models.py),
    réunies en une seule liste sans doublon — pour n'afficher qu'UNE ligne
    par contact sur le tableau de bord au lieu d'une par site."""
    cities = [d["city"]] if d["city"] else []
    for site in _fromjson_filter(d["merged_sites"]):
        c = site.get("city")
        if c and c not in cities:
            cities.append(c)
    return ", ".join(cities) if cities else "—"


app.jinja_env.filters["merged_cities"] = _merged_cities_filter

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


@app.errorhandler(413)
def _fichier_trop_lourd(e):
    flash(
        f"Fichier trop volumineux (max {config.MAX_ATTACHMENT_SIZE_MB} Mo) — "
        "pièce jointe ignorée.",
        "error",
    )
    return redirect(request.referrer or url_for("index"))


def _delete_attachment_file(filename):
    if not filename:
        return
    path = os.path.join(config.ATTACHMENTS_DIR, filename)
    if os.path.exists(path):
        os.remove(path)


# Nombre de candidatures affichées par page du tableau de bord — au-delà,
# tout charger d'un coup ralentirait la page pour rien (voir pagination
# ci-dessous, ajoutée le 2026-09-16 en prévision d'une recherche active sur
# plusieurs mois).
DASHBOARD_PAGE_SIZE = 25


@app.route("/")
def index():
    current_status = request.args.get("statut") or None
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1

    with get_db() as conn:
        counts = counts_by_status(conn)
        total_for_filter = counts.get(current_status, 0) if current_status else sum(counts.values())
        total_pages = max(1, -(-total_for_filter // DASHBOARD_PAGE_SIZE))  # ceil sans importer math
        page = min(page, total_pages)  # évite une page vide si on filtre puis qu'on revient en arrière

        drafts = list_drafts(conn, status=current_status, page=page, page_size=DASHBOARD_PAGE_SIZE)
        followup_candidates = list_followup_candidates(conn, config.FOLLOWUP_DAYS)
        quotas = _quotas(conn)
    return render_template(
        "index.html", drafts=drafts, counts=counts,
        followup_candidates=followup_candidates, followup_days=config.FOLLOWUP_DAYS,
        current_status=current_status, quotas=quotas,
        page=page, total_pages=total_pages,
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
        # Nettoie les pièces jointes de tous les brouillons de cette
        # entreprise avant de supprimer les lignes en base, sinon les
        # fichiers restent orphelins sur le disque (delete_company_and_drafts
        # ne connaît que la DB, pas data/attachments/).
        for row in conn.execute(
            "SELECT attachment_filename FROM drafts WHERE company_id = ?", (company_id,)
        ).fetchall():
            _delete_attachment_file(row["attachment_filename"])
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

    city_raw = request.form.get("city", "").strip()
    postal_code = request.form.get("postal_code", "").strip() or None
    company_name = request.form.get("company_name", "").strip() or None
    departement_raw = request.form.get("departement", "").strip() or None
    region_raw = request.form.get("region", "").strip() or None
    max_results = int(request.form.get("max_results", 15))

    # Recherche nationale : taper "France" (ou une variante courante) dans le
    # champ Ville ne doit PAS être traité comme un mot-clé de recherche texte
    # (l'API cherche alors les entreprises dont le NOM ou l'ADRESSE contient
    # littéralement "France", ce qui ne couvre presque rien) — c'est une vraie
    # demande de recherche sans restriction de ville, sur toute la France,
    # filtrée seulement par les codes NAF sélectionnés.
    NATIONWIDE_ALIASES = {"france", "toute la france", "france entière", "france entiere", "national"}
    nationwide = city_raw.lower() in NATIONWIDE_ALIASES
    city = None if nationwide else (city_raw or None)
    if nationwide:
        postal_code = None  # un code postal n'a pas de sens combiné à une recherche nationale

    # Département / région : on accepte un nom ("Essonne", "Île-de-France")
    # ou un code déjà valide ("91", "11") — voir services/geo.py.
    try:
        departement_code = geo.resolve_departement(departement_raw)
        if departement_raw and not departement_code:
            flash(
                f"Département \"{departement_raw}\" introuvable — vérifiez l'orthographe "
                "ou utilisez directement le code (ex : 91).",
                "error",
            )
            return redirect(url_for("recherche"))
        region_code = geo.resolve_region(region_raw)
        if region_raw and not region_code:
            flash(
                f"Région \"{region_raw}\" introuvable — vérifiez l'orthographe "
                "ou utilisez directement le code (ex : 11).",
                "error",
            )
            return redirect(url_for("recherche"))
    except geo.GeoError as e:
        flash(str(e), "error")
        return redirect(url_for("recherche"))

    if not nationwide and not city and not company_name and not departement_code and not region_code:
        flash(
            "Merci de renseigner une ville, \"France\" pour tout le territoire, "
            "un département, une région, ou un nom d'entreprise.",
            "error",
        )
        return redirect(url_for("recherche"))

    # Recherche d'une entreprise précise par son nom : on ignore les codes NAF
    # (elle peut être dans n'importe quel secteur, pas forcément ceux ciblés
    # par défaut) pour ne pas rater le résultat à cause d'un filtre trop strict.
    naf_codes = None if company_name else (request.form.getlist("naf_codes") or config.DEFAULT_NAF_CODES)

    try:
        establishments = sirene.search_establishments(
            city=city, postal_code=postal_code, company_name=company_name,
            naf_codes=naf_codes, departement=departement_code, region=region_code,
            max_results=max_results,
        )
    except sirene.SireneError as e:
        flash(f"Erreur Sirene : {e}", "error")
        return redirect(url_for("recherche"))

    created = 0
    skipped_no_domain = 0
    skipped_duplicate = 0
    skipped_no_contact = 0
    merged_same_contact = 0
    provider_warnings = []
    # Si le premier appel France Travail échoue (identifiants invalides, API
    # indisponible...), inutile de réessayer sur chaque entreprise suivante
    # de la même recherche — un seul avertissement suffit. Trois API
    # distinctes (scopes différents) -> trois coupe-circuits indépendants :
    # une pouvant échouer (ex : mauvais scope) sans bloquer les autres.
    france_travail_disabled_this_run = False
    pages_employeurs_disabled_this_run = False
    lbb_disabled_this_run = False

    with get_db() as conn:
        for etab in establishments:
            if not etab.get("siren") or not etab.get("name"):
                continue

            # Déjà traitée lors d'une recherche précédente (que ça ait abouti
            # à un brouillon ou non) -> on ne refait pas le travail, pour
            # éviter de regaspiller des crédits Hunter/Apollo sur une
            # entreprise dont on sait déjà qu'elle n'a pas de site identifié
            # ou pas de contact trouvable.
            existing_company_id = get_company_id_by_siren(conn, etab["siren"])
            if existing_company_id:
                skipped_duplicate += 1
                continue

            domain = domain_guess.find_live_domain(etab["name"])
            etab["domain"] = domain
            etab["domain_confidence"] = "guessed" if domain else "unknown"

            company_id = upsert_company(conn, etab)

            # Valeurs par défaut : pas écrasées si France Travail est
            # désactivé (pas de clé) ou en pause (coupe-circuit) sur cette
            # entreprise — sert plus bas à décrire ce site dans
            # merged_sites s'il fusionne avec un contact déjà connu.
            offers_count = None
            potential = None

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

            # Signal "recrute actuellement" via France Travail (gratuit,
            # comme Jobea) — bonus non bloquant, ne dépend pas d'un domaine
            # trouvé (juste du SIRET, toujours connu via Sirene).
            if config.FRANCE_TRAVAIL_CLIENT_ID and not france_travail_disabled_this_run:
                try:
                    offers_count = france_travail.check_hiring(etab.get("siret"))
                    if offers_count is not None:
                        update_company_hiring_signal(conn, company_id, offers_count)
                except france_travail.FranceTravailError as e:
                    provider_warnings.append(f"France Travail (signal recrutement) : {e}")
                    france_travail_disabled_this_run = True

            # Page employeur France Travail (badges/labels/avantages mis en
            # avant par l'entreprise elle-même) — même principe, bonus non
            # bloquant, gratuit.
            if config.FRANCE_TRAVAIL_CLIENT_ID and not pages_employeurs_disabled_this_run:
                try:
                    page = france_travail.get_employer_page(
                        etab.get("siret"), postal_code=etab.get("postal_code"),
                        departement_code=departement_code,
                    )
                    update_company_employer_page(conn, company_id, page)
                except france_travail.FranceTravailError as e:
                    provider_warnings.append(f"France Travail (page employeur) : {e}")
                    pages_employeurs_disabled_this_run = True

            # Score "potentiel d'embauche" La Bonne Boîte — complète le
            # signal "recrute actuellement" : une entreprise sans offre
            # publiée là maintenant peut quand même avoir un fort potentiel
            # d'embauche dans les 6 prochains mois. Même principe, bonus non
            # bloquant, gratuit.
            if config.FRANCE_TRAVAIL_CLIENT_ID and not lbb_disabled_this_run:
                try:
                    potential = france_travail.get_hiring_potential(
                        etab.get("siret"), naf_code=etab.get("naf_code"),
                    )
                    update_company_hiring_potential(conn, company_id, potential)
                except france_travail.FranceTravailError as e:
                    provider_warnings.append(f"France Travail (La Bonne Boîte) : {e}")
                    lbb_disabled_this_run = True

            contact = None
            if domain:
                # Un domaine déjà résolu pour une autre entreprise (souvent
                # une filiale du même groupe) -> on réutilise ce contact
                # plutôt que de rappeler Hunter.io/GetProspect une seconde
                # fois pour rien (économie de crédits), ce qui a aussi pour
                # effet de retrouver mécaniquement le même contact -> la
                # fusion juste en dessous s'appliquera.
                contact = get_contact_by_domain(conn, domain)
                if not contact:
                    contact = contact_finder.find_best_contact(conn, domain, warnings=provider_warnings)

            if not domain:
                skipped_no_domain += 1
                continue  # pas de mail généré sans domaine identifié

            to_addr = contact["email"] if contact else None
            first_name = contact.get("first_name") if contact else None

            if not to_addr:
                skipped_no_contact += 1
                continue  # domaine trouvé mais aucun contact (quota atteint ou personne trouvée)

            # Même contact (email) déjà utilisé pour un autre site -> pas un
            # nouveau brouillon/mail en double : ce site vient s'accrocher
            # au brouillon existant (visible sur sa page), un seul mail
            # partira pour tout le groupe qui partage ce contact.
            existing_draft = get_draft_by_contact_email(conn, to_addr)
            if existing_draft:
                add_merged_site(conn, existing_draft["id"], {
                    "company_name": etab["name"],
                    "city": etab.get("city"),
                    "hiring_signal": bool(offers_count) if offers_count is not None else None,
                    "hiring_offers_count": offers_count,
                    "lbb_is_high_potential": (potential or {}).get("is_high_potential"),
                    "lbb_hiring_potential": (potential or {}).get("hiring_potential"),
                })
                merged_same_contact += 1
                continue

            contact_id = add_contact(conn, company_id, contact)
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
    if merged_same_contact:
        msg += (
            f" {merged_same_contact} entreprise(s) fusionnée(s) avec un brouillon existant "
            "(même contact — un seul mail partira pour le groupe)."
        )
    flash(msg, "success")

    for w in dict.fromkeys(provider_warnings):  # dédoublonne en gardant l'ordre
        flash(w, "warning")

    return redirect(url_for("index"))


@app.route("/draft/<int:draft_id>", methods=["GET", "POST"])
def draft_detail(draft_id):
    with get_db() as conn:
        if request.method == "POST":
            action = request.form.get("action")

            # Objet/Message et boutons d'action vivent dans LE MÊME <form> du
            # template (draft.html) : un clic sur "Marquer prêt", "Envoyer"
            # ou "Écarter" soumet donc TOUJOURS le texte actuellement affiché
            # à l'écran, même sans avoir cliqué "Enregistrer" avant. On le
            # persiste systématiquement ici, pour TOUTE action, avant de
            # faire quoi que ce soit d'autre : sinon une modification tapée
            # dans le formulaire mais jamais explicitement enregistrée était
            # silencieusement ignorée, et c'est l'ancienne version en base
            # qui partait à l'envoi (bug découvert le 2026-09-16 : un texte
            # amélioré collé dans le champ Message, puis "Envoyer" cliqué
            # directement sans passer par "Enregistrer", a fini par envoyer
            # l'ancienne version à Silex France au lieu de la nouvelle).
            if action in ("save", "mark_ready", "decline", "send"):
                update_draft(
                    conn, draft_id,
                    subject=request.form.get("subject", ""),
                    body=request.form.get("body", ""),
                )

                # Pièce jointe : même principe que subject/body ci-dessus —
                # le champ fichier vit dans le même formulaire, donc on la
                # traite pour TOUTE action. Trois cas : nouveau fichier
                # choisi (remplace l'ancien s'il y en avait un), case
                # "retirer" cochée (supprime la pièce jointe existante), ou
                # ni l'un ni l'autre (on ne touche à rien — un input file ne
                # peut pas "se souvenir" d'un choix précédent d'un rechargement
                # à l'autre, une soumission sans nouveau fichier ne veut donc
                # pas dire qu'on veut la retirer).
                current = get_draft(conn, draft_id)
                uploaded = request.files.get("attachment")
                remove_requested = request.form.get("remove_attachment") == "1"

                if uploaded and uploaded.filename:
                    safe_name = secure_filename(uploaded.filename)
                    if not safe_name:
                        flash("Nom de fichier non valide, pièce jointe ignorée.", "error")
                    else:
                        os.makedirs(config.ATTACHMENTS_DIR, exist_ok=True)
                        stored_name = f"{draft_id}_{safe_name}"
                        uploaded.save(os.path.join(config.ATTACHMENTS_DIR, stored_name))
                        if current["attachment_filename"] and current["attachment_filename"] != stored_name:
                            _delete_attachment_file(current["attachment_filename"])
                        update_draft(
                            conn, draft_id,
                            attachment_filename=stored_name,
                            attachment_original_name=uploaded.filename,
                        )
                elif remove_requested and current["attachment_filename"]:
                    _delete_attachment_file(current["attachment_filename"])
                    update_draft(
                        conn, draft_id,
                        attachment_filename=None, attachment_original_name=None,
                    )

            if action == "save":
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
                    from services.email_templates import build_html_email

                    # Pour une relance, on rattache le mail au fil d'origine
                    # (In-Reply-To) si on a le Message-ID du mail précédent.
                    in_reply_to = None
                    if d["parent_draft_id"]:
                        parent = get_draft(conn, d["parent_draft_id"])
                        if parent and parent["message_id"]:
                            in_reply_to = parent["message_id"]

                    # Le brouillon stocké/édité reste du texte brut (relu
                    # dans l'appli) ; la version HTML avec la signature mise
                    # en forme n'est construite qu'ici, au moment de
                    # l'envoi, et n'est jamais enregistrée en base.
                    html_body = build_html_email(d["body"])

                    attachment_path = None
                    if d["attachment_filename"]:
                        attachment_path = os.path.join(
                            config.ATTACHMENTS_DIR, d["attachment_filename"]
                        )

                    try:
                        message_id = send_email(
                            d["contact_email"], d["subject"], d["body"],
                            in_reply_to=in_reply_to, html_body=html_body,
                            attachment_path=attachment_path,
                            attachment_name=d["attachment_original_name"],
                        )
                        mark_sent(conn, draft_id, message_id=message_id)
                        flash(f"Mail envoyé à {d['contact_email']}.", "success")
                    except MailerError as e:
                        flash(f"Échec de l'envoi : {e}", "error")

            # Seul "Envoyer" ramène au tableau de bord (le brouillon est
            # traité, plus rien à y faire) ; "Enregistrer" reste sur la page
            # du brouillon — on peut être en train de le retravailler sans
            # avoir encore décidé de l'envoyer, pas de raison d'être éjectée.
            # "Marquer prêt" et "Écarter" restent aussi sur la page.
            if action == "send":
                return redirect(url_for("index"))
            return redirect(url_for("draft_detail", draft_id=draft_id))

        d = get_draft(conn, draft_id)
        quotas = _quotas(conn)
    if not d:
        flash("Brouillon introuvable.", "error")
        return redirect(url_for("index"))
    return render_template("draft.html", d=d, quotas=quotas)


@app.route("/draft/<int:draft_id>/attachment")
def draft_attachment(draft_id):
    """Permet d'ouvrir/télécharger la pièce jointe actuelle d'un brouillon
    (lien affiché sur sa page) pour vérifier ce qui sera réellement envoyé."""
    with get_db() as conn:
        d = get_draft(conn, draft_id)
    if not d or not d["attachment_filename"]:
        flash("Aucune pièce jointe pour ce brouillon.", "error")
        return redirect(url_for("draft_detail", draft_id=draft_id))
    return send_from_directory(
        config.ATTACHMENTS_DIR, d["attachment_filename"],
        as_attachment=True,
        download_name=d["attachment_original_name"] or d["attachment_filename"],
    )


if __name__ == "__main__":
    # threaded=True : sans ça, le serveur ne traite qu'UNE requête à la
    # fois — une recherche un peu longue (plusieurs entreprises, chacune
    # avec ses appels Apollo/France Travail/Hunter) bloquait alors TOUTE
    # l'appli (impossible d'ouvrir un brouillon en attendant). Avec
    # threaded=True, une recherche en cours n'empêche plus de naviguer
    # ailleurs dans l'appli pendant ce temps-là.
    app.run(debug=True, port=5000, threaded=True)
