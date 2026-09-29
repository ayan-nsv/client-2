import os
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from shared.logger.log import setup_logger

load_dotenv()

logger = setup_logger("marketing-app")

S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", None)
S3_REGION = (os.getenv("S3_REGION") or "").strip() or None
# If set: boto3 uses this S3-compatible API URL (e.g. Huawei OBS). If unset: default AWS S3.
S3_ENDPOINT_URL = (os.getenv("S3_ENDPOINT_URL") or "").strip() or None

_s3_client = None


def get_s3_base_url() -> str:
    """
    Public URL prefix for stored object links.

    Optional override: S3_BASE_URL (custom CDN/domain).
    Otherwise derived from S3_ENDPOINT_URL + S3_BUCKET_NAME (OBS) or bucket + S3_REGION (AWS).
    """
    override = (os.getenv("S3_BASE_URL") or "").strip().rstrip("/")
    if override:
        return override

    bucket = (S3_BUCKET_NAME or "").strip()
    if not bucket:
        raise ValueError("S3_BUCKET_NAME is required")
    # For Huawei OBS
    if S3_ENDPOINT_URL:
        parsed = urlparse(S3_ENDPOINT_URL)
        scheme = parsed.scheme or "https"
        host = parsed.netloc
        if not host:
            raise ValueError("S3_ENDPOINT_URL must include a hostname")
        # obs.eu-west-101.myhuaweicloud.eu -> {bucket}.obs.eu-west-101.myhuaweicloud.eu
        if host.startswith("obs."):
            return f"{scheme}://{bucket}.obs.{host[4:]}"
        #For AWs S3
        return f"{S3_ENDPOINT_URL.rstrip('/')}/{bucket}"

    region = S3_REGION
    if not region:
        raise ValueError(
            "S3_REGION is required when S3_BASE_URL and S3_ENDPOINT_URL are not set"
        )
    # For AWs S3
    return f"https://{bucket}.s3.{region}.amazonaws.com"


def _file_key_from_url(file_url: str) -> str:
    """Resolve object key from a stored URL (derived base + optional legacy S3_BASE_URL)."""
    candidates = []
    try:
        candidates.append(get_s3_base_url().rstrip("/"))
    except ValueError:
        pass
    legacy = (os.getenv("S3_BASE_URL") or "").strip().rstrip("/")
    if legacy and legacy not in candidates:
        candidates.append(legacy)

    for base in candidates:
        prefix = f"{base}/"
        if file_url.startswith(prefix):
            return file_url[len(prefix) :]

    raise ValueError("Invalid S3 file URL: does not match configured bucket base URL")


def get_s3_client():
    """Get or create S3-compatible client (AWS default or custom S3_ENDPOINT_URL)."""
    global _s3_client
    if _s3_client is None:
        client_kwargs = {
            "service_name": "s3",
            "region_name": S3_REGION,
            "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        }
        session_token = (os.getenv("AWS_SESSION_TOKEN") or "").strip()
        if session_token:
            client_kwargs["aws_session_token"] = session_token
        if S3_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = S3_ENDPOINT_URL

        _s3_client = boto3.client(**client_kwargs)
        logger.info(
            "S3 client initialized region=%s endpoint=%s base_url=%s",
            S3_REGION,
            S3_ENDPOINT_URL or "(AWS default)",
            get_s3_base_url(),
        )
    return _s3_client


async def upload_pdf_to_s3(file_bytes: bytes, file_path: str, content_type: str = "application/pdf") -> str:
    """Upload a file to S3-compatible storage. Returns the full public URL."""
    try:
        s3_client = get_s3_client()
        base_url = get_s3_base_url()

        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=file_path,
            Body=file_bytes,
            ContentType=content_type,
        )

        full_url = f"{base_url}/{file_path}"
        logger.info(f"PDF uploaded successfully to S3: {file_path}")
        return full_url

    except ClientError as e:
        logger.error(f"Failed to upload PDF to S3 {file_path}: {str(e)}")
        raise Exception(f"S3 upload failed: {str(e)}") from e
    except Exception as e:
        logger.error(f"Unexpected error uploading PDF to S3: {str(e)}")
        raise Exception(f"Upload failed: {str(e)}") from e


async def delete_file_from_s3(file_url: str):
    """Delete file from S3-compatible storage using its full URL."""
    try:
        file_key = _file_key_from_url(file_url)
        s3_client = get_s3_client()
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=file_key)
        logger.info(f"Deleted file from S3: {file_key}")

    except ClientError as e:
        logger.error(f"Failed to delete file from S3: {str(e)}")
        raise Exception(f"S3 delete failed: {str(e)}") from e
    except Exception as e:
        logger.error(f"Unexpected S3 delete error: {str(e)}")
        raise
