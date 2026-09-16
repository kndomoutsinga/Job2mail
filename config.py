import os
from dotenv import load_dotenv

load_dotenv()

# Note : la recherche d'entreprises utilise l'API publique et gratuite
# recherche-entreprises.api.gouv.fr (voir services/sirene.py), qui ne
# demande ni clé ni compte — rien à configurer ici pour cette partie.

HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "")
GETPROSPECT_API_KEY = os.getenv("GETPROSPECT_API_KEY", "")

# API "Offres d'emploi" de France Travail (ex-Pôle emploi) — publique et
# gratuite, utilisée uniquement pour savoir si une entreprise a des offres
# publiées en ce moment ("signal recrutement", voir services/france_travail.py).
# Compte gratuit à créer sur https://francetravail.io -> "Mes applications"
# -> abonner l'appli à l'API "Offres d'emploi v2" pour obtenir ces deux
# identifiants. Facultatif : sans eux, l'appli fonctionne normalement, juste
# sans ce signal.
FRANCE_TRAVAIL_CLIENT_ID = os.getenv("FRANCE_TRAVAIL_CLIENT_ID", "")
FRANCE_TRAVAIL_CLIENT_SECRET = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET", "")

SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
SENDER_NAME = os.getenv("SENDER_NAME", "")
SENDER_APP_PASSWORD = os.getenv("SENDER_APP_PASSWORD", "")
SENDER_PHONE = os.getenv("SENDER_PHONE", "")
SENDER_PORTFOLIO = os.getenv("SENDER_PORTFOLIO", "")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))

# Nombre de jours sans réponse avant qu'une candidature apparaisse dans
# "Relances à faire" sur le tableau de bord. Passé à 14 (deux semaines) pour
# laisser plus de temps avant de relancer un recruteur — une relance à une
# semaine est perçue comme trop rapide/insistante.
FOLLOWUP_DAYS = int(os.getenv("FOLLOWUP_DAYS", "14"))

# --- Quotas ---------------------------------------------------------------
# Limite de candidatures ENVOYÉES par jour (sécurité pour ne pas faire
# repérer le compte Gmail comme spam à force d'envoyer beaucoup de mails
# d'un coup — ce n'est pas un quota imposé par Google, juste une prudence).
# Une fois atteinte, le bouton "Envoyer" est bloqué jusqu'au lendemain.
DAILY_SEND_LIMIT = int(os.getenv("DAILY_SEND_LIMIT", "30"))

# Quotas mensuels réels des comptes API (à ajuster avec les chiffres exacts
# affichés sur vos tableaux de bord Hunter.io / GetProspect — "Account" /
# "Usage" / "Billing"). Une fois atteints, l'outil arrête d'appeler ce
# fournisseur jusqu'au mois suivant (les autres fournisseurs continuent).
HUNTER_MONTHLY_LIMIT = int(os.getenv("HUNTER_MONTHLY_LIMIT", "50"))
GETPROSPECT_MONTHLY_LIMIT = int(os.getenv("GETPROSPECT_MONTHLY_LIMIT", "50"))
# Apollo.io : seul "organizations/enrich" (infos entreprise) fonctionne sur
# mon plan gratuit — la recherche/révélation de contacts est verrouillée
# (voir services/apollo.py). 85 = quota réel affiché sur mon tableau de bord
# Apollo (Settings > Plan & Billing).
APOLLO_MONTHLY_LIMIT = int(os.getenv("APOLLO_MONTHLY_LIMIT", "85"))

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "job2mail.db")

# Pièces jointes (CV, image...) attachées à un brouillon depuis l'appli
# (bouton "Ajouter une pièce jointe" sur la page du brouillon, façon
# Gmail) — stockées ici, un fichier par brouillon (remplacé si on en
# choisit un autre). Limite de taille par sécurité (éviter un mail trop
# lourd qui passe mal ou traîne à s'envoyer).
ATTACHMENTS_DIR = os.path.join(os.path.dirname(__file__), "data", "attachments")
MAX_ATTACHMENT_SIZE_MB = int(os.getenv("MAX_ATTACHMENT_SIZE_MB", "10"))

# Codes NAF (activités) pertinents pour un profil dev / QA / chef de projet IT.
# Vous pouvez en ajouter/retirer depuis l'écran "Nouvelle recherche" de l'appli.
DEFAULT_NAF_CODES = [
    "6201Z",  # Programmation informatique
    "6202A",  # Conseil en systèmes et logiciels informatiques
    "6202B",  # Tierce maintenance de systèmes et d'applications informatiques
    "6203Z",  # Gestion d'installations informatiques
    "6209Z",  # Autres activités informatiques
    "6311Z",  # Traitement de données, hébergement
    "7022Z",  # Conseil pour les affaires et autres conseils de gestion (ESN/conseil)
]

# Villes cibles par défaut, reprises de sa stratégie de recherche actuelle
# (Paris/IDF + grandes villes déjà suivies). Code postal ou nom de commune.
DEFAULT_TARGET_CITIES = [
    "Paris", "Athis-Mons", "Nantes", "Lyon", "Bordeaux", "Toulouse",
    "Montpellier", "Lille", "Nice", "Sophia Antipolis", "Tours",
    "Strasbourg", "Clermont-Ferrand", "Orléans", "Poitiers", "Toulon",
    "Amiens", "Caen", "Rouen",
]
