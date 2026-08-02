"""Cloudflare R2 파일 업로드/삭제."""

import asyncio
import uuid

import boto3
from botocore.client import Config

from app.config import settings

_client = boto3.client(
    "s3",
    endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=settings.R2_ACCESS_KEY_ID,
    aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
    region_name="auto",
)


async def upload_file(folder: str, file_bytes: bytes, extension: str, content_type: str) -> str:
    """파일을 `{folder}/{uuid4}.{extension}` 키로 R2에 업로드하고 public URL을 반환합니다."""
    key = f"{folder}/{uuid.uuid4()}.{extension}"
    await asyncio.to_thread(
        _client.put_object,
        Bucket=settings.R2_BUCKET_NAME,
        Key=key,
        Body=file_bytes,
        ContentType=content_type,
    )
    return f"{settings.R2_PUBLIC_URL}/{key}"


async def delete_file(url: str) -> None:
    """public URL에 해당하는 R2 오브젝트를 삭제합니다."""
    key = url.removeprefix(f"{settings.R2_PUBLIC_URL}/")
    await asyncio.to_thread(_client.delete_object, Bucket=settings.R2_BUCKET_NAME, Key=key)
