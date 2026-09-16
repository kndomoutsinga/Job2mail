"""
Envoi d'un mail via SMTP (Gmail par défaut). Ce module tourne uniquement en
local sur votre machine, avec vos propres identifiants stockés dans .env —
aucun mot de passe ne transite ailleurs.

Gmail exige un "mot de passe d'application" (pas votre mot de passe normal),
à générer sur https://myaccount.google.com/apppasswords après avoir activé
la validation en 2 étapes.
"""
import mimetypes
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid

import config


class MailerError(Exception):
    pass


def _build_attachment_part(path, filename=None):
    """Construit la partie MIME d'une pièce jointe quelconque (CV, image...),
    en devinant son type depuis l'extension (repli générique si inconnu)."""
    filename = filename or os.path.basename(path)
    ctype, encoding = mimetypes.guess_type(path)
    if ctype is None or encoding is not None:
        ctype = "application/octet-stream"
    maintype, subtype = ctype.split("/", 1)
    with open(path, "rb") as f:
        part = MIMEBase(maintype, subtype)
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=filename)
    return part


def send_email(to_address, subject, body, in_reply_to=None, html_body=None,
                attachment_path=None, attachment_name=None):
    """
    Envoie le mail et retourne le Message-ID généré (à conserver pour le
    suivi des réponses et, pour une relance, pour bien la rattacher au fil
    de discussion d'origine via `in_reply_to`).

    `html_body` (optionnel) : si fourni, le mail part en multipart/alternative
    (texte brut `body` + version HTML `html_body`, ex : signature mise en
    forme) — les clients mail qui savent afficher du HTML (Gmail, etc.)
    montrent `html_body`, les autres retombent sur `body`. Sans `html_body`,
    comportement inchangé : mail texte brut simple.

    `attachment_path` (optionnel) : chemin d'un fichier quelconque (CV,
    image...) à joindre réellement au mail — voir data/attachments/ et
    draft_detail() dans app.py. `attachment_name` est le nom affiché au
    destinataire (par défaut, le nom du fichier sur le disque).
    """
    if not config.SENDER_EMAIL or not config.SENDER_APP_PASSWORD:
        raise MailerError(
            "Identifiants d'envoi manquants : renseignez SENDER_EMAIL et "
            "SENDER_APP_PASSWORD dans votre fichier .env"
        )

    message_id = make_msgid()

    if html_body:
        content = MIMEMultipart("alternative")
        # L'ordre compte : la dernière partie attachée est celle préférée
        # par les clients qui savent afficher du HTML (RFC 2046) — donc le
        # texte brut d'abord, le HTML en dernier.
        content.attach(MIMEText(body, "plain", "utf-8"))
        content.attach(MIMEText(html_body, "html", "utf-8"))
    else:
        content = MIMEText(body, "plain", "utf-8")

    if attachment_path:
        # multipart/mixed autour du texte (ou du multipart/alternative
        # texte+HTML ci-dessus) + la pièce jointe, pour ne pas casser
        # l'affichage HTML tout en ajoutant un fichier réel.
        msg = MIMEMultipart("mixed")
        msg.attach(content)
        msg.attach(_build_attachment_part(attachment_path, attachment_name))
    else:
        msg = content
    msg["Subject"] = subject
    msg["From"] = formataddr((config.SENDER_NAME, config.SENDER_EMAIL))
    msg["To"] = to_address
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(config.SENDER_EMAIL, config.SENDER_APP_PASSWORD)
            server.sendmail(config.SENDER_EMAIL, [to_address], msg.as_string())
    except smtplib.SMTPAuthenticationError as e:
        raise MailerError(
            "Authentification refusée par Gmail — vérifiez que vous utilisez bien un "
            "mot de passe d'application (pas votre mot de passe normal)."
        ) from e
    except smtplib.SMTPException as e:
        raise MailerError(f"Échec de l'envoi : {e}") from e

    return message_id
