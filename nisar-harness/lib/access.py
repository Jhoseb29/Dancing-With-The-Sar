"""Open a NISAR HDF5 granule directly from the AWS archive - nothing is downloaded to disk.

Strategy chain (first that works wins):
    1. s3     - direct S3 with STS temporary keys (only works in-region, us-west-2)
    2. https  - HTTP range requests to the same S3 objects via ASF/CloudFront (Earthdata token)
Only the HDF5 chunks that cover the AOI are fetched.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import IO

import h5py
import requests

from .catalog import Granule
from .credentials import AWS_REGION, AwsCredentials
from .settings import Settings

log = logging.getLogger("nisar.access")

STREAM_BLOCK_SIZE = 8 * 1024 * 1024


@dataclass
class GranuleSource:
    granule_id: str
    s3_url: str | None = None
    https_url: str | None = None

    @classmethod
    def from_granule(cls, granule: Granule) -> GranuleSource:
        return cls(granule.granule_id, granule.s3_url, granule.https_url)


# ---------- openers: each returns a file-like object or raises ----------
Opener = Callable[[GranuleSource, Settings], IO[bytes]]


def _open_s3(src: GranuleSource, settings: Settings) -> IO[bytes]:
    creds = AwsCredentials.load(settings.aws_credentials_file)
    if not src.s3_url or creds is None or creds.expired:
        raise PermissionError("sin URI S3 o credenciales STS vigentes")
    import s3fs

    fs = s3fs.S3FileSystem(
        key=creds.access_key_id,
        secret=creds.secret_access_key,
        token=creds.session_token,
        client_kwargs={"region_name": AWS_REGION},
        default_block_size=STREAM_BLOCK_SIZE,
    )
    handle = fs.open(src.s3_url, "rb")
    handle.read(8)  # fail fast on AccessDenied (role is in-region only)
    handle.seek(0)
    return handle


def _open_https(src: GranuleSource, settings: Settings) -> IO[bytes]:
    if not src.https_url or not settings.earthdata_token:
        raise PermissionError("sin URL HTTPS o EARTHDATA_TOKEN")
    import fsspec

    resp = requests.get(
        src.https_url,
        headers={"Authorization": f"Bearer {settings.earthdata_token}"},
        allow_redirects=False,
        timeout=30,
    )
    if resp.status_code in (401, 403):
        raise PermissionError(f"Earthdata rechazó el token (HTTP {resp.status_code})")
    signed_url = resp.headers.get("Location", src.https_url) if resp.is_redirect else src.https_url
    return fsspec.filesystem("http", block_size=STREAM_BLOCK_SIZE).open(signed_url, "rb")


OPENERS: dict[str, Opener] = {"s3": _open_s3, "https": _open_https}


@contextmanager
def open_granule(src: GranuleSource, settings: Settings, prefer: str = "auto") -> Iterator[tuple[h5py.File, str]]:
    """Yield (h5py.File, access_mode). `prefer` = auto | s3 | https."""
    order = list(OPENERS) if prefer == "auto" else [prefer]
    errors: dict[str, str] = {}
    for mode in order:
        try:
            handle = OPENERS[mode](src, settings)
        except Exception as exc:  # noqa: BLE001 - try next strategy
            errors[mode] = str(exc)
            log.debug("Acceso %s no disponible: %s", mode, exc)
            continue
        log.info("Streaming %s vía %s", src.granule_id, mode)
        try:
            with h5py.File(handle, "r") as h5:
                yield h5, mode
            return
        finally:
            handle.close()
    raise ConnectionError(f"No se pudo abrir {src.granule_id}: {errors}")
