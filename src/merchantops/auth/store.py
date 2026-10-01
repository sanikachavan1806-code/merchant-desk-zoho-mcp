from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from merchantops.errors import ConfigError, UnauthorizedError
from merchantops.models import TokenSet


class TokenStore:
    def __init__(self, path: str | Path, encryption_key: str) -> None:
        if not encryption_key:
            raise ConfigError(
                "TOKEN_ENCRYPTION_KEY is required before a refresh token can be stored. "
                'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        try:
            self._fernet = Fernet(encryption_key.encode())
        except (ValueError, TypeError) as exc:
            raise ConfigError("TOKEN_ENCRYPTION_KEY is not a valid Fernet key.") from exc
        self.path = Path(path)

    def save(self, token: TokenSet) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        blob = self._fernet.encrypt(token.model_dump_json().encode())
        self.path.write_bytes(blob)

    def load(self) -> TokenSet | None:
        if not self.path.exists():
            return None
        try:
            raw = self._fernet.decrypt(self.path.read_bytes())
        except InvalidToken as exc:
            raise UnauthorizedError("Token store could not be decrypted with TOKEN_ENCRYPTION_KEY.") from exc
        return TokenSet.model_validate_json(raw)
