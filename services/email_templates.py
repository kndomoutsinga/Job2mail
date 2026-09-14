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
"""
import random

import config

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
        "approche plus directe : vous contacter avec mon CV, sans attendre une offre "
        "précise. {company} fait partie des entreprises qui m'intéressent.\n\n"
        "Je suis {title} ({stack}), {availability_sentence} et {mobility_sentence}. "
        "Je suis convaincue d'avoir le profil et l'expérience pour apporter quelque "
        "chose rapidement — dev en priorité, mais aussi partante pour un poste de "
        "{extra_roles}, ou tout poste IT qui correspondrait à mon profil.\n\n"
        "Mon portfolio (projets, compétences, parcours) : {portfolio}\n\n"
        "Je suis disponible pour en discuter quand vous voulez."
    ),
    (
        "Je suis en recherche active depuis un moment, et j'ai choisi de tester le "
        "contact direct plutôt que d'attendre une offre qui corresponde pile à mon "
        "profil. {company} fait partie des entreprises qui m'intéressent particulièrement.\n\n"
        "{title} de formation ({stack}), {availability_sentence} et {mobility_sentence}. "
        "Je pense avoir le profil et l'expérience pour être utile rapidement, en dev "
        "en priorité, mais je reste ouverte à un poste de {extra_roles}, ou à tout "
        "poste IT qui correspondrait à mon profil.\n\n"
        "Vous trouverez mon parcours et mes projets ici : {portfolio}\n\n"
        "Je suis disponible pour échanger quand vous voulez."
    ),
    (
        "J'ai exploré plusieurs pistes ces derniers mois, et je me permets aujourd'hui "
        "de vous contacter directement, CV à l'appui. {company} correspond à ce que "
        "je recherche.\n\n"
        "Je suis {title} ({stack}), {availability_sentence} et {mobility_sentence}. "
        "Mon profil et mon expérience me semblent adaptés pour apporter quelque chose "
        "rapidement — en priorité comme dev, mais aussi comme {extra_roles}, ou tout "
        "poste IT en lien avec mon profil.\n\n"
        "Portfolio (projets, compétences, parcours) : {portfolio}\n\n"
        "Disponible pour un échange quand vous voulez."
    ),
    (
        "Plutôt que d'attendre une offre précise, j'ai décidé de contacter directement "
        "les entreprises qui m'intéressent — {company} en fait partie.\n\n"
        "Je suis {title} ({stack}), {availability_sentence} et {mobility_sentence}, "
        "avec le profil et l'expérience pour apporter quelque chose rapidement. Je "
        "suis ouverte à un poste de dev en priorité, mais aussi de {extra_roles}, ou "
        "tout poste IT qui correspondrait à mon profil.\n\n"
        "Mon portfolio : {portfolio}\n\n"
        "Je reste disponible pour en discuter quand vous voulez."
    ),
]

CLOSING = "Cordialement,\n{full_name}\n{phone}\n{portfolio}"


def _availability_sentence():
    return f"Je suis {PROFILE['availability']}"


def _mobility_sentence():
    return PROFILE["mobility"]


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

    closing = CLOSING.format(
        full_name=PROFILE["full_name"],
        phone=config.SENDER_PHONE,
        portfolio=config.SENDER_PORTFOLIO,
    )

    body = f"{greeting}\n\n{body_middle}\n\n{closing}"
    subject = f"Candidature spontanée — {PROFILE['title']} — {PROFILE['full_name']}"

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
        "Petit rappel suite à mon message du {date} pour {company} — je reste "
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

    closing = CLOSING.format(
        full_name=PROFILE["full_name"],
        phone=config.SENDER_PHONE,
        portfolio=config.SENDER_PORTFOLIO,
    )

    body = f"{greeting}\n\n{body_middle}\n\n{closing}"
    suffix = f" (relance {followup_number})" if followup_number > 1 else " (relance)"
    subject = f"Candidature spontanée — {PROFILE['title']} — {PROFILE['full_name']}{suffix}"

    return subject, body
