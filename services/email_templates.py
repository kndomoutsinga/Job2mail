"""
Génération de mails de candidature spontanée personnalisés.

Plusieurs MODÈLES COMPLETS (pas juste la phrase d'accroche) tournent
automatiquement, pour que la formulation change vraiment d'une entreprise
à l'autre. Le modèle est tiré une fois par entreprise via un "seed" (son
id) : le résultat est stable si on régénère pour la même entreprise, mais
varie d'une entreprise à l'autre. Le texte généré est enregistré tel quel
dans le brouillon — c'est exactement ce qui part à l'envoi, sauf si on le
modifie à la main avant.

Contenu factuel et honnête — pas de tournures corporate creuses, phrases
courtes, signature "Cordialement". Personnalisez librement les modèles
ci-dessous ou le profil dans PROFILE.

Signature : le brouillon stocké/édité dans l'appli reste du texte brut (ce
qu'on relit/modifie dans le tableau de bord). À l'ENVOI seulement (voir
build_html_email plus bas, appelé depuis app.py), une version HTML est
générée en plus, avec la signature mise en forme (nom en gras, sous-titre,
liens...) telle que fournie par l'utilisatrice — le mail part en
multipart/alternative (texte + HTML), donc les clients mail qui affichent
le HTML (Gmail, etc.) montrent la belle version, et le texte brut reste en
repli pour les autres.
"""
import html as html_lib
import random

import config

# Identifiant LinkedIn et libellé de poste utilisés uniquement dans la
# signature (texte et HTML) — distincts de PROFILE ci-dessous, qui sert au
# corps de la lettre (voix "je suis développeuse full stack...", volontairement
# différente/plus simple que la liste de titres de la signature).
SIGNATURE_LINKEDIN = "kaprisky-ndo-moutsinga"
SIGNATURE_TITLES = "Développeuse Full Stack · Testeuse QA · Chef de Projet"
SIGNATURE_TAGLINE = "France · Mobile partout · Ouverte à un poste en CDI"

PROFILE = {
    "full_name": "Kaprisky NDO MOUTSINGA",
    "title": "Développeuse Full Stack",
    "stack": "PHP/Symfony, React, Java/Spring Boot",
    "extra_roles": "testeuse QA junior ou cheffe de projet junior",
    "availability": "disponible immédiatement",
    "mobility": "mobile partout en France",
}

# Chaque modèle est un texte complet (accroche + présentation) avec les
# mêmes informations factuelles (PROFILE, portfolio...) mais une formulation
# différente. Garder le même sens partout : démarche de contact direct
# assumée (pas "je n'ai pas trouvé d'offre"), profil dev en priorité mais
# ouverte à d'autres postes IT, message court et motivé.
TEMPLATES = [
    (
        "Après plusieurs mois de candidatures classiques, j'ai décidé de tester une "
        "approche plus directe : vous contacter directement, sans attendre une offre "
        "précise. {company} fait partie des entreprises que j'ai identifiées comme "
        "correspondant à mon profil.\n\n"
        "Je suis {title} ({stack}), {availability_sentence} et {mobility_sentence}. "
        "Je suis convaincue d'avoir le profil et l'expérience pour apporter quelque "
        "chose rapidement, dev en priorité, mais aussi partante pour un poste de "
        "{extra_roles}, ou tout poste IT qui correspondrait à mon profil.\n\n"
        "Mon portfolio (projets, compétences, parcours) : {portfolio}\n\n"
        "Je suis disponible pour en discuter quand vous voulez."
    ),
    (
        "Je suis en recherche active depuis un moment, et j'ai choisi de tester le "
        "contact direct plutôt que d'attendre une offre qui corresponde pile à mon "
        "profil. {company} fait partie des entreprises que j'ai repérées comme "
        "correspondant à ce que je recherche.\n\n"
        "{title} de formation ({stack}), {availability_sentence} et {mobility_sentence}. "
        "Je pense avoir le profil et l'expérience pour être utile rapidement, en dev "
        "en priorité, mais je reste ouverte à un poste de {extra_roles}, ou à tout "
        "poste IT qui correspondrait à mon profil.\n\n"
        "Vous trouverez mon parcours et mes projets ici : {portfolio}\n\n"
        "Je suis disponible pour échanger quand vous voulez."
    ),
    (
        "J'ai exploré plusieurs pistes ces derniers mois, et je me permets aujourd'hui "
        "de vous contacter directement, portfolio à l'appui. {company} correspond à ce que "
        "je recherche.\n\n"
        "Je suis {title} ({stack}), {availability_sentence} et {mobility_sentence}. "
        "Mon profil et mon expérience me semblent adaptés pour apporter quelque chose "
        "rapidement, en priorité comme dev, mais aussi comme {extra_roles}, ou tout "
        "poste IT en lien avec mon profil.\n\n"
        "Portfolio (projets, compétences, parcours) : {portfolio}\n\n"
        "Disponible pour un échange quand vous voulez."
    ),
    (
        "Plutôt que d'attendre une offre précise, j'ai décidé de contacter directement "
        "les entreprises qui correspondent à mon profil. {company} en fait partie.\n\n"
        "Je suis {title} ({stack}), {availability_sentence} et {mobility_sentence}, "
        "avec le profil et l'expérience pour apporter quelque chose rapidement. Je "
        "suis ouverte à un poste de dev en priorité, mais aussi de {extra_roles}, ou "
        "tout poste IT qui correspondrait à mon profil.\n\n"
        "Mon portfolio : {portfolio}\n\n"
        "Je reste disponible pour en discuter quand vous voulez."
    ),
]

CLOSING = (
    "Cordialement,\n"
    "{full_name}\n"
    "{titles}\n\n"
    "{portfolio}\n"
    "in/{linkedin} | {email} | {phone}\n"
    "{tagline}"
)


def _availability_sentence():
    # Pas de "Je suis" ici : tous les modèles l'ont déjà une fois avant
    # (ex : "Je suis {title} (...), {availability_sentence} et
    # {mobility_sentence}") — le remettre créait un "Je suis ... Je suis
    # disponible..." redondant, avec un "Je" mal placé en milieu de phrase.
    return PROFILE["availability"]


def _mobility_sentence():
    return PROFILE["mobility"]


def _build_closing():
    return CLOSING.format(
        full_name=PROFILE["full_name"],
        titles=SIGNATURE_TITLES,
        portfolio=config.SENDER_PORTFOLIO,
        linkedin=SIGNATURE_LINKEDIN,
        email=config.SENDER_EMAIL,
        phone=config.SENDER_PHONE,
        tagline=SIGNATURE_TAGLINE,
    )


def generate_email(company_name, contact_first_name=None, seed=None):
    """
    Retourne (subject, body). `seed` (ex: id de l'entreprise) permet de
    garder le même modèle pour une même entreprise si on régénère, tout en
    variant d'une entreprise à l'autre.
    """
    rnd = random.Random(seed)
    template = rnd.choice(TEMPLATES)

    greeting = f"Bonjour {contact_first_name}," if contact_first_name else "Madame, Monsieur,"

    body_middle = template.format(
        company=company_name,
        title=PROFILE["title"],
        stack=PROFILE["stack"],
        extra_roles=PROFILE["extra_roles"],
        availability_sentence=_availability_sentence(),
        mobility_sentence=_mobility_sentence(),
        portfolio=config.SENDER_PORTFOLIO,
    )

    closing = _build_closing()

    body = f"{greeting}\n\n{body_middle}\n\n{closing}"
    subject = f"Candidature spontanée · {PROFILE['title']} · {PROFILE['full_name']}"

    return subject, body


FOLLOWUP_TEMPLATES = [
    (
        "Je me permets de revenir vers vous : je vous avais écrit le {date} au sujet "
        "d'une candidature spontanée chez {company}, sans nouvelle de votre côté pour "
        "l'instant.\n\n"
        "Pour rappel : {title} ({stack}), {availability_sentence} et "
        "{mobility_sentence}, ouverte aussi à un poste de {extra_roles}.\n\n"
        "Mon portfolio : {portfolio}\n"
        "N'hésitez pas à me solliciter si le profil vous intéresse, même plus tard."
    ),
    (
        "Petit rappel suite à mon message du {date} pour {company}. Je reste "
        "disponible si un besoin se présente, même s'il n'y a pas d'urgence de votre "
        "côté.\n\n"
        "{title} ({stack}), {availability_sentence} et {mobility_sentence}, également "
        "ouverte à un poste de {extra_roles}.\n\n"
        "Portfolio : {portfolio}\n"
        "Je reste à votre disposition si le profil correspond, même plus tard."
    ),
    (
        "Je reviens brièvement vers vous après mon mail du {date} concernant "
        "{company}, au cas où il serait passé inaperçu.\n\n"
        "Pour rappel rapide : {title} ({stack}), {availability_sentence} et "
        "{mobility_sentence}, ouverte aussi à {extra_roles}.\n\n"
        "Mon portfolio : {portfolio}\n"
        "N'hésitez pas si un besoin se présente, même plus tard."
    ),
]


def generate_followup_email(company_name, contact_first_name=None, followup_number=1,
                             original_date=None, seed=None):
    """
    Mail de relance, plus court que la candidature initiale. `original_date`
    est une chaîne déjà formatée pour être lisible (ex: "12 septembre").
    """
    rnd = random.Random(f"{seed}-followup-{followup_number}" if seed else None)
    date_str = original_date or "récemment"
    template = rnd.choice(FOLLOWUP_TEMPLATES)

    greeting = f"Bonjour {contact_first_name}," if contact_first_name else "Madame, Monsieur,"

    body_middle = template.format(
        company=company_name,
        date=date_str,
        title=PROFILE["title"],
        stack=PROFILE["stack"],
        extra_roles=PROFILE["extra_roles"],
        availability_sentence=_availability_sentence(),
        mobility_sentence=_mobility_sentence(),
        portfolio=config.SENDER_PORTFOLIO,
    )

    closing = _build_closing()

    body = f"{greeting}\n\n{body_middle}\n\n{closing}"
    suffix = f" (relance {followup_number})" if followup_number > 1 else " (relance)"
    subject = f"Candidature spontanée · {PROFILE['title']} · {PROFILE['full_name']}{suffix}"

    return subject, body


# --- Version HTML de la signature, générée uniquement à l'ENVOI -----------
# (voir la note en tête de fichier). Reprend fidèlement la signature fournie
# par l'utilisatrice (capture d'écran du 2026-09-15) : nom en gras/serif,
# sous-titre gris, courte barre d'accent bleue, lien portfolio, ligne de
# contact et tagline en monospace.

SIGNATURE_HTML_TEMPLATE = """\
<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
  <tr>
    <td style="border-left:3px solid #1a73e8; padding-left:18px;">
      <div style="font-family:Georgia,'Times New Roman',serif; font-size:22px; font-weight:bold; color:#111111; margin:0 0 6px 0;">{full_name}</div>
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:14px; color:#5f6368; margin:0 0 10px 0;">{titles}</div>
      <div style="width:40px; height:3px; background-color:#1a73e8; margin:0 0 10px 0; font-size:0; line-height:0;">&nbsp;</div>
      <div style="font-family:'Courier New',Courier,monospace; font-size:13px; margin:0 0 8px 0;">
        <a href="{portfolio_url}" style="color:#1a73e8; text-decoration:none;">{portfolio}</a>
      </div>
      <div style="font-family:'Courier New',Courier,monospace; font-size:13px; color:#333333; margin:0 0 8px 0;">
        in/{linkedin}&nbsp;&nbsp;|&nbsp;&nbsp;{email}&nbsp;&nbsp;|&nbsp;&nbsp;{phone}
      </div>
      <div style="font-family:'Courier New',Courier,monospace; font-size:11px; color:#9aa0a6; letter-spacing:1px; text-transform:uppercase;">{tagline}</div>
    </td>
  </tr>
</table>"""


def _signature_html():
    portfolio = config.SENDER_PORTFOLIO
    portfolio_url = portfolio if portfolio.startswith("http") else f"https://{portfolio}"
    return SIGNATURE_HTML_TEMPLATE.format(
        full_name=html_lib.escape(PROFILE["full_name"].title()),
        titles=html_lib.escape(SIGNATURE_TITLES),
        portfolio=html_lib.escape(portfolio),
        portfolio_url=html_lib.escape(portfolio_url, quote=True),
        linkedin=html_lib.escape(SIGNATURE_LINKEDIN),
        email=html_lib.escape(config.SENDER_EMAIL),
        phone=html_lib.escape(config.SENDER_PHONE),
        tagline=html_lib.escape(SIGNATURE_TAGLINE),
    )


def _paragraphs_to_html(text):
    paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    style = (
        "margin:0 0 14px 0; font-family:Arial,Helvetica,sans-serif; "
        "font-size:14px; color:#202124; line-height:1.5;"
    )
    return "".join(
        f'<p style="{style}">{html_lib.escape(p).replace(chr(10), "<br>")}</p>'
        for p in paragraphs
    )


def build_html_email(plain_body):
    """
    Construit la version HTML d'un brouillon (texte brut, potentiellement
    modifié à la main dans l'appli) pour l'envoi en multipart/alternative :
    le texte de la lettre devient des paragraphes HTML, et tout ce qui suit
    "Cordialement," est remplacé par la signature mise en forme (fixe, pas
    dérivée du texte édité, pour être sûre qu'elle s'affiche toujours
    correctement même après une modification manuelle du brouillon).
    Appelée uniquement à l'envoi (voir app.py) — jamais stockée en base.
    """
    marker = "Cordialement,"
    idx = plain_body.rfind(marker)
    letter_part = plain_body[:idx].rstrip() if idx != -1 else plain_body.strip()

    closing_style = (
        "margin:0 0 16px 0; font-family:Arial,Helvetica,sans-serif; "
        "font-size:14px; color:#202124;"
    )
    return (
        f'<div>{_paragraphs_to_html(letter_part)}'
        f'<p style="{closing_style}">Cordialement,</p>'
        f'{_signature_html()}</div>'
    )
