"""Security and trust primitives for QMR.CO.

This module intentionally uses only the Python standard library. SecureStorage
is a compress-first protected storage placeholder, not production-grade
encryption. Real encryption requires a future approved crypto dependency.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import zlib
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping


DEFAULT_STORAGE_KEY_ID = "development-placeholder"
_DEFAULT_STORAGE_KEY = b"qmr.co-development-storage-placeholder"


@dataclass(frozen=True)
class AuditEntry:
    """A safe-to-view audit event."""

    timestamp: str
    event_type: str
    message: str
    details: dict[str, object]


@dataclass(frozen=True)
class ValidatedConfig:
    """Validated safe startup configuration."""

    privacy_logging: str
    storage_mode: str
    live_trading_enabled: bool


class SecureStorage:
    """Compress-first protected storage placeholder.

    This class prevents direct plaintext storage and provides tamper detection,
    but it is not production encryption. Do not use it for production secrets
    until a real crypto dependency is approved.
    """

    def __init__(self, key: bytes | None = None, key_id: str = DEFAULT_STORAGE_KEY_ID) -> None:
        """Create a standard-library protected storage helper."""
        self.key = key or _DEFAULT_STORAGE_KEY
        self.key_id = key_id

    def protect(self, data: str, key_id: str | None = None) -> str:
        """Compress and protect data for storage without storing raw plaintext."""
        compressed = zlib.compress(data.encode("utf-8"))
        encoded_data = base64.b64encode(compressed).decode("ascii")
        digest = hmac.new(self.key, compressed, hashlib.sha256).hexdigest()
        payload = {
            "version": 1,
            "key_id": key_id or self.key_id,
            "protection": "standard-library-compressed-placeholder",
            "data": encoded_data,
            "digest": digest,
        }
        return base64.b64encode(json.dumps(payload, sort_keys=True).encode("utf-8")).decode("ascii")

    def reveal(self, payload: str) -> str:
        """Reveal protected data only when explicitly requested."""
        try:
            raw_payload = base64.b64decode(payload.encode("ascii"))
            metadata = json.loads(raw_payload.decode("utf-8"))
            compressed = base64.b64decode(str(metadata["data"]).encode("ascii"))
            expected_digest = str(metadata["digest"])
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid protected storage payload.") from exc

        actual_digest = hmac.new(self.key, compressed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(actual_digest, expected_digest):
            raise ValueError("Protected storage payload failed integrity validation.")
        return zlib.decompress(compressed).decode("utf-8")


class SecretManager:
    """Load and validate secrets without printing or exposing values."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        """Create a secret manager backed by environment-style values."""
        self.env = env if env is not None else os.environ

    def require(self, names: list[str]) -> dict[str, str]:
        """Return required secrets or raise a redacted validation error."""
        missing = [name for name in names if not self.env.get(name)]
        if missing:
            raise ValueError(f"Missing required secret(s): {', '.join(missing)}.")
        return {name: self.env[name] for name in names}

    def redacted_environment(self, names: list[str]) -> dict[str, str]:
        """Return secret presence without exposing secret values."""
        return {name: "<set>" if self.env.get(name) else "<missing>" for name in names}


class PrivacyFilter:
    """Redact private values from logs, errors, dashboards, and exports."""

    _email_pattern = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
    _ipv4_pattern = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    _token_assignment_pattern = re.compile(
        r"(?i)\b(api[_-]?key|token|secret|password|credential|broker[_-]?key|account[_-]?id|tax[_-]?id)\b\s*[:=]\s*[^,\s;]+"
    )
    _bearer_pattern = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")

    def redact(self, text: str) -> str:
        """Return text with sensitive values removed."""
        redacted = self._email_pattern.sub("<redacted-email>", text)
        redacted = self._ipv4_pattern.sub("<redacted-ip>", redacted)
        redacted = self._token_assignment_pattern.sub(lambda match: f"{match.group(1)}=<redacted>", redacted)
        redacted = self._bearer_pattern.sub("Bearer <redacted>", redacted)
        return redacted

    def redact_mapping(self, values: Mapping[str, object]) -> dict[str, object]:
        """Return a mapping with sensitive keys and values redacted."""
        return {str(key): self._redact_value(str(key), value) for key, value in values.items()}

    def _redact_value(self, key: str, value: object) -> object:
        """Redact one value based on key and content."""
        if _is_sensitive_key(key):
            return "<redacted>"
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, Mapping):
            return self.redact_mapping(value)
        if isinstance(value, list):
            return [self._redact_value(key, item) for item in value]
        return value


class AuditLogger:
    """Record safe platform events without leaking private data."""

    def __init__(self, privacy_filter: PrivacyFilter | None = None) -> None:
        """Create an in-memory safe audit logger."""
        self.privacy_filter = privacy_filter or PrivacyFilter()
        self._entries: list[AuditEntry] = []

    def record(self, event_type: str, message: str, details: Mapping[str, object] | None = None) -> None:
        """Record a redacted audit event."""
        self._entries.append(
            AuditEntry(
                timestamp=datetime.now().isoformat(timespec="seconds"),
                event_type=self.privacy_filter.redact(event_type),
                message=self.privacy_filter.redact(message),
                details=self.privacy_filter.redact_mapping(details or {}),
            )
        )

    def entries(self) -> list[AuditEntry]:
        """Return safe audit entries."""
        return list(self._entries)


class ConfigValidator:
    """Validate safe startup configuration."""

    _broker_keys = {
        "broker_api_key",
        "broker_secret",
        "broker_token",
        "robinhood_username",
        "robinhood_password",
    }

    def __init__(self, secret_manager: SecretManager | None = None) -> None:
        """Create a validator with optional secret validation support."""
        self.secret_manager = secret_manager or SecretManager()

    def validate(self, config: Mapping[str, object]) -> ValidatedConfig:
        """Validate config using safe defaults and fail-closed rules."""
        if bool(config.get("live_trading_enabled", False)):
            raise ValueError("Unsafe config: live trading is not supported.")

        present_broker_keys = [key for key in self._broker_keys if config.get(key)]
        if present_broker_keys:
            raise ValueError(f"Unsafe config: broker secrets are not supported: {', '.join(sorted(present_broker_keys))}.")

        required_secrets = config.get("required_secrets", [])
        if required_secrets:
            if not isinstance(required_secrets, list) or not all(isinstance(item, str) for item in required_secrets):
                raise ValueError("Unsafe config: required_secrets must be a list of names.")
            self.secret_manager.require(required_secrets)

        privacy_logging = str(config.get("privacy_logging", "redacted"))
        if privacy_logging != "redacted":
            raise ValueError("Unsafe config: privacy_logging must be redacted.")

        storage_mode = str(config.get("storage_mode", "protected"))
        if storage_mode != "protected":
            raise ValueError("Unsafe config: storage_mode must be protected.")

        return ValidatedConfig(
            privacy_logging=privacy_logging,
            storage_mode=storage_mode,
            live_trading_enabled=False,
        )


def _is_sensitive_key(key: str) -> bool:
    """Return whether a mapping key should be fully redacted."""
    normalized = key.lower().replace("-", "_")
    sensitive_terms = (
        "api_key",
        "token",
        "secret",
        "password",
        "credential",
        "account_id",
        "tax_id",
        "broker",
        "email",
        "ip",
    )
    return any(term in normalized for term in sensitive_terms)
