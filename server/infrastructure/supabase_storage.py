from __future__ import annotations

"""Supabase Storage HTTP adapter. The service-role key stays server-side."""

from urllib.parse import quote, urljoin
import httpx
from settings import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

BUCKETS = {"product-images", "prescriptions"}


class StorageError(RuntimeError):
    pass


class SupabaseStorage:
    def _auth_headers(self) -> dict[str, str]:
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            raise StorageError("Supabase Storage is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in server/.env.")
        return {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        }

    @staticmethod
    def _safe_path(bucket: str, path: str) -> str:
        if bucket not in BUCKETS:
            raise StorageError("Unsupported Storage bucket.")
        path = str(path).replace("\\", "/").lstrip("/")
        parts = path.split("/")
        if not parts or any(p in {"", ".", ".."} for p in parts) or "?" in path or "#" in path:
            raise StorageError("Invalid Storage path.")
        return "/".join(quote(part, safe="-._~") for part in parts)

    def _endpoint(self, bucket: str, path: str, prefix: str) -> str:
        if not SUPABASE_URL:
            raise StorageError("SUPABASE_URL is missing.")
        return f"{SUPABASE_URL.rstrip('/')}/storage/v1/{prefix}/{quote(bucket, safe='')}/{self._safe_path(bucket, path)}"

    def upload(self, bucket: str, path: str, data: bytes, content_type: str, *, upsert: bool = False) -> str:
        if bucket == "prescriptions" and content_type not in {"application/pdf", "image/png", "image/jpeg", "image/webp"}:
            raise StorageError("This prescription file type is not allowed.")
        if bucket == "product-images" and content_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise StorageError("Only JPG, PNG, and WEBP product images are accepted.")
        limit = 5*1024*1024 if bucket == "product-images" else 10*1024*1024
        if len(data) > limit or not data:
            raise StorageError("File is empty or exceeds the bucket size limit.")
        headers = {**self._auth_headers(), "content-type": content_type, "x-upsert": "true" if upsert else "false"}
        try:
            response = httpx.post(self._endpoint(bucket, path, "object"), headers=headers, content=data, timeout=30)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise StorageError("Supabase Storage upload failed. Check the bucket and server credentials.") from exc
        return path

    def public_url(self, bucket: str, path: str) -> str:
        if bucket != "product-images":
            raise StorageError("Only product images can have public Storage URLs.")
        return self._endpoint(bucket, path, "object/public")

    def signed_url(self, bucket: str, path: str, expires: int = 3600) -> str:
        if bucket == "product-images":
            return self.public_url(bucket, path)
        expires = max(60, min(int(expires), 3600))
        try:
            response = httpx.post(
                self._endpoint(bucket, path, "object/sign"),
                headers={**self._auth_headers(), "content-type": "application/json"},
                json={"expiresIn": expires}, timeout=20,
            )
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise StorageError("Unable to create a Supabase signed file link.") from exc
        signed = result.get("signedURL") or result.get("signedUrl")
        if not signed:
            raise StorageError("Supabase did not return a signed URL.")
        if signed.startswith("https://"):
            return signed
        # Supabase generally returns /object/sign/bucket/path?token=...
        base = SUPABASE_URL.rstrip("/") + "/storage/v1/"
        return urljoin(base, signed.lstrip("/"))


storage = SupabaseStorage()
