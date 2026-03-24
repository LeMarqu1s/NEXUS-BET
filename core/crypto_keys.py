"""
NEXUS BET - Chiffrement AES-256 (Fernet) des clés privées utilisateurs.
Les clés ne transitent jamais en clair dans les logs.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    """Retourne une instance Fernet depuis NEXUS_ENCRYPTION_KEY."""
    raw = os.getenv("NEXUS_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise ValueError(
            "NEXUS_ENCRYPTION_KEY manquante — génère avec : "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(raw.encode())


def encrypt_key(private_key: str) -> str:
    """Chiffre une clé privée. Retourne le token Base64 chiffré."""
    f = _get_fernet()
    encrypted = f.encrypt(private_key.encode()).decode()
    log.debug("Key encrypted (length=%d)", len(encrypted))
    return encrypted


def decrypt_key(encrypted_key: str) -> str:
    """Déchiffre une clé privée. Lève InvalidToken si la clé est corrompue."""
    f = _get_fernet()
    return f.decrypt(encrypted_key.encode()).decode()


def is_encryption_available() -> bool:
    """Vérifie si NEXUS_ENCRYPTION_KEY est configurée."""
    return bool(os.getenv("NEXUS_ENCRYPTION_KEY", "").strip())


async def get_user_clob_client(telegram_id: int):
    """
    Récupère le ClobClient Polymarket d'un utilisateur depuis Supabase.
    Déchiffre la clé en mémoire seulement — ne log jamais la clé brute.
    Retourne None si l'utilisateur n'a pas de clé configurée.
    """
    import httpx
    from py_clob_client.client import ClobClient

    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        log.warning("get_user_clob_client: Supabase non configuré")
        return None

    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(
                f"{url}/rest/v1/users",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                params={"telegram_chat_id": f"eq.{telegram_id}", "select": "polymarket_private_key_enc"},
            )
            if r.status_code != 200 or not r.json():
                return None
            row = r.json()[0]
    except Exception as e:
        log.error("get_user_clob_client: Supabase fetch failed: %s", e)
        return None

    enc_key: Optional[str] = row.get("polymarket_private_key_enc")
    if not enc_key:
        return None

    try:
        private_key = decrypt_key(enc_key)
    except (InvalidToken, Exception) as e:
        log.error("get_user_clob_client: decrypt failed for user %s: %s", telegram_id, type(e).__name__)
        return None

    try:
        from data.polymarket_client import _sanitize_private_key
        private_key = _sanitize_private_key(private_key)
        client = ClobClient(
            host="https://clob.polymarket.com",
            key=private_key,
            chain_id=137,
        )
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
    except Exception as e:
        log.error("get_user_clob_client: ClobClient init failed: %s", e)
        return None
    finally:
        # Efface la clé brute de la mémoire locale
        private_key = None  # noqa: F841

    return client
