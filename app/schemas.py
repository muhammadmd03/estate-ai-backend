# app/schemas.py

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from datetime import datetime


# ---------------------------------
# Chat API Models
# ---------------------------------
class ChatRequest(BaseModel):
    client_id: str
    api_key: str
    message: str
    # user_id: str = "default_user"
    # thread_id: str = "default_thread"
    user_id: str
    thread_id: str


class PropertyCard(BaseModel):
    property_id: str
    title: str
    price_usd: float
    location: str
    bedrooms: int
    bathrooms: int
    area_sqft: float


class ChatResponse(BaseModel):
    reply: str
    properties: Optional[List[PropertyCard]] = None
    analysis: Optional[Dict[str, Any]] = None


# ---------------------------------
# Upload Endpoint (Future Ready)
# ---------------------------------

class UploadResponse(BaseModel):
    message: str
    documents_indexed: int