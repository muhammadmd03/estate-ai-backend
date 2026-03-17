# app/main.py

from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from fastapi import BackgroundTasks
from fastapi import HTTPException
from pydantic import BaseModel
import sqlite3
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from io import StringIO
import secrets

from .models import User, Company
from .db import SessionLocal
from .models import Lead
from sqlalchemy import desc
from .db import engine
from .models import Base
from .engine import run_agent
from .database import  load_property_cache, index_properties_csv
from .database import validate_property_csv
from .schemas import ChatRequest, ChatResponse, UploadResponse
from .auth import verify_password, create_access_token
from .database import DB_PATH
from .database import delete_property_from_qdrant, delete_client_properties
from .database import load_csv_to_qdrant , validate_client_api


# ---------------------------------
# App Initialization
# ---------------------------------


import os 

print("==== ENV DEBUG ====")
print("DATABASE_URL:", os.getenv("DATABASE_URL"))
print("GOOGLE_API_KEY:", os.getenv("GOOGLE_API_KEY"))
print("QDRANT_API_KEY:", os.getenv("QDRANT_API_KEY"))
print("===================")

app = FastAPI(
    title="Real Estate AI Backend",
    description="Hybrid RAG + Gemini-powered real estate assistant",
    version="1.0.0"
)
# ---------------------------------
# CORS (Important for frontend)
# ---------------------------------


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/login")
def login(data: LoginRequest):
    # TEMP DEBUG — remove after fixing
    print(f"Email received: '{data.email}'")
    print(f"Password received: '{data.password}'")
    print(f"Password length: {len(data.password)} chars / {len(data.password.encode('utf-8'))} bytes")
    

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == data.email).first()

        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if not verify_password(data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = create_access_token({
            "sub": str(user.id),
            "client_id": user.client_id
        })
        return {"access_token": token}
    finally:
        db.close()
    # user = db.query(User).filter(User.email == data.email).first()

    # db.close()
    # print("Input password:", data.password)
    # print("Stored hash:", user.password_hash)

    # if not user:
    #     raise HTTPException(status_code=401, detail="Invalid credentials")

    # if not verify_password(data.password, user.password_hash):
    #     raise HTTPException(status_code=401, detail="Invalid credentials")

    # token = create_access_token({
    #     "sub": str(user.id),
    #     "client_id": user.client_id
    # })

    # return {"access_token": token}


#Protect /api/leads

from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from .auth import SECRET_KEY, ALGORITHM

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401)
        return {
            "user_id": user_id,
            "client_id": payload.get("client_id")
        }
    except JWTError:
        raise HTTPException(status_code=401)
    
# @app.post("/api/upload-properties")
# async def upload_properties(
#     file: UploadFile = File(...),
#     current_user: dict = Depends(get_current_user)
# ):

#     if not file.filename.endswith(".csv"):
#         raise HTTPException(status_code=400, detail="Only CSV files allowed")

#     contents = await file.read()

#     try:
#         df = pd.read_csv(StringIO(contents.decode("utf-8")))

        
#         validate_property_csv(df)

#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))

#     except Exception:
#         raise HTTPException(status_code=400, detail="Invalid CSV format")

#     client_id = current_user["client_id"]

#     indexed = index_properties_csv(df, client_id)

#     return {
#         "message": "Properties uploaded successfully",
#         "properties_indexed": indexed
#     }

@app.delete("/api/properties/{property_id}")
def delete_property(
    property_id: str,
    current_user: dict = Depends(get_current_user)
):

    client_id = current_user["client_id"]

    deleted = delete_property_from_qdrant(property_id, client_id)

    return {
        "message": "Property deleted",
        "deleted": deleted
    }

@app.delete("/api/properties")
def delete_all_properties(current_user: dict = Depends(get_current_user)):

    client_id = current_user["client_id"]

    delete_client_properties(client_id)

    return {"message": "All properties deleted"}


@app.get("/api/leads")
def get_leads(
    lead_type: str | None = None,
    status: str | None = None,
    property_id: str | None = None,
    current_user: str = Depends(get_current_user)
):

    db = SessionLocal()

    query = db.query(Lead).filter(
        Lead.client_id == current_user["client_id"]
    )

    if lead_type:
        query = query.filter(Lead.lead_type == lead_type)

    if status:
        query = query.filter(Lead.status == status)

    if property_id:
        query = query.filter(Lead.preferred_properties.contains(property_id))

    rows = query.order_by(desc(Lead.timestamp)).all()

    db.close()

    # return same structure as old code
    return [
        {
            "id": r.id,
            "name": r.name,
            "email": r.email,
            "whatsapp": r.whatsapp,
            "preferred_time": r.preferred_time,
            "preferred_properties": r.preferred_properties,
            "lead_type": r.lead_type,
            "status": r.status,
            "timestamp": r.timestamp,
        }
        for r in rows
    ]





# ---------------------------------
# Startup Event
# ---------------------------------

from .database import index_properties_csv

@app.on_event("startup")
def startup_event():
    """
    Initialize memory DB and load CSV into Qdrant.
    Runs only once at startup.
    """
    try:
        # 🔥 Create postgresql tables
        Base.metadata.create_all(bind=engine)

        print("PostgreSQL tables created")

        # Load vector data
        # load_csv_to_qdrant()
        # print("✅ Property data loaded into Qdrant.")
        
        load_property_cache()
        print("✅ Property cache loaded into memory.")


    except Exception as e:
        print(f"⚠️ Startup loading skipped or failed: {e}")

# ---------------------------------
# Health Check
# ---------------------------------

@app.get("/")
def health_check():
    return {
        "status": "running",
        "service": "Real Estate AI",
        "timestamp": datetime.utcnow()
    }

@app.get("/api/widget-config/{client_id}")

def widget_config(client_id: str):

    db = SessionLocal()

    company = db.query(Company).filter(
        Company.client_id == client_id
    ).first()

    db.close()

    if not company:
        raise HTTPException(status_code=404, detail="Client not found")

    return {
        "agency_name": company.agency_name,
        "brand_color": company.brand_color,
        "welcome_message": company.welcome_message,
        "widget_position": company.widget_position,
        "whatsapp_number": company.agency_whatsapp
    }

# ---------------------------------
# Chat Endpoint
# ---------------------------------


@app.post("/api/chat")
def chat(request: ChatRequest, background_tasks: BackgroundTasks):

    company = validate_client_api(
        request.client_id,
        request.api_key
    )

    if not company:
        raise HTTPException(status_code=401, detail="Invalid client ID or API key")


    result = run_agent(
    request.message,
    request.client_id,
    request.user_id,
    request.thread_id,
    background_tasks
    )

    # background_tasks.add_task(send_webhook, data)

    return {
        "reply": result.get("reply"),
        "properties": result.get("properties"),
        "analysis": result.get("analysis", None)
    }


# ---------------------------------
# Optional: Manual Reindex Endpoint
# ---------------------------------

@app.post("/reindex", response_model=UploadResponse)
def reindex_data():
    """
    Manually reload CSV into Qdrant.
    Useful if data changes.
    """
    # load_csv_to_qdrant()

    return UploadResponse(
        message="Data reindexed successfully.",
        documents_indexed=0  # you can improve this later
    )



@app.post("/api/admin/create-client")

def create_client(client_id: str, agency_name: str):

    db = SessionLocal()

    existing = db.query(Company).filter(
        Company.client_id == client_id
    ).first()

    if existing:
        db.close()
        raise HTTPException(status_code=400, detail="Client already exists")

    api_key = "sk_live_" + secrets.token_hex(16)

    company = Company(
        client_id=client_id,
        agency_name=agency_name,
        api_key=api_key
    )

    db.add(company)
    db.commit()
    db.close()

    return {
        "client_id": client_id,
        "api_key": api_key
    }


import uvicorn

# if __name__ == "__main__":
#     port = int(os.environ.get("PORT", 8080))
#     uvicorn.run("app.main:app", host="0.0.0.0", port=port)