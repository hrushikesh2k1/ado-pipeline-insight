"""Azure Blob Storage client service for caching and persisting InnerSource data.

Uses the azure-storage-blob SDK when available, otherwise falls back to
manual SharedKey REST API construction.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class BlobStorageService:
    def __init__(self, connection_string: str | None = None, container: str | None = None) -> None:
        settings = get_settings()
        self.connection_string = (
            connection_string
            or settings.azure_storage_connection_string
            or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
            or ""
        ).strip()
        self.container = (
            container
            or settings.azure_storage_container
            or os.environ.get("AZURE_STORAGE_CONTAINER")
            or "innersource-data"
        ).strip()
        self.account_name: str = ""
        self.account_key: str = ""
        self.blob_endpoint: str = ""
        self._parse_connection_string()

        # Local fallback directory for offline / testing environments
        self.local_cache_dir = Path(__file__).resolve().parents[2] / ".cache" / "innersource"

        if self.is_configured:
            logger.info(
                "BlobStorageService initialized: account=%s container=%s",
                self.account_name,
                self.container,
            )
        else:
            logger.warning("BlobStorageService: no Azure storage credentials found, using local disk fallback")

    def _parse_connection_string(self) -> None:
        if not self.connection_string:
            return
        parts = dict(
            segment.split("=", 1)
            for segment in self.connection_string.split(";")
            if "=" in segment
        )
        self.account_name = parts.get("AccountName", "").strip()
        self.account_key = parts.get("AccountKey", "").strip()
        self.blob_endpoint = parts.get(
            "BlobEndpoint",
            f"https://{self.account_name}.blob.core.windows.net",
        ).rstrip("/")

    @property
    def is_configured(self) -> bool:
        return bool(self.account_name and self.account_key)

    def _build_auth_headers(
        self,
        verb: str,
        blob_name: str,
        content_length: int = 0,
        content_type: str = "application/json",
    ) -> dict[str, str]:
        """Build the SharedKey authorization headers required by Azure Blob Storage REST API.

        The canonical headers MUST include ALL x-ms-* headers in alphabetical order,
        and x-ms-version is always sent so it must always be in the signature.
        """
        # RFC 1123 date string
        dt = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        ms_version = "2020-10-02"

        # All x-ms-* headers we send (sorted alphabetically for canonicalization)
        xms_headers: dict[str, str] = {
            "x-ms-date": dt,
            "x-ms-version": ms_version,
        }
        if verb == "PUT":
            xms_headers["x-ms-blob-type"] = "BlockBlob"

        # Canonical headers = sorted x-ms-* k:v pairs, one per line, terminated with \n
        canon_headers = "\n".join(
            f"{k}:{v}" for k, v in sorted(xms_headers.items())
        )

        # Canonical resource = /account/container/blob (no URL-encoding needed here – the blob path segments are already clean)
        clean_blob = blob_name.lstrip("/")
        canon_resource = f"/{self.account_name}/{self.container}/{clean_blob}"

        # String-to-sign per the SharedKey schema:
        # VERB\nContent-Encoding\nContent-Language\nContent-Length\nContent-MD5\nContent-Type\n
        # Date\nIf-Modified-Since\nIf-Match\nIf-None-Match\nIf-Unmodified-Since\nRange\n
        # CanonicalizedHeaders\nCanonicalizedResource
        if verb == "PUT":
            str_to_sign = (
                f"PUT\n\n\n{content_length}\n\n{content_type}\n"
                f"\n\n\n\n\n\n"
                f"{canon_headers}\n{canon_resource}"
            )
        else:  # GET
            str_to_sign = (
                f"GET\n\n\n\n\n\n"
                f"\n\n\n\n\n\n"
                f"{canon_headers}\n{canon_resource}"
            )

        decoded_key = base64.b64decode(self.account_key)
        signature = base64.b64encode(
            hmac.new(decoded_key, str_to_sign.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")

        headers = {**xms_headers, "Authorization": f"SharedKey {self.account_name}:{signature}"}
        if verb == "PUT":
            headers["Content-Type"] = content_type
            headers["Content-Length"] = str(content_length)
        return headers

    def put_json(self, blob_name: str, data: Any) -> bool:
        """Write JSON data to Blob Storage, with fallback to local disk."""
        payload = json.dumps(data, indent=2, default=str).encode("utf-8")
        clean_blob = blob_name.lstrip("/")

        if self.is_configured:
            try:
                headers = self._build_auth_headers(
                    "PUT", clean_blob, content_length=len(payload), content_type="application/json"
                )
                url = f"{self.blob_endpoint}/{self.container}/{clean_blob}"
                logger.debug("PUT blob: %s (size=%d bytes)", url, len(payload))
                res = requests.put(url, headers=headers, data=payload, timeout=60)
                if res.status_code in (200, 201):
                    logger.info("Successfully uploaded blob %s to container %s", clean_blob, self.container)
                    return True
                logger.warning(
                    "Failed to upload blob %s: HTTP %s - %s",
                    clean_blob,
                    res.status_code,
                    res.text[:500],
                )
            except Exception as exc:
                logger.warning(
                    "Error writing blob %s to Azure Storage: %s; falling back to local disk",
                    clean_blob,
                    exc,
                )

        # Fallback to local file cache
        try:
            target_path = self.local_cache_dir / clean_blob
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(payload)
            logger.info("Saved local cache for blob %s at %s", clean_blob, target_path)
            return True
        except Exception as exc:
            logger.error("Failed to write local cache for %s: %s", clean_blob, exc)
            return False

    def get_json(self, blob_name: str) -> Any | None:
        """Read and parse JSON from Blob Storage, with fallback to local disk."""
        clean_blob = blob_name.lstrip("/")

        if self.is_configured:
            try:
                headers = self._build_auth_headers("GET", clean_blob)
                url = f"{self.blob_endpoint}/{self.container}/{clean_blob}"
                res = requests.get(url, headers=headers, timeout=30)
                if res.status_code == 200:
                    logger.info("Fetched blob %s from Azure Storage (%d bytes)", clean_blob, len(res.content))
                    return res.json()
                if res.status_code == 404:
                    logger.debug("Blob %s not found in Azure Storage (404)", clean_blob)
                else:
                    logger.warning(
                        "Failed to fetch blob %s: HTTP %s - %s",
                        clean_blob,
                        res.status_code,
                        res.text[:500],
                    )
            except Exception as exc:
                logger.warning(
                    "Error fetching blob %s from Azure Storage: %s; checking local disk",
                    clean_blob,
                    exc,
                )

        # Fallback to local file cache
        target_path = self.local_cache_dir / clean_blob
        if target_path.exists():
            try:
                return json.loads(target_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.error("Failed to read local cache %s: %s", target_path, exc)

        return None


# Global singleton instance
_blob_service: BlobStorageService | None = None


def get_blob_storage_service() -> BlobStorageService:
    global _blob_service
    if _blob_service is None:
        _blob_service = BlobStorageService()
    return _blob_service
