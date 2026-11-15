"""Credentials for NISAR data access (AWS STS temporary keys and Earthdata token)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .jsonio import read_json

log = logging.getLogger("nisar.credentials")

AWS_REGION = "us-west-2"


@dataclass(frozen=True)
class AwsCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str | None
    expiration: datetime | None

    @property
    def expired(self) -> bool:
        return self.expiration is not None and self.expiration <= datetime.now(timezone.utc)

    @classmethod
    def load(cls, path: Path) -> AwsCredentials | None:
        if not path.is_file():
            return None
        try:
            raw = read_json(path)
            exp = raw.get("expiration")
            return cls(
                access_key_id=raw["accessKeyId"],
                secret_access_key=raw["secretAccessKey"],
                session_token=raw.get("sessionToken"),
                expiration=datetime.fromisoformat(exp) if exp else None,
            )
        except (KeyError, ValueError) as exc:
            log.warning("Credenciales AWS inválidas en %s: %s", path.name, exc)
            return None


def check_sts_identity(creds: AwsCredentials | None) -> dict[str, Any]:
    """Validate temporary keys against AWS STS. Never raises."""
    if creds is None:
        return {"status": "missing"}
    if creds.expired:
        return {"status": "expired", "expiration": creds.expiration.isoformat()}
    try:
        import boto3

        identity = boto3.client(
            "sts",
            aws_access_key_id=creds.access_key_id,
            aws_secret_access_key=creds.secret_access_key,
            aws_session_token=creds.session_token,
            region_name=AWS_REGION,
        ).get_caller_identity()
        return {
            "status": "valid",
            "arn": identity.get("Arn"),
            "expiration": creds.expiration.isoformat() if creds.expiration else None,
        }
    except Exception as exc:  # network / auth errors are reported, not fatal
        return {"status": "error", "error": str(exc)}
