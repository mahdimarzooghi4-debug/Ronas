"""Explicit LOCAL/TEST-only Keycloak BFF ASGI entrypoint.

Importing this module without all required settings fails before it can serve.
Never use in Stage/Production; TLS, HTTPS callback, private files and
self-hosted Keycloak must be independently supplied by the local operator.
"""
from ronas_api.local_keycloak_bff import create_from_environment

app = create_from_environment()
