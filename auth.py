import hashlib
import hmac
from typing import Optional, Dict, Any
from urllib.parse import unquote

from fastapi import HTTPException, status, Header, Depends
from pydantic import BaseModel, Field

# Local imports
from config import Settings
from dependencies import get_settings_dep

# settings = get_settings() # 💥 УДАЛЕНО: Это вызывало ошибку при импорте во время тестов

class WebAppUser(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    language_code: Optional[str] = "en"
    is_premium: Optional[bool] = False

class InitData(BaseModel):
    query_id: Optional[str] = None
    user: Optional[WebAppUser] = None
    receiver: Optional[WebAppUser] = None
    chat: Optional[Dict[str, Any]] = None
    start_param: Optional[str] = None
    can_send_after: Optional[int] = None
    auth_date: int
    hash: str

def validate_init_data(init_data: str, bot_token: str) -> InitData:
    """
    Validates the initData string from the Telegram Web App.
    
    Raises HTTPException if validation fails.
    """
    try:
        # Sort and format the data pairs
        data_pairs = sorted([
            chunk.split("=") 
            for chunk in unquote(init_data).split("&")
        ])
        
        # Extract the hash and remove it from the pairs
        hash_value = ""
        for i, pair in enumerate(data_pairs):
            if pair[0] == "hash":
                hash_value = pair[1]
                data_pairs.pop(i)
                break
        
        if not hash_value:
            raise ValueError("Hash not found in initData")

        # Create the data-check-string
        data_check_string = "\n".join([f"{k}={v}" for k, v in data_pairs])

        # Calculate HMAC-SHA256
        secret_key = hmac.new("WebAppData".encode(), bot_token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        # Compare hashes
        if calculated_hash != hash_value:
            raise ValueError("Hash validation failed")
            
        # Parse the user data from the original string
        parsed_data = {k: v for k, v in (p.split("=") for p in unquote(init_data).split("&"))}
        return InitData(**parsed_data)

    except (ValueError, KeyError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid initData: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during initData validation: {e}"
        )

async def get_validated_user(
    authorization: str = Header(None),
    settings: Settings = Depends(get_settings_dep)
) -> WebAppUser:
    """
    A FastAPI dependency that validates the initData from the Authorization header.
    
    Header format should be "Tma <init_data_string>".
    
    Returns the WebAppUser object if validation is successful.
    Raises HTTPException if validation fails.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is missing."
        )

    if not authorization.startswith("Tma "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme. Should be 'Tma <initData>'."
        )
    
    init_data_str = authorization.split(" ", 1)[1]
    
    try:
        validated_data = validate_init_data(init_data_str, settings.BOT_TOKEN)
        if not validated_data.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User data not found in initData."
            )
        return validated_data.user
    except HTTPException as e:
        # Re-raise exceptions from validation
        raise e
    except Exception as e:
        # Catch any other unexpected errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during authorization: {e}"
        )
