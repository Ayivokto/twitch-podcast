# Lives Twitch → Apple Podcasts (automatique, gratuit)

Chaque jour, GitHub Actions télécharge les nouvelles rediffusions d'une chaîne Twitch,
les convertit en audio, les range dans des Releases et met à jour `docs/feed.xml`,
publié par GitHub Pages.

## Mise en place (10 minutes, une seule fois)

1. **Créer le dépôt** : sur github.com → **New repository**, par exemple `twitch-podcast`,
   en **Public** (minutes d'Actions illimitées).
2. **Envoyer les fichiers** : **Add file → Upload files**, glisser le contenu de ce dossier
   (`twitch2podcast.py`, `README.md`, `.gitignore` et le dossier `.github`), puis **Commit**.
   > Le dossier `.github` est caché sous Windows : afficher les éléments masqués dans l'Explorateur.
3. **Choisir la chaîne** : **Settings → Secrets and variables → Actions → onglet Variables
   → New repository variable**
   - `TWITCH_CHANNEL` = le nom de la chaîne (ex. `zerator`)
   - facultatif : `MAX_VODS` = nombre de VODs récentes à vérifier (défaut 5)
4. **Premier lancement** : onglet **Actions** → « Mise à jour du podcast » → **Run workflow**.
   Attendre la coche verte (plusieurs minutes par live).
5. **Activer Pages** : **Settings → Pages** → Source **Deploy from a branch**,
   branche `main`, dossier `/docs` → **Save**.
6. **Ajouter dans Apple Podcasts** (iPhone) : **Bibliothèque → ⋯ → Suivre une émission par URL**
   `https://<ton-pseudo>.github.io/twitch-podcast/feed.xml`

Ensuite, tout se fait seul chaque matin.

## En cas de problème

- **Échec au téléchargement (erreur 403, « blocked »)** : Twitch bloque les serveurs de GitHub.
  Il faudra alors lancer le script depuis ton PC.
- **Live ignoré** : les lives encore en cours et les VODs réservées aux abonnés sont sautés.
- Les journaux détaillés sont dans l'onglet **Actions**, en cliquant sur une exécution.
