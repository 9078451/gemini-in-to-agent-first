"""Plus de fils pour le serveur.

Chaque route synchrone et chaque flux SSE (app, tâches Cowork, API réseau) tient un fil
pendant qu'il attend. Par défaut, anyio en prête 40 : avec quelques fenêtres ouvertes
et un long message, l'app pouvait se figer. Les fils qui attendent ne coûtent presque rien.
"""
from contextlib import asynccontextmanager

import anyio.to_thread

FILS_SERVEUR = 200


@asynccontextmanager
async def plus_de_fils(_app):
    anyio.to_thread.current_default_thread_limiter().total_tokens = FILS_SERVEUR
    yield
