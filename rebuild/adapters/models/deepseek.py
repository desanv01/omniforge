"""Direct HTTPS, explicit credential injection, no redirect/proxy/env fallback."""
import http.client
import json
import socket
import ssl

from adapters.secrets.store import CredentialRef, SecretValue


class ProviderFailure(Exception):
    CODES = {"provider_auth", "provider_rate_limit", "provider_timeout", "provider_balance",
             "provider_unavailable", "invalid_schema", "unsupported", "tool_failure",
             "forbidden", "budget", "canceled", "credential_missing", "credential_denied",
             "credential_unavailable", "credential_unsupported", "credential_storage"}

    def __init__(self, code):
        self.code = code if code in self.CODES else "provider_unavailable"
        super().__init__(self.code)


def validate_profile(profile):
    # Exact allowlist; no userinfo, query, fragments, redirects, custom hosts/ports.
    if profile.endpoint != "https://api.deepseek.com/chat/completions":
        raise ProviderFailure("forbidden")
    if (type(profile.revision) is not int or profile.revision < 1
            or not isinstance(profile.model, str) or not 1 <= len(profile.model) <= 128
            or any(ord(c) < 33 or ord(c) > 126 for c in profile.model)
            or not isinstance(profile.credential_ref, CredentialRef)):
        raise ProviderFailure("forbidden")
    # Revalidate even a bypassed frozen reference before any store read.
    CredentialRef(profile.credential_ref.value)


class DeepSeekHTTPS:
    def complete(self, profile, secret: SecretValue, payload, timeout):
        validate_profile(profile)
        connection = http.client.HTTPSConnection("api.deepseek.com", timeout=timeout,
                                                context=ssl.create_default_context())
        try:
            key = secret.reveal().decode("ascii")
            if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
                raise ProviderFailure("provider_auth")
            connection.request("POST", "/chat/completions", json.dumps(payload).encode(),
                               {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                raise ProviderFailure({401: "provider_auth", 403: "provider_auth",
                    402: "provider_balance", 429: "provider_rate_limit", 400: "invalid_schema",
                    422: "invalid_schema"}.get(response.status, "provider_unavailable"))
            raw = response.read(1048577)
            if len(raw) > 1048576:
                raise ProviderFailure("invalid_schema")
            return json.loads(raw)
        except ProviderFailure:
            raise
        except (socket.timeout, TimeoutError):
            raise ProviderFailure("provider_timeout") from None
        except (ValueError, UnicodeError):
            raise ProviderFailure("invalid_schema") from None
        except Exception:
            raise ProviderFailure("provider_unavailable") from None
        finally:
            connection.close()
