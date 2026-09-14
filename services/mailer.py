"""
Envoi d'un mail via SMTP (Gmail par défaut). Ce module tourne uniquement en
local sur votre machine, avec vos propres identifiants stockés dans .env —
aucun mot de passe ne transite ailleurs.

Gmail exige un "mot de passe d'application" (pas votre mot de passe normal),
à générer sur https://myaccount.google.com/apppasswords après avoir activé
la validation en 2 étapes.
"""
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid

import config


class MailerError(Exception):
    pass


def send_email(to_address, subject, body, in_reply_to=None):
    """
    Envoie le mail et retourne le Message-ID généré (à conserver pour le
    suivi des réponses et, pour une relance, pour bien la rattacher au fil
    de discussion d'origine via `in_reply_to`).
    """
    if not config.SENDER_EMAIL or not config.SENDER_APP_PASSWORD:
        raise MailerError(
            "Identifiants d'envoi manquants : renseignez SENDER_EMAIL et "
            "SENDER_APP_PASSWORD dans votre fichier .env"
        )

    message_id = make_msgid()

    msg = MIMEText(body, "plain", "utf-8")
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
