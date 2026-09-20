# syntax=docker/dockerfile:1

# =============================================================================
# Image d'exécution du bot Telegram (Python / aiogram + Flask + keep-alive)
# -----------------------------------------------------------------------------
# Même principe que le projet précédent : un entrypoint qui détecte le port
# (variable PORT), un HEALTHCHECK, et des permissions d'écriture larges pour
# les plateformes qui lancent le conteneur avec un utilisateur non-root.
# =============================================================================
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# curl + ca-certificates : health-check et requêtes HTTPS du keep-alive
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Dépendances Python du bot
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Code de l'application
COPY istidafa4_by_moon.py keepalive.py ./
COPY .env.example ./.env.example

# Script d'entrée : détecte automatiquement le port d'écoute
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# --- Permissions d'écriture ------------------------------------------------
# L'appli doit pouvoir écrire dans /app/data : detected-host.json, scripts
# des utilisateurs, et bibliothèques installées à la demande par le bot
# (pip --user, car le site-packages système n'est pas inscriptible en non-root).
# Ces variables sont définies APRÈS l'installation des dépendances ci-dessus.
ENV DATA_DIR=/app/data \
    HOME=/app/data/home \
    PYTHONUSERBASE=/app/data/.local \
    PIP_USER=1
RUN mkdir -p /app/data/scripts /app/data/home /app/data/.local \
    && chmod -R a+rwX /app

# Le port réel est déterminé dynamiquement (variable PORT), 8080 par défaut.
EXPOSE 8080

# Vérifie que le serveur web répond sur le port réellement utilisé
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD sh -c 'curl -fsS "http://127.0.0.1:${PORT:-8080}/health" || exit 1'

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "istidafa4_by_moon.py"]
