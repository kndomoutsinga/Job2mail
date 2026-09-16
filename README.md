# Job2Mail

Petit outil personnel (Flask + SQLite, 100% local) pour automatiser la partie
répétitive d'une recherche d'emploi par candidature spontanée : trouver des
entreprises actives dans un secteur/une zone, deviner leur site et un
contact, préparer un mail personnalisé, le relire, l'envoyer — et suivre les
réponses et les relances. Rien ne part jamais sans relecture explicite.

## Fonctionnalités

- **Recherche d'entreprises** par ville, code postal, département, région ou
  France entière, filtrée par codes NAF (ou recherche d'une entreprise
  précise par son nom) — via l'API publique et gratuite
  [recherche-entreprises.api.gouv.fr](https://recherche-entreprises.api.gouv.fr/docs/)
  (données Sirene), sans clé ni compte.
- **Détection automatique du site web** de chaque entreprise (heuristique à
  partir de sa raison sociale, vérifiée en direct).
- **Recherche de contact** (email, prénom/nom) via Hunter.io puis GetProspect
  en dernier recours, si les clés API correspondantes sont configurées.
- **Enrichissement entreprise** (secteur, effectif, description) via
  Apollo.io.
- **Signaux France Travail** (3 API gratuites, facultatives) pour prioriser
  les candidatures :
  - *recrute actuellement* — l'entreprise a des offres publiées en ce moment ;
  - *page employeur* — badges/labels/avantages mis en avant par l'entreprise
    elle-même sur France Travail ;
  - *fort potentiel d'embauche* — score 0-100 calculé par France Travail
    (via La Bonne Boîte) pour les 6 prochains mois, même sans offre publiée
    là maintenant.
- **Génération de mails** à partir de plusieurs modèles honnêtes (pas de
  fausses promesses type "CV en pièce jointe" quand il n'y en a pas), tirés
  au sort de façon stable par entreprise pour varier la formulation.
- **Pièce jointe optionnelle** par brouillon (CV, portfolio PDF...), ajoutée/
  retirée depuis la page du brouillon, façon Gmail.
- **Tableau de bord** : brouillons filtrables par statut (à relire, prêts,
  envoyés, réponses, écartés), paginé (25 par page), avec quotas d'envoi
  quotidien et quotas mensuels des fournisseurs de contacts configurés.
- **Suivi des réponses** par lecture IMAP de la boîte mail, et **relances
  automatiques** proposées après un délai configurable sans réponse.
- **Rien n'est envoyé automatiquement** : la recherche ne fait que créer des
  brouillons ; chaque envoi est un clic explicite, avec confirmation.

## Installation

```bash
git clone <url-de-votre-dépôt>
cd job2mail_kaprisky
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

Copiez ensuite `.env.example` en `.env` et remplissez vos propres valeurs
(voir la section suivante) :

```bash
copy .env.example .env        # Windows
# cp .env.example .env        # macOS/Linux
```

Puis lancez l'appli :

```bash
python app.py
```

Elle est accessible sur <http://127.0.0.1:5000>.

## Configuration (`.env`)

Toutes les variables sont détaillées avec leurs valeurs par défaut dans
`.env.example`. Résumé :

| Variable | Obligatoire ? | Rôle |
|---|---|---|
| `SENDER_EMAIL`, `SENDER_APP_PASSWORD`, `SENDER_NAME`, `SENDER_PHONE`, `SENDER_PORTFOLIO` | Oui, pour envoyer | Identité et mot de passe d'application Gmail (voir [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)) |
| `HUNTER_API_KEY`, `GETPROSPECT_API_KEY`, `APOLLO_API_KEY` | Non | Recherche/enrichissement de contacts — sans elles, l'appli fonctionne, juste sans cette étape |
| `FRANCE_TRAVAIL_CLIENT_ID`, `FRANCE_TRAVAIL_CLIENT_SECRET` | Non | Les 3 signaux France Travail décrits ci-dessus — compte gratuit sur [francetravail.io](https://francetravail.io) |
| `DAILY_SEND_LIMIT` | Non (défaut 30) | Sécurité anti-spam Gmail : max de candidatures envoyées par jour |
| `FOLLOWUP_DAYS` | Non (défaut 14) | Délai sans réponse avant proposition de relance |
| `MAX_ATTACHMENT_SIZE_MB` | Non (défaut 10) | Taille max d'une pièce jointe |

**Important :** le fichier `.env` contient vos vrais mots de passe/clés — il
est exclu de Git par `.gitignore` et ne doit **jamais** être poussé sur un
dépôt, même privé.

## Structure du projet

```
job2mail_kaprisky/
├── app.py                  # Routes Flask
├── models.py                # Schéma SQLite, migrations, requêtes
├── config.py                # Lecture du .env, valeurs par défaut
├── services/
│   ├── sirene.py             # Recherche d'entreprises (Sirene)
│   ├── domain_guess.py       # Détection du site web
│   ├── contact_finder.py     # Enchaîne Hunter.io -> GetProspect
│   ├── hunter.py / getprospect.py / apollo.py
│   ├── france_travail.py     # 3 API France Travail (v. ci-dessus)
│   ├── geo.py                 # Nom de département/région -> code INSEE
│   ├── email_templates.py    # Génération des mails
│   └── mailer.py              # Envoi SMTP + pièce jointe
├── templates/                # Pages Jinja (tableau de bord, brouillon, recherche)
├── static/style.css
└── data/
    ├── job2mail.db            # Base SQLite (créée au premier lancement)
    └── attachments/           # Pièces jointes envoyées
```

## Limites connues / à garder en tête

- Les scopes OAuth2 exacts des API France Travail "Synthèse pages
  employeurs" et "La Bonne Boîte" ont été confirmés directement dans la
  documentation officielle (pas une supposition) — mais n'ont pas encore été
  validés par un vrai appel réussi. Si l'un des deux échoue à
  l'authentification, un avertissement apparaît sur le tableau de bord avec
  le détail de l'erreur.
- Les quotas mensuels (`HUNTER_MONTHLY_LIMIT`, `APOLLO_MONTHLY_LIMIT`,
  `GETPROSPECT_MONTHLY_LIMIT`) sont à ajuster à la main selon ce qu'affiche
  votre tableau de bord chez chaque fournisseur — l'appli ne les récupère
  pas automatiquement.
- Outil 100% local et personnel : pas d'authentification, pas conçu pour
  être exposé publiquement sur Internet tel quel.
