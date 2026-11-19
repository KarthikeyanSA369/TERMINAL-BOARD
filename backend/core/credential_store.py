"""
SYSFIX Secure Credential Store
Provides military-grade credential protection using the Windows Data Protection API (DPAPI).
Tied directly to the current Windows user profile with zero external pip dependencies.
Secrets are never written to SQLite, logs, source code, or frontend responses.
"""

import os
import sys
import ctypes
import ctypes.wintypes
import logging
import json
from typing import Optional, Dict, Any

logger = logging.getLogger("SYSFIX.CredentialStore")


def _get_vault_path() -> str:
    """Retrieve isolated vault file path in LocalAppData or test override."""
    override = os.environ.get("TERMINAL_BOARD_VAULT_PATH") or os.environ.get("SYSFIX_VAULT_PATH")
    if override:
        os.makedirs(os.path.dirname(os.path.abspath(override)), exist_ok=True)
        return override

    app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if app_data:
        target_dir = os.path.join(app_data, "TerminalBoard")
        legacy_dir = os.path.join(app_data, "SYSFIX")
        os.makedirs(target_dir, exist_ok=True)
        new_vault = os.path.join(target_dir, "smtp_vault.dat")
        legacy_vault = os.path.join(legacy_dir, "smtp_vault.dat")
        if not os.path.exists(new_vault) and os.path.exists(legacy_vault):
            try:
                import shutil
                shutil.copy2(legacy_vault, new_vault)
            except Exception:
                return legacy_vault
        return new_vault
    else:
        target_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        os.makedirs(target_dir, exist_ok=True)
        return os.path.join(target_dir, "smtp_vault.dat")


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char))
    ]


def _encrypt_dpapi(plaintext: str) -> bytes:
    """Encrypt plaintext string using Windows DPAPI CryptProtectData."""
    if sys.platform != "win32":
        # Fallback for mocked/non-windows environments
        return plaintext.encode("utf-8")

    data_bytes = plaintext.encode("utf-8")
    in_blob = _DATA_BLOB(
        len(data_bytes),
        ctypes.cast(ctypes.create_string_buffer(data_bytes), ctypes.POINTER(ctypes.c_char))
    )
    out_blob = _DATA_BLOB()
    
    # CryptProtectData: flags=0, description="SYSFIX_SMTP_SECRET"
    success = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "SYSFIX_SMTP_SECRET",
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob)
    )
    if not success:
        raise RuntimeError("Windows DPAPI CryptProtectData failed to encrypt secret.")

    try:
        ciphertext = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return ciphertext
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _decrypt_dpapi(ciphertext: bytes) -> str:
    """Decrypt ciphertext bytes using Windows DPAPI CryptUnprotectData."""
    if sys.platform != "win32":
        # Fallback for mocked/non-windows environments
        return ciphertext.decode("utf-8")

    in_blob = _DATA_BLOB(
        len(ciphertext),
        ctypes.cast(ctypes.create_string_buffer(ciphertext), ctypes.POINTER(ctypes.c_char))
    )
    out_blob = _DATA_BLOB()

    success = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob)
    )
    if not success:
        raise RuntimeError("Windows DPAPI CryptUnprotectData failed to decrypt secret.")

    try:
        plaintext = ctypes.string_at(out_blob.pbData, out_blob.cbData).decode("utf-8")
        return plaintext
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def store_smtp_credentials(username: str, password: str) -> bool:
    """Securely encrypt and store the SMTP username and password in Windows DPAPI vault with round-trip verification."""
    clean_pwd = str(password).strip() if password is not None else ""
    if not clean_pwd:
        return False
    clean_user = (username or "").strip()
    try:
        vault_path = _get_vault_path()
        payload = json.dumps({"username": clean_user, "password": clean_pwd})
        encrypted_bytes = _encrypt_dpapi(payload)
        with open(vault_path, "wb") as f:
            f.write(encrypted_bytes)

        # Immediate round-trip verification: read back and decrypt to verify integrity
        with open(vault_path, "rb") as f:
            test_bytes = f.read()
        decrypted_text = _decrypt_dpapi(test_bytes)
        parsed = json.loads(decrypted_text)
        if not isinstance(parsed, dict) or parsed.get("password") != clean_pwd:
            raise RuntimeError("DPAPI round-trip verification failed: decrypted credential does not match.")

        logger.info("SMTP credentials securely persisted and verified in Windows DPAPI vault.")
        return True
    except Exception as e:
        logger.error(f"Failed to persist or verify secure credential: {e}")
        return False


def save_smtp_password(password: str) -> bool:
    """Securely encrypt and store password (legacy compatibility)."""
    return store_smtp_credentials("", password)


def retrieve_smtp_credentials() -> Dict[str, str]:
    """Retrieve and decrypt the SMTP credentials from the secure vault or environment variables."""
    creds = {"username": "", "password": ""}
    vault_path = _get_vault_path()
    if os.path.isfile(vault_path):
        try:
            with open(vault_path, "rb") as f:
                encrypted_bytes = f.read()
            if encrypted_bytes:
                plaintext = _decrypt_dpapi(encrypted_bytes)
                try:
                    parsed = json.loads(plaintext)
                    if isinstance(parsed, dict):
                        creds["username"] = (parsed.get("username") or "").strip()
                        creds["password"] = (parsed.get("password") or "").strip()
                except Exception:
                    creds["password"] = (plaintext or "").strip()
        except Exception as e:
            logger.error(f"Failed to decrypt SMTP credentials from vault ({vault_path}): {e}")

    # Fallback to environment variables if vault fields are empty
    if not creds.get("username"):
        env_user = os.environ.get("SYSFIX_SMTP_USERNAME") or os.environ.get("SMTP_USERNAME") or os.environ.get("GMAIL_ADDRESS") or os.environ.get("GMAIL_USER")
        if env_user:
            creds["username"] = env_user.strip()

    if not creds.get("password"):
        env_pwd = os.environ.get("SYSFIX_SMTP_PASSWORD") or os.environ.get("SMTP_PASSWORD") or os.environ.get("GMAIL_APP_PASSWORD") or os.environ.get("SMTP_APP_PASSWORD")
        if env_pwd:
            creds["password"] = env_pwd.strip()

    return creds


def get_smtp_password() -> Optional[str]:
    """Retrieve and decrypt the SMTP authentication password."""
    creds = retrieve_smtp_credentials()
    return creds.get("password") or None


def has_smtp_credentials() -> bool:
    """Check if verified, decryptable SMTP credentials exist in the secure vault or environment variables."""
    creds = retrieve_smtp_credentials()
    return bool(creds.get("password"))


has_smtp_password = has_smtp_credentials


def delete_smtp_credentials() -> bool:
    """Securely purge the encrypted SMTP credentials from disk."""
    vault_path = _get_vault_path()
    if os.path.isfile(vault_path):
        try:
            os.remove(vault_path)
            logger.info("SMTP credentials removed from secure vault.")
            return True
        except Exception as e:
            logger.error(f"Failed to remove SMTP vault: {e}")
            return False
    return True


delete_smtp_password = delete_smtp_credentials


def mask_secret(secret: Optional[str]) -> str:
    """Safely mask a secret string for UI presentation (8 dots)."""
    if not secret:
        return ""
    return "••••••••"


mask_password = mask_secret


