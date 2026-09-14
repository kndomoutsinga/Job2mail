# Job2Mail

Après des centaines de candidatures envoyées sans retour, j'ai fini par me dire que le problème n'était peut-être pas mon CV, mais l'endroit où je l'envoyais. Alors j'ai codé cet outil pour aller directement vers les entreprises, plutôt que d'attendre une offre publiée.

Ça fait cinq choses :

1. Récupère les entreprises actives dans une zone donnée via l'**API publique "Recherche d'entreprises"** (data.gouv.fr/Etalab, basée sur les données Sirene), filtrées par code NAF (activités dev/IT).
2. Essaie de deviner leur site web, cherche un contact (email, nom, poste) via **Hunter.io**, et récupère quelques infos publiques sur l'entreprise (secteur, effectif, description) via **Apollo.io**.
3. Génère un brouillon de mail de candidature spontanée personnalisé pour chaque entreprise où un contact a été trouvé.
4. Détecte automatiquement (via IMAP, sur ma propre boîte Gmail) quand un contact a répondu.
5. Repère les candidatures envoyées depuis plusieurs jours sans réponse et prépare un brouillon de relance.

Rien ne part automatiquement. Chaque brouillon, candidature initiale ou relance, reste en attente dans un tableau de bord. Je le relis, je le modifie si besoin, et j'envoie moi-même, un par un.

Interface entièrement en français, avec suivi des quotas API en temps réel (façon "vous avez atteint votre limite gratuite, revenez demain") pour ne jamais me faire surprendre par un compte bloqué en pleine recherche.

## Stack technique

- Python / Flask
- SQLite (suivi des entreprises, contacts, brouillons, statuts d'envoi, quotas API)
- API publique "Recherche d'entreprises" (data.gouv.fr) pour les données entreprises, gratuite et sans clé
- API Hunter.io pour trouver un contact (email/nom) à partir d'un domaine
- API Apollo.io pour enrichir la fiche entreprise (secteur, effectif, description)
- SMTP (Gmail) pour l'envoi, IMAP (même compte) pour détecter les réponses

## Installation

Python 3.9+ requis.

```bash
cd job2mail_kaprisky
python3 -m venv venv
source venv/bin/activate        # sous Windows : venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Copier `.env.example` en `.env` :

```bash
cp .env.example .env
```

Puis remplir dans `.env` :

### Recherche d'entreprises — rien à configurer

L'outil utilise l'API publique et gratuite [recherche-entreprises.api.gouv.fr](https://recherche-entreprises.api.gouv.fr/docs/) (mêmes données que le Sirene de l'INSEE), sans clé ni compte.

### Hunter.io — gratuit (quota mensuel limité), source principale de contacts

1. Compte sur https://hunter.io
2. Clé API sur https://hunter.io/api-keys
3. La coller dans `HUNTER_API_KEY`

Le plan gratuit partage un même quota entre recherche par domaine, recherche d'email et vérification (le nombre exact évolue selon les offres, à vérifier sur le tableau de bord Hunter). L'outil ne consomme un crédit que si un site web a été identifié pour l'entreprise.

### Apollo.io — enrichissement des fiches entreprise (secteur, effectif, description)

1. Compte sur https://apollo.io
2. Clé API dans Settings → API Keys, en cochant au minimum la permission `organizations/enrich`
3. La coller dans `APOLLO_API_KEY`

Sur le plan gratuit, seule la route d'enrichissement entreprise (`organizations/enrich`) est accessible par clé API. La recherche et la révélation de contacts (`mixed_people/api_search`, `people/match`) restent verrouillées, même en essayant plusieurs formats de paramètres. Cette partie du code existe toujours dans `services/apollo.py` au cas où l'offre évoluerait un jour, mais n'est pas utilisée par défaut. Laisser `APOLLO_API_KEY` vide désactive proprement cette fonctionnalité : juste une fiche entreprise moins détaillée, rien ne plante.

### GetProspect — prêt pour une future source de noms

1. Compte gratuit sur https://getprospect.com
2. Clé API dans les paramètres du compte
3. La coller dans `GETPROSPECT_API_KEY`

Particularité : contrairement à Hunter, GetProspect ne sait pas chercher "par domaine seul", il faut déjà avoir un prénom et un nom identifiés ailleurs. Cet étage est câblé et prêt (`services/contact_finder.py`) mais ne se déclenche pas tant qu'aucune autre source ne fournit ce nom.

### Adresse d'envoi et suivi des réponses (Gmail)

1. Activer la validation en 2 étapes sur le compte Gmail utilisé pour l'envoi
2. Générer un mot de passe d'application sur https://myaccount.google.com/apppasswords
3. Le coller dans `SENDER_APP_PASSWORD` (pas le mot de passe Gmail normal)
4. Vérifier que l'accès IMAP est activé sur le compte (Gmail → Voir tous les paramètres → Transfert et POP/IMAP → activer IMAP). C'est ce qui permet à l'outil de lire l'arrivée des réponses, en lecture seule, sans rien supprimer ni modifier.

Le même mot de passe d'application sert à la fois pour l'envoi (SMTP) et la lecture (IMAP), pas besoin d'en créer un deuxième.

### Quotas

Chaque fournisseur a une limite mensuelle réglable dans `.env` (`HUNTER_MONTHLY_LIMIT`, `APOLLO_MONTHLY_LIMIT`, `GETPROSPECT_MONTHLY_LIMIT`), plus une limite quotidienne d'envois (`DAILY_SEND_LIMIT`, sécurité anti-spam Gmail). Une fois une limite atteinte, l'outil arrête d'appeler ce fournisseur (ou bloque l'envoi) jusqu'à la période suivante et l'affiche clairement sur le tableau de bord, sans jamais planter la recherche en cours. Si le compteur interne ne correspond plus aux vrais chiffres affichés sur mes comptes (Hunter/Apollo/GetProspect), `scripts/synchroniser_quotas.py` permet de le recaler en une fois.

Le fichier `.env` reste en local, jamais commité, jamais partagé.

## Lancer l'outil

```bash
python app.py
```

Puis ouvrir http://localhost:5000

## Utilisation

1. "Nouvelle recherche" → choisir une ville (ou un code postal) et les activités à cibler.
2. L'outil crée des brouillons sur le tableau de bord pour chaque entreprise où un contact a été trouvé (les entreprises déjà traitées lors d'une recherche précédente sont ignorées, pas de doublons).
3. Ouvrir un brouillon, relire/modifier le texte, puis :
   - "Enregistrer" pour sauvegarder les modifications
   - "Marquer prêt" une fois satisfaite
   - "Envoyer" pour partir directement (confirmation demandée)
   - "Écarter" si cette candidature précise ne m'intéresse plus (garde l'historique)
   - "Supprimer l'entreprise" pour effacer complètement une entreprise qui ne m'intéresse pas du tout (entreprise, contacts et brouillons)
4. Sur le tableau de bord, le bouton "Vérifier les réponses" se connecte à ma boîte mail (IMAP) et marque automatiquement "répondu" les candidatures pour lesquelles un contact a écrit en retour, avec un extrait du message.
5. La section "Relances à faire" liste les candidatures envoyées depuis au moins `FOLLOWUP_DAYS` jours (7 par défaut, réglable dans `.env`) sans réponse. Un clic sur "Générer une relance" crée un nouveau brouillon plus court, qui référence la date du premier envoi ; comme les autres, il passe par la relecture avant de partir.

## Limites

Quelques trucs que je sais imparfaits, pour être honnête :

- La détection du site web est une estimation (nom d'entreprise → nom de domaine probable, vérifié par une requête HTTP). Ça rate parfois, surtout pour les petites structures ou les noms génériques. Dans ce cas, pas de brouillon créé pour cette entreprise, faute de contact possible automatiquement.
- Hunter.io ne trouve pas toujours un contact nommé, parfois juste un pattern d'adresse générique (contact@, recrutement@...) ou rien du tout.
- Les plans gratuits sont limités, pas la peine de lancer une recherche sur des centaines d'entreprises d'un coup.
- La recherche/révélation de contacts par Apollo n'est pas utilisable sur le plan gratuit (voir Configuration). Seul l'enrichissement de fiche entreprise l'est.
- La détection des réponses par IMAP travaille à la journée près, pas à l'heure près. Un mail reçu le même jour que l'envoi peut en théorie se confondre avec un mail plus ancien du même contact, mais c'est rare et sans grande conséquence en pratique.
- Pas de relance automatique en tâche de fond. Il faut ouvrir le tableau de bord et cliquer sur "Vérifier les réponses" / "Générer une relance" soi-même, rien ne se déclenche tout seul pendant que l'ordinateur est éteint.
- Les mails générés reprennent mon profil et mes formulations habituelles, mais je relis toujours avant d'envoyer.

## Données

Tout reste en local, dans `data/job2mail.db` (SQLite), créé automatiquement au premier lancement. Rien ne part vers un serveur externe autre que l'API Recherche d'entreprises, Hunter.io, Apollo.io et le serveur SMTP/IMAP au moment de l'envoi ou de la vérification.
