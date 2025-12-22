
import aioboto3
from typing import Optional

from config import Settings

# This is a global session object that can be reused.
# aioboto3 sessions are generally safe to be shared.
_session: Optional[aioboto3.Session] = None

def get_s3_session(settings: Settings) -> Optional[aioboto3.Session]:
    """
    Initializes and returns a reusable aioboto3 session if S3 is configured.
    Returns None if S3 is not configured.
    """
    global _session

    # If S3 is not configured, do nothing.
    if not all([settings.S3_BUCKET_NAME, settings.S3_ENDPOINT_URL, settings.S3_ACCESS_KEY_ID, settings.S3_SECRET_ACCESS_KEY]):
        return None

    # If session is already created, return it.
    if _session:
        return _session

    # Otherwise, create a new session.
    _session = aioboto3.Session(
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        region_name="auto",  # region is usually not important for S3-compatible services
    )
    return _session
