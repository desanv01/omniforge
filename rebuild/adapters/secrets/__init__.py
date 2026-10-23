"""Explicit, reference-only Windows credential storage; no automatic discovery."""

from .store import CredentialRef, SecretStore, SecretStoreError, SecretValue
from .windows import WindowsSecretStore

__all__ = ["CredentialRef", "SecretStore", "SecretStoreError", "SecretValue", "WindowsSecretStore"]
