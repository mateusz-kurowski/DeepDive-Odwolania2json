"""Object storage na pliki użytkowników i wyniki ewaluacji: S3/MinIO albo katalog lokalny."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol


class NotFound(KeyError):
    """Brak obiektu pod kluczem."""


class Storage(Protocol):
    backend: str
    bucket: str | None

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...
    def delete(self, key: str) -> None: ...


def _safe(key: str) -> str:
    parts = key.split("/")
    if not key or key.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"niepoprawny klucz: {key!r}")
    return key


class LocalStorage:
    """Na potrzeby developmentu i testów; produkcyjnie S3/MinIO."""

    backend = "local"
    bucket = None

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / _safe(key)

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            raise NotFound(key) from None

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list(self, prefix: str) -> list[str]:
        return sorted(
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file()
            and not p.name.endswith(".tmp")
            and p.relative_to(self.root).as_posix().startswith(prefix)
        )

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3Storage:
    """S3 lub MinIO (`endpoint_url`). Klient można wstrzyknąć (testy)."""

    backend = "s3"

    def __init__(
        self,
        bucket: str,
        client: Any | None = None,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        create_bucket: bool = False,
    ):
        self.bucket = bucket
        if client is None:
            import boto3

            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url or None,
                region_name=region or None,
                aws_access_key_id=access_key or None,
                aws_secret_access_key=secret_key or None,
            )
        self.client = client
        if create_bucket:
            self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.bucket)

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=_safe(key), Body=data, **extra)

    def get(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=_safe(key))["Body"].read()
        except Exception as exc:
            if _is_missing(exc):
                raise NotFound(key) from None
            raise

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=_safe(key))
        except Exception as exc:
            if _is_missing(exc):
                return False
            raise
        return True

    def list(self, prefix: str) -> list[str]:
        keys: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            page = self.client.list_objects_v2(**kwargs)
            keys += [o["Key"] for o in page.get("Contents", [])]
            if not page.get("IsTruncated"):
                return sorted(keys)
            token = page["NextContinuationToken"]

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=_safe(key))


def _is_missing(exc: Exception) -> bool:
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
    return code in ("404", "NoSuchKey", "NotFound")


def make_storage(env: Mapping[str, str] | None = None) -> Storage:
    """`STORAGE_BACKEND=s3|local` (domyślnie s3, gdy ustawiono S3_BUCKET, inaczej local)."""
    env = os.environ if env is None else env
    backend = env.get("STORAGE_BACKEND") or ("s3" if env.get("S3_BUCKET") else "local")
    if backend == "local":
        return LocalStorage(Path(env.get("STORAGE_DIR") or "storage"))
    if backend != "s3":
        raise ValueError(f"nieznany STORAGE_BACKEND: {backend}")
    if not env.get("S3_BUCKET"):
        raise ValueError("STORAGE_BACKEND=s3 wymaga S3_BUCKET")
    return S3Storage(
        env["S3_BUCKET"],
        endpoint_url=env.get("S3_ENDPOINT_URL"),
        region=env.get("S3_REGION"),
        access_key=env.get("S3_ACCESS_KEY"),
        secret_key=env.get("S3_SECRET_KEY"),
        create_bucket=env.get("S3_CREATE_BUCKET", "").lower() in ("1", "true", "yes"),
    )
