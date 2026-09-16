import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    siren TEXT UNIQUE,
    siret TEXT,
    name TEXT NOT NULL,
    naf_code TEXT,
    naf_label TEXT,
    city TEXT,
    postal_code TEXT,
    address TEXT,
    domain TEXT,
    domain_confidence TEXT,  -- 'confirmed' | 'guessed' | 'unknown'
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    email TEXT,
    first_name TEXT,
    last_name TEXT,
    position TEXT,
    department TEXT,
    confidence INTEGER,
    source TEXT,  -- 'hunter' | 'apollo' | 'getprospect' | 'generic_pattern'
    FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    contact_id INTEGER,
    parent_draft_id INTEGER,     -- NULL = candidature initiale, sinon relance de ce brouillon
    followup_number INTEGER DEFAULT 0,  -- 0 = initiale, 1 = 1ère relance, 2 = 2e...
    subject TEXT,
    body TEXT,
    status TEXT DEFAULT 'draft',  -- draft | ready | sent | replied | declined
    template_used TEXT,
    message_id TEXT,             -- Message-ID du mail envoyé (pour le suivi/threading)
    created_at TEXT,
    sent_at TEXT,
    replied_at TEXT,
    reply_snippet TEXT,
    notes TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id),
    FOREIGN KEY (contact_id) REFERENCES contacts(id),
    FOREIGN KEY (parent_draft_id) REFERENCES drafts(id)
);

-- Historique des appels aux API de recherche de contact (Hunter.io,
-- GetProspect...) — sert uniquement à calculer la consommation du quota
-- mensuel de chaque fournisseur, pas à autre chose.
CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    called_at TEXT NOT NULL
);
"""

# Colonnes ajoutées après la première version du schéma — permet de mettre à
# jour une base existante sans perdre les données déjà présentes.
MIGRATIONS = [
    "ALTER TABLE drafts ADD COLUMN parent_draft_id INTEGER",
    "ALTER TABLE drafts ADD COLUMN followup_number INTEGER DEFAULT 0",
    "ALTER TABLE drafts ADD COLUMN message_id TEXT",
    "ALTER TABLE drafts ADD COLUMN replied_at TEXT",
    "ALTER TABLE drafts ADD COLUMN reply_snippet TEXT",
    # Infos entreprise récupérées via Apollo.io (organizations/enrich) — seule
    # partie de l'API Apollo utilisable sur le plan gratuit (voir services/apollo.py).
    "ALTER TABLE companies ADD COLUMN industry TEXT",
    "ALTER TABLE companies ADD COLUMN employee_count INTEGER",
    "ALTER TABLE companies ADD COLUMN short_description TEXT",
    "ALTER TABLE companies ADD COLUMN apollo_enriched_at TEXT",
    # Pièce jointe optionnelle par brouillon (CV, image...) — voir
    # services/mailer.py. attachment_filename = nom du fichier tel que
    # stocké sur disque (data/attachments/), attachment_original_name =
    # nom d'origine choisi par l'utilisatrice, montré dans l'appli et au
    # destinataire du mail.
    "ALTER TABLE drafts ADD COLUMN attachment_filename TEXT",
    "ALTER TABLE drafts ADD COLUMN attachment_original_name TEXT",
    # Signal "recrute actuellement" via l'API France Travail (voir
    # services/france_travail.py) — hiring_signal : NULL = jamais vérifié,
    # 0 = vérifié, aucune offre en cours, 1 = au moins une offre en cours.
    "ALTER TABLE companies ADD COLUMN hiring_signal INTEGER",
    "ALTER TABLE companies ADD COLUMN hiring_offers_count INTEGER",
    "ALTER TABLE companies ADD COLUMN hiring_checked_at TEXT",
    # Page employeur France Travail (voir services/france_travail.py,
    # get_employer_page) — badges/labels/avantages stockés en JSON
    # (listes de texte), employer_page_found = 1 si une page existe, 0 sinon.
    "ALTER TABLE companies ADD COLUMN employer_page_found INTEGER",
    "ALTER TABLE companies ADD COLUMN employer_page_badges TEXT",
    "ALTER TABLE companies ADD COLUMN employer_page_labels TEXT",
    "ALTER TABLE companies ADD COLUMN employer_page_avantages TEXT",
    "ALTER TABLE companies ADD COLUMN employer_page_checked_at TEXT",
    # Score "potentiel d'embauche" La Bonne Boîte (voir
    # services/france_travail.py, get_hiring_potential) — lbb_hiring_potential
    # entre 0 et 100 (NULL = jamais vérifié ou entreprise absente de La Bonne
    # Boîte), lbb_is_high_potential = 1 si l'entreprise est repérée comme "à
    # fort potentiel d'embauche" par France Travail.
    "ALTER TABLE companies ADD COLUMN lbb_hiring_potential INTEGER",
    "ALTER TABLE companies ADD COLUMN lbb_is_high_potential INTEGER",
    "ALTER TABLE companies ADD COLUMN lbb_checked_at TEXT",
    # Fusion des sites/établissements qui partagent le même contact (ex :
    # plusieurs filiales d'un même grand groupe, même domaine -> Hunter
    # renvoie le même email) — voir get_contact_by_domain/add_merged_site
    # ci-dessous. Au lieu de créer un brouillon (donc un mail) par site, on
    # n'en crée qu'un seul et les sites suivants s'y accrochent, stockés en
    # JSON ici : [{"company_name", "city", "hiring_signal",
    # "hiring_offers_count", "lbb_is_high_potential", "lbb_hiring_potential"}].
    "ALTER TABLE drafts ADD COLUMN merged_sites TEXT",
]


@contextmanager
def get_db():
    # timeout=30 : si une autre connexion écrit déjà, on attend jusqu'à 30s
    # au lieu d'échouer immédiatement avec "database is locked" (le défaut
    # sqlite3 est 5s, trop court si une recherche est en cours).
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL : permet à une lecture (ex: rafraîchir le tableau de bord) de ne
    # pas être bloquée par une écriture en cours (ex: une recherche), et vice versa.
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)
        for stmt in MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e):
                    raise


def get_company_id_by_siren(conn, siren):
    row = conn.execute("SELECT id FROM companies WHERE siren = ?", (siren,)).fetchone()
    return row["id"] if row else None


def upsert_company(conn, data):
    # INSERT ... ON CONFLICT DO NOTHING plutôt que SELECT puis INSERT :
    # avec deux recherches qui tournent en même temps (double clic sur
    # "Rechercher", ou deux établissements de la même entreprise dans les
    # résultats), le SELECT pouvait ne rien trouver puis l'INSERT arriver
    # après qu'une autre connexion ait déjà inséré la même siren entre
    # temps -> sqlite3.IntegrityError sur companies.siren. Cette version
    # est atomique : en cas de conflit, l'INSERT ne fait rien au lieu de
    # planter, et on va simplement relire l'id existant.
    cur = conn.execute(
        """INSERT INTO companies
           (siren, siret, name, naf_code, naf_label, city, postal_code, address,
            domain, domain_confidence, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(siren) DO NOTHING""",
        (
            data["siren"], data.get("siret"), data["name"], data.get("naf_code"),
            data.get("naf_label"), data.get("city"), data.get("postal_code"),
            data.get("address"), data.get("domain"), data.get("domain_confidence", "unknown"),
            datetime.utcnow().isoformat(),
        ),
    )
    if cur.rowcount:
        return cur.lastrowid
    # La ligne existait déjà (créée juste avant, par ce même passage ou par
    # une recherche concurrente) -> on récupère simplement son id.
    row = conn.execute("SELECT id FROM companies WHERE siren = ?", (data["siren"],)).fetchone()
    return row["id"]
    return cur.lastrowid


def add_contact(conn, company_id, contact):
    cur = conn.execute(
        """INSERT INTO contacts (company_id, email, first_name, last_name, position,
           department, confidence, source) VALUES (?,?,?,?,?,?,?,?)""",
        (
            company_id, contact.get("email"), contact.get("first_name"),
            contact.get("last_name"), contact.get("position"), contact.get("department"),
            contact.get("confidence"), contact.get("source"),
        ),
    )
    return cur.lastrowid


def add_draft(conn, company_id, contact_id, subject, body, template_used,
              parent_draft_id=None, followup_number=0):
    cur = conn.execute(
        """INSERT INTO drafts (company_id, contact_id, subject, body, status,
           template_used, parent_draft_id, followup_number, created_at)
           VALUES (?,?,?,?, 'draft', ?,?,?,?)""",
        (
            company_id, contact_id, subject, body, template_used,
            parent_draft_id, followup_number, datetime.utcnow().isoformat(),
        ),
    )
    return cur.lastrowid


def get_contact_by_domain(conn, domain):
    """
    Contact déjà connu pour ce domaine (retrouvé lors d'une recherche
    précédente OU plus tôt dans la même recherche) — évite de rappeler
    Hunter.io/GetProspect une seconde fois pour un domaine déjà résolu
    (plusieurs filiales d'un même groupe partagent souvent le même domaine
    et donc le même contact) : ça économise des crédits ET prépare la
    fusion faite par get_draft_by_contact_email ci-dessous, puisque
    réutiliser le même contact donne mécaniquement le même email.
    """
    if not domain:
        return None
    row = conn.execute(
        """SELECT ct.email, ct.first_name, ct.last_name, ct.position,
                  ct.department, ct.confidence, ct.source
           FROM contacts ct JOIN companies c ON c.id = ct.company_id
           WHERE c.domain = ? AND ct.email IS NOT NULL
           ORDER BY ct.id DESC LIMIT 1""",
        (domain,),
    ).fetchone()
    return dict(row) if row else None


def get_draft_by_contact_email(conn, email):
    """
    Le brouillon le plus récent déjà créé pour ce contact (email), tous
    statuts confondus — sert à fusionner un nouveau site qui partage le
    même contact au lieu de créer un doublon (voir add_merged_site)."""
    if not email:
        return None
    return conn.execute(
        """SELECT d.* FROM drafts d JOIN contacts c ON c.id = d.contact_id
           WHERE c.email = ? ORDER BY d.created_at DESC LIMIT 1""",
        (email,),
    ).fetchone()


def add_merged_site(conn, draft_id, site):
    """Ajoute un site (entreprise/ville + ses signaux France Travail) à la
    liste merged_sites d'un brouillon existant, au lieu de créer un nouveau
    brouillon pour ce site."""
    row = conn.execute("SELECT merged_sites FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    sites = json.loads(row["merged_sites"]) if row and row["merged_sites"] else []
    sites.append(site)
    conn.execute("UPDATE drafts SET merged_sites = ? WHERE id = ?", (json.dumps(sites), draft_id))


DRAFT_SELECT = """SELECT d.*, c.name AS company_name, c.city, c.domain, c.siret,
                  c.industry, c.employee_count, c.short_description,
                  c.hiring_signal, c.hiring_offers_count,
                  c.employer_page_found, c.employer_page_badges,
                  c.employer_page_labels, c.employer_page_avantages,
                  c.lbb_hiring_potential, c.lbb_is_high_potential,
                  ct.email AS contact_email, ct.first_name, ct.last_name, ct.position
           FROM drafts d
           JOIN companies c ON c.id = d.company_id
           LEFT JOIN contacts ct ON ct.id = d.contact_id"""


def list_drafts(conn, status=None, page=None, page_size=None):
    """
    `page`/`page_size` sont optionnels (None = comportement d'avant, tout
    remonter d'un coup — utilisé par ex. par les tests) ; le tableau de bord
    passe toujours les deux pour ne pas tout recharger d'un coup quand il y a
    beaucoup de candidatures (voir index() dans app.py).
    """
    q = DRAFT_SELECT
    params = []
    if status:
        q += " WHERE d.status = ?"
        params.append(status)
    q += " ORDER BY d.created_at DESC"
    if page and page_size:
        q += " LIMIT ? OFFSET ?"
        params += [page_size, (page - 1) * page_size]
    return conn.execute(q, params).fetchall()


def get_draft(conn, draft_id):
    return conn.execute(DRAFT_SELECT + " WHERE d.id = ?", (draft_id,)).fetchone()


def update_draft(conn, draft_id, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [draft_id]
    conn.execute(f"UPDATE drafts SET {cols} WHERE id = ?", values)


def mark_sent(conn, draft_id, message_id=None):
    conn.execute(
        "UPDATE drafts SET status = 'sent', sent_at = ?, message_id = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), message_id, draft_id),
    )


def mark_replied(conn, draft_id, replied_at, reply_snippet):
    conn.execute(
        "UPDATE drafts SET status = 'replied', replied_at = ?, reply_snippet = ? WHERE id = ?",
        (replied_at, reply_snippet, draft_id),
    )


def company_has_draft(conn, company_id):
    """
    True si cette entreprise a déjà au moins un brouillon (quel que soit son
    statut) — sert à éviter de recréer un doublon quand une recherche
    retombe sur une entreprise déjà traitée lors d'une recherche précédente.
    """
    row = conn.execute(
        "SELECT 1 FROM drafts WHERE company_id = ? LIMIT 1", (company_id,)
    ).fetchone()
    return row is not None


def update_company_enrichment(conn, company_id, industry=None, employee_count=None, short_description=None):
    """Enregistre les infos entreprise récupérées via Apollo.io (organizations/enrich)."""
    conn.execute(
        """UPDATE companies SET industry = ?, employee_count = ?, short_description = ?,
           apollo_enriched_at = ? WHERE id = ?""",
        (industry, employee_count, short_description, datetime.utcnow().isoformat(), company_id),
    )


def update_company_hiring_signal(conn, company_id, offers_count):
    """Enregistre le résultat d'une vérification France Travail : `offers_count`
    est le nombre d'offres actuellement publiées par cette entreprise (0 si
    aucune) — voir services/france_travail.py."""
    conn.execute(
        """UPDATE companies SET hiring_signal = ?, hiring_offers_count = ?,
           hiring_checked_at = ? WHERE id = ?""",
        (1 if offers_count else 0, offers_count, datetime.utcnow().isoformat(), company_id),
    )


def update_company_employer_page(conn, company_id, page):
    """Enregistre le résultat d'une vérification "page employeur" France
    Travail — `page` est None si l'entreprise n'en a pas, ou un dict
    {badges, labels, avantages} (voir france_travail.get_employer_page)."""
    conn.execute(
        """UPDATE companies SET employer_page_found = ?, employer_page_badges = ?,
           employer_page_labels = ?, employer_page_avantages = ?,
           employer_page_checked_at = ? WHERE id = ?""",
        (
            1 if page else 0,
            json.dumps(page.get("badges", [])) if page else None,
            json.dumps(page.get("labels", [])) if page else None,
            json.dumps(page.get("avantages", [])) if page else None,
            datetime.utcnow().isoformat(),
            company_id,
        ),
    )


def update_company_hiring_potential(conn, company_id, potential):
    """Enregistre le résultat d'une vérification "La Bonne Boîte" — `potential`
    est None si l'entreprise n'a pas de score calculé (ou est absente de La
    Bonne Boîte), ou un dict {hiring_potential, is_high_potential} (voir
    france_travail.get_hiring_potential)."""
    conn.execute(
        """UPDATE companies SET lbb_hiring_potential = ?, lbb_is_high_potential = ?,
           lbb_checked_at = ? WHERE id = ?""",
        (
            potential.get("hiring_potential") if potential else None,
            (1 if potential.get("is_high_potential") else 0) if potential else None,
            datetime.utcnow().isoformat(),
            company_id,
        ),
    )


def delete_company_and_drafts(conn, company_id):
    """
    Supprime une entreprise et tout ce qui s'y rattache (contacts, brouillons
    — les relances ont le même company_id que la candidature d'origine).
    """
    conn.execute("DELETE FROM drafts WHERE company_id = ?", (company_id,))
    conn.execute("DELETE FROM contacts WHERE company_id = ?", (company_id,))
    conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))


def log_api_call(conn, provider):
    """Enregistre un appel à un fournisseur de contacts (hunter/getprospect),
    pour pouvoir calculer la consommation du quota mensuel."""
    conn.execute(
        "INSERT INTO api_usage (provider, called_at) VALUES (?, ?)",
        (provider, datetime.utcnow().isoformat()),
    )


def count_api_calls_this_month(conn, provider):
    month_start = datetime.utcnow().strftime("%Y-%m") + "-01"
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM api_usage WHERE provider = ? AND called_at >= ?",
        (provider, month_start),
    ).fetchone()
    return row["n"]


def count_sent_today(conn):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM drafts WHERE status = 'sent' AND sent_at >= ?",
        (today,),
    ).fetchone()
    return row["n"]


def counts_by_status(conn):
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM drafts GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


def list_unreplied_sent(conn):
    """
    Tous les mails envoyés sans réponse enregistrée — utilisé pour la
    vérification des réponses (peu importe qu'une relance ait déjà été
    générée ou non, on veut simplement savoir si quelqu'un a répondu).
    """
    q = DRAFT_SELECT + " WHERE d.status = 'sent' AND d.replied_at IS NULL ORDER BY d.sent_at ASC"
    return conn.execute(q).fetchall()


def list_followup_candidates(conn, days_threshold):
    """
    Candidatures envoyées, sans réponse, envoyées il y a au moins
    `days_threshold` jours, et pour lesquelles aucune relance n'a encore
    été générée (pas de brouillon enfant) — ce sont les seules pour
    lesquelles proposer "Générer une relance".
    """
    q = DRAFT_SELECT + """
        WHERE d.status = 'sent'
          AND d.replied_at IS NULL
          AND d.sent_at <= datetime('now', ?)
          AND NOT EXISTS (SELECT 1 FROM drafts child WHERE child.parent_draft_id = d.id)
        ORDER BY d.sent_at ASC
    """
    return conn.execute(q, (f"-{days_threshold} days",)).fetchall()
