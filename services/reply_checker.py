"""
Vérifie, via IMAP, si un contact a répondu à un mail envoyé.

Utilise les mêmes identifiants que l'envoi (SENDER_EMAIL / SENDER_APP_PASSWORD) :
un mot de passe d'application Gmail donne accès à IMAP comme à SMTP, pas
besoin d'en créer un deuxième.

Limite connue : la recherche IMAP "SINCE" ne travaille qu'au jour près (pas
à l'heure près), donc un mail envoyé et une réponse arrivée le même jour
peuvent — en théorie — se confondre avec un mail plus ancien du même
contact. Dans la pratique, pour une candidature spontanée, c'est un cas
rare et sans grande conséquence (au pire une candidature marquée "répondu"
un peu tôt).
"""
import email
import imaplib
from datetime import datetime
from email.header import decode_header

import config


class ReplyCheckError(Exception):
    pass


def _decode(value):
    if not value:
        return ""
    parts = decode_header(value)
    decoded = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            decoded += text.decode(enc or "utf-8", errors="replace")
        else:
            decoded += text
    return decoded


def _extract_snippet(msg, max_len=220):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                charset = part.get_content_charset() or "utf-8"
                try:
                    body = part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    continue
                break
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            body = msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            body = ""

    body = " ".join(body.split())  # aplatit les sauts de ligne
    return (body[:max_len] + "…") if len(body) > max_len else body


def check_reply(contact_email, since_iso):
    """
    Retourne {"date": str, "snippet": str} si un mail de `contact_email` a
    été reçu depuis `since_iso` (ISO 8601), sinon None.
    """
    if not config.SENDER_EMAIL or not config.SENDER_APP_PASSWORD:
        raise ReplyCheckError(
            "Identifiants manquants : renseignez SENDER_EMAIL et SENDER_APP_PASSWORD dans .env"
        )
    if not contact_email:
        return None

    try:
        since_dt = datetime.fromisoformat(since_iso)
    except (TypeError, ValueError):
        since_dt = datetime.utcnow()
    imap_date = since_dt.strftime("%d-%b-%Y")

    try:
        imap = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT)
    except (imaplib.IMAP4.error, OSError) as e:
        raise ReplyCheckError(f"Connexion IMAP impossible ({config.IMAP_HOST}) : {e}") from e

    try:
        try:
            imap.login(config.SENDER_EMAIL, config.SENDER_APP_PASSWORD)
        except imaplib.IMAP4.error as e:
            raise ReplyCheckError(
                "Authentification IMAP refusée — vérifiez le mot de passe d'application "
                "et que l'accès IMAP est activé sur le compte Gmail."
            ) from e

        imap.select("INBOX", readonly=True)
        typ, data = imap.search(None, f'(FROM "{contact_email}" SINCE {imap_date})')
        if typ != "OK" or not data or not data[0]:
            return None

        ids = data[0].split()
        latest_id = ids[-1]  # le plus récent
        typ, msg_data = imap.fetch(latest_id, "(RFC822)")
        if typ != "OK" or not msg_data or not msg_data[0]:
            return None

        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        return {
            "date": _decode(msg.get("Date")) or datetime.utcnow().isoformat(),
            "snippet": _extract_snippet(msg),
        }
    finally:
        try:
            imap.logout()
        except Exception:
            pass
