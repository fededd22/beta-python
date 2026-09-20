# istidafa4-by-moon

Bot Telegram (aiogram) pour héberger/exécuter des scripts Python, avec un
**keep-alive automatique** identique à celui du projet précédent.

## Fichiers
| Fichier | Rôle |
|---|---|
| `istidafa4_by_moon.py` | Le bot Telegram |
| `keepalive.py` | Serveur web (`/`, `/health`) + détection du domaine + ping automatique |
| `Dockerfile`, `docker-entrypoint.sh`, `docker-compose.yml` | Déploiement Docker |
| `requirements.txt`, `.env.example`, `.dockerignore` | Dépendances / configuration |

## Keep-alive automatique
- Le domaine public est détecté tout seul (en-têtes `X-Forwarded-Host` / `Host`
  de la première requête reçue) ou pris dans `APP_URL` s'il est défini.
- Toutes les 30 s, le bot appelle `https://<domaine>/health`.
- Logs : `[Keep-Alive] ✅ https://.../health (70ms)`.
- Tant qu'aucune requête publique n'est arrivée, le log indique
  `Public domain not detected yet` : ouvrez simplement l'URL du site une fois
  (ou définissez `APP_URL`).
- Le bouton admin « 🔄 État Keep-Alive » affiche le domaine, l'intervalle et le
  dernier ping (lecture seule, plus de configuration manuelle).

## Variables d'environnement
`TELEGRAM_BOT_TOKEN`, `ADMIN_IDS`, `APP_URL` (optionnel), `PORT` (auto),
`KEEP_ALIVE_INTERVAL` (défaut 30), `DATA_DIR` (défaut `/app/data`).

## Déploiement
```bash
docker compose up -d --build
```
Sur une plateforme (bata.bliz / blitz.cloud…) : déployez le dossier avec le
`Dockerfile` à la racine, définissez `TELEGRAM_BOT_TOKEN`, et si possible montez
un volume persistant sur `/app/data`.
