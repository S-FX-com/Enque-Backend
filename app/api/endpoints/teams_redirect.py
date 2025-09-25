from fastapi import APIRouter, HTTPException
from app.core.cache import user_cache
import time
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/redirect-data/{token}")
async def get_redirect_data(token: str):
    """
    Retrieve redirect data for Teams notifications using a temporary token
    """
    try:
        # Check if redirect cache exists
        if not hasattr(user_cache, '_redirect_cache'):
            user_cache._redirect_cache = {}
            
        redirect_cache = user_cache._redirect_cache
        
        # Get data from in-memory cache
        if token not in redirect_cache:
            logger.warning(f"Redirect token not found: {token}")
            raise HTTPException(status_code=404, detail="Redirect token not found")
        
        redirect_data = redirect_cache[token]
        
        # Check if token has expired
        current_time = time.time()
        if current_time > redirect_data.get("expires_at", 0):
            # Clean up expired token
            del redirect_cache[token]
            logger.warning(f"Redirect token expired: {token}")
            raise HTTPException(status_code=404, detail="Redirect token expired")
        
        # Optional: Delete the token after use (single-use)
        del redirect_cache[token]
        
        logger.info(f"Successfully retrieved redirect data for token: {token}")
        
        return {
            "ticketId": redirect_data.get("ticketId"),
            "subdomain": redirect_data.get("subdomain"),
            "agentId": redirect_data.get("agentId"),
            "timestamp": redirect_data.get("timestamp")
        }
        
    except Exception as e:
        logger.error(f"Unexpected error retrieving redirect data for token {token}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")