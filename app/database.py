# app/database.py
import json
import sqlite3
from pathlib import Path

import os
from docutils.nodes import row
from langchain_core import documents
import pandas as pd
from dotenv import load_dotenv

from langchain_text_splitters import RecursiveCharacterTextSplitter

from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
# from langchain.vectorstores import Qdrant
from langchain_qdrant import QdrantVectorStore, RetrievalMode, FastEmbedSparse , Qdrant 
from langchain_core.tools import Tool
# from langchain.agents import initialize_agent, AgentType
from qdrant_client import QdrantClient
from pathlib import Path
import requests
from qdrant_client.models import Filter, FieldCondition, MatchValue

from .db import SessionLocal
from .models import Message , PropertyState, BookingState , Lead, Company


load_dotenv()



BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "chat_memory.sqlite3"
GOOGLE_SHEET_WEBHOOK = os.getenv("GOOGLE_SHEET_URL")

if not GOOGLE_SHEET_WEBHOOK:
    print("Warning: GOOGLE_SHEET_URL not set in .env")


#property cache
PROPERTY_CACHE = {}

REQUIRED_PROPERTY_COLUMNS = [
    "property_id",
    "title",
    "description",
    "price_usd",
    "area_sqft",
    "location",
    "bedrooms",
    "bathrooms",
    "property_type",
    "amenities",
    "listing_date",
    "image_url"
]



#send to google function
def send_to_google_sheet(client_id,user_id, name=None, email=None,
                         whatsapp=None, preferred_time=None,
                         source="chatbot",
                         preferred_properties=None,
                         lead_type=None):
    payload = {
        "client_id": client_id,
        "user_id": user_id,
        "name": name,
        "email": email,
        "whatsapp": whatsapp,
        "preferred_time": preferred_time,
        "source": source,
        "preferred_properties": ",".join(preferred_properties) if preferred_properties else None,
        "lead_type": lead_type
    }
    print("GOOGLE SHEET PAYLOAD:", payload)
    try:
        response = requests.post(GOOGLE_SHEET_WEBHOOK, json=payload, timeout=5)
        print("Webhook status:", response.status_code)
        print("Webhook response:", response.text)
    except Exception as e:
        print("Google Sheet webhook failed:", e)



def validate_client_api(client_id, api_key):

    db = SessionLocal()

    company = db.query(Company).filter(
        Company.client_id == client_id,
        Company.api_key == api_key
    ).first()

    db.close()

    if not company:
        return None

    return company


def get_company(client_id):

    db = SessionLocal()

    company = db.query(Company).filter(
        Company.client_id == client_id
    ).first()

    db.close()

    return company
#------------------------
#whatsapp integration functions
#-----------------------

def send_whatsapp_notification(client_id, name, phone, property_ids, preferred_time):
    company = get_company(client_id)
    if not company:
        print("Company config missing")
        return
    token = company.whatsapp_token
    phone_number_id = company.whatsapp_phone_number_id
    agency_phone = company.agency_whatsapp

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"

    properties = ", ".join(property_ids) if property_ids else "Not specified"

    message_text = f"""
🔥 New EstateAI Lead

Name: {name}
Phone: {phone}

Interested Property:
{properties}

Preferred Contact Time:
{preferred_time}
"""

    payload = {
        "messaging_product": "whatsapp",
        "to": agency_phone,
        "type": "text",
        "text": {
            "body": message_text
        }
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        print("WhatsApp status:", response.status_code)
        print("WhatsApp response:", response.text)
    except Exception as e:
        print("WhatsApp notification failed:", e)



#memory memory
# def init_memory_db():
#     # conn = sqlite3.connect(DB_PATH , check_same_thread=False)
    
#     conn.execute("PRAGMA journal_mode=WAL;")  # Better concurrency
#     cursor = conn.cursor()


#     # Chat memory
#     cursor.execute("""
#         CREATE TABLE IF NOT EXISTS messages (
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             user_id TEXT,
#             thread_id TEXT,
#             role TEXT,
#             content TEXT,
#             timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
#         )
#     """)
#     # Users table (Admin authentication)
#     cursor.execute("""
#         CREATE TABLE IF NOT EXISTS users (
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             email TEXT UNIQUE,
#             password_hash TEXT
#         )
#     """)

#     # Property state
#     cursor.execute("""
#         CREATE TABLE IF NOT EXISTS property_state (
#             user_id TEXT,
#             thread_id TEXT,
#             property_ids TEXT,
#             PRIMARY KEY (user_id, thread_id)
#         )
#     """)
#     # Lead table
#     cursor.execute("""
#         CREATE TABLE IF NOT EXISTS leads (
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             user_id TEXT ,
#             thread_id TEXT,
#             name TEXT,
#             email TEXT,
#             whatsapp TEXT,
#             preferred_time TEXT,
#             source TEXT,
#             preferred_properties TEXT,
#             lead_type TEXT,
#             status TEXT DEFAULT 'New',
#             timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
#         )
#     """)
#     # Booking state table
#     cursor.execute("""
#         CREATE TABLE IF NOT EXISTS booking_state (
#             user_id TEXT,
#             thread_id TEXT,
#             name TEXT,
#             email TEXT,
#             phone TEXT,
#             property_ids TEXT,
#             preferred_time TEXT,
#             stage TEXT,
#             lead_stage_saved TEXT,
#             PRIMARY KEY (user_id, thread_id)
#         )
#     """)


#     conn.commit()
#     conn.close()
#for leads

from .models import Lead
from .db import SessionLocal
import json


def save_lead(
    client_id,
    user_id,
    thread_id,
    name=None,
    email=None,
    whatsapp=None,
    preferred_time=None,
    preferred_properties=None,
    lead_type="Cold"
):

    db = SessionLocal()

    existing = (
        db.query(Lead)
        .filter(
            Lead.client_id == client_id,
            Lead.user_id == user_id,
            Lead.thread_id == thread_id
        )
        .first()
    )

    if existing:

        if name:
            existing.name = name

        if email:
            existing.email = email

        if whatsapp:
            existing.whatsapp = whatsapp

        if preferred_time:
            existing.preferred_time = preferred_time

        if preferred_properties:
            existing.preferred_properties = json.dumps(preferred_properties)

        existing.lead_type = lead_type

    else:

        new_lead = Lead(
            client_id=client_id,
            user_id=user_id,
            thread_id=thread_id,
            name=name,
            email=email,
            whatsapp=whatsapp,
            preferred_time=preferred_time,
            preferred_properties=json.dumps(preferred_properties) if preferred_properties else None,
            lead_type=lead_type
        )

        db.add(new_lead)

    db.commit()
    db.close()
    

#save message to memory
def save_message(client_id: str, user_id: str, thread_id: str, role: str, content: str):
    db = SessionLocal()

    msg = Message(
        client_id=client_id,
        user_id=user_id,
        thread_id=thread_id,
        role=role,
        content=content
    )

    db.add(msg)
    db.commit()
    db.close()

def load_recent_messages(client_id: str, user_id: str, thread_id: str, limit: int = 7):

    db = SessionLocal()

    rows = (
        db.query(Message)
        .filter(
            Message.client_id == client_id,
            Message.user_id == user_id,
            Message.thread_id == thread_id
        )
        .order_by(Message.timestamp.desc())
        .limit(limit)
        .all()
    )

    db.close()

    rows.reverse()

    return [{"role": r.role, "content": r.content} for r in rows]


from .models import PropertyState
from .db import SessionLocal
import json


def save_property_state(client_id: str, user_id: str, thread_id: str, property_ids: list):

    db = SessionLocal()

    state = (
        db.query(PropertyState)
        .filter(
            PropertyState.client_id == client_id,
            PropertyState.user_id == user_id,
            PropertyState.thread_id == thread_id
        )
        .first()
    )

    if state:
        state.property_ids = json.dumps(property_ids)
    else:
        state = PropertyState(
            client_id=client_id,
            user_id=user_id,
            thread_id=thread_id,
            property_ids=json.dumps(property_ids)
        )
        db.add(state)

    db.commit()
    db.close()

def load_property_state(client_id,user_id, thread_id):

    db = SessionLocal()

    state = (
        db.query(PropertyState)
        .filter(
            PropertyState.client_id == client_id,
            PropertyState.user_id == user_id,
            PropertyState.thread_id == thread_id
        )
        .first()
    )

    db.close()

    if state and state.property_ids:
        return json.loads(state.property_ids)

    return []

# def load_property_cache():
#     df = pd.read_csv(DATA_PATH)

#     for _, row in df.iterrows():
#         PROPERTY_CACHE[f"{row['client_id']}_{row['property_id']}"] = {
#             "property_id": row["property_id"],
#             "title": row["title"],
#             "price_usd": row["price_usd"],
#             "location": row["location"],
#             "bedrooms": row["bedrooms"],
#             "bathrooms": row["bathrooms"],
#             "area_sqft": row["area_sqft"],
#             "property_type": row["property_type"],
#             "image_url": row["image_url"]
#         }

def load_property_cache():

    PROPERTY_CACHE.clear()

    points, _ = client.scroll(
        collection_name=COLLECTION_NAME,
        limit=10000,
        with_payload=True,
        with_vectors=False
    )

    for point in points:

        payload = point.payload

        metadata = payload.get("metadata", {})

        if not metadata:
            continue

        key = f"{metadata['client_id']}_{metadata['property_id']}"

        PROPERTY_CACHE[key] = {
            
            "property_id": metadata["property_id"],
            "title": metadata["title"],
            "price_usd": metadata["price_usd"],
            "location": metadata["location"],
            "bedrooms": metadata["bedrooms"],
            "bathrooms": metadata["bathrooms"],
            "area_sqft": metadata["area_sqft"],
            "property_type": metadata["property_type"],
            "image_url": metadata["image_url"]
        }

    print(f"Loaded {len(PROPERTY_CACHE)} properties into cache")



#for booking state
def save_booking_state(client_id,user_id, thread_id, **kwargs):

    db = SessionLocal()

    state = (
        db.query(BookingState)
        .filter(
            BookingState.client_id == client_id,
            BookingState.user_id == user_id,
            BookingState.thread_id == thread_id
        )
        .first()
    )

    if not state:
        state = BookingState(
            client_id=client_id,
            user_id=user_id,
            thread_id=thread_id
        )
        db.add(state)

    # progressive updates (same logic as SQLite)
    for key, value in kwargs.items():
        if value is not None:
            setattr(state, key, value)

    db.commit()
    db.close()


def load_booking_state(client_id,user_id, thread_id):

    db = SessionLocal()

    state = (
        db.query(BookingState)
        .filter(
            BookingState.client_id == client_id,
            BookingState.user_id == user_id,
            BookingState.thread_id == thread_id
        )
        .first()
    )

    db.close()

    if not state:
        return None

    return {
        "name": state.name,
        "email": state.email,
        "phone": state.phone,
        "property_ids": state.property_ids,
        "preferred_time": state.preferred_time,
        "stage": state.stage,
        "lead_stage_saved": state.lead_stage_saved
    }


def clear_booking_state(client_id, user_id, thread_id):

    db = SessionLocal()

    db.query(BookingState).filter(
        BookingState.client_id == client_id,
        BookingState.user_id == user_id,
        BookingState.thread_id == thread_id
    ).delete()

    db.commit()
    db.close()

COLLECTION_NAME = "house_listings"
EMBEDDING_MODEL = "models/gemini-embedding-001"

# Initialize embeddings
embeddings = GoogleGenerativeAIEmbeddings(
    model=EMBEDDING_MODEL,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# Qdrant client
sparse_embeddings = FastEmbedSparse(model_name="Qdrant/bm25")

#-------------------
# Vector store
#----------------
# vector_store = QdrantVectorStore.from_documents(
#     documents=[],
#     embedding=embeddings,
#     # sparse_embedding=sparse_embeddings,
#     url="https://5413868d-cca6-4f3e-8aa2-32e74dc78bd1.us-west-1-0.aws.cloud.qdrant.io", 
#     # api_key=os.getenv("QDRANT_API_KEY"),
#     api_key=os.getenv("QDRANT_API_KEY"),
    
#     collection_name = COLLECTION_NAME,
#     retrieval_mode=RetrievalMode.DENSE,
#     force_recreate=False #true if you want to recreate collection every time, false to keep existing data
# )

client = QdrantClient(
    url="https://5413868d-cca6-4f3e-8aa2-32e74dc78bd1.us-west-1-0.aws.cloud.qdrant.io",
    api_key=os.getenv("QDRANT_API_KEY"),
    timeout=60
)



from qdrant_client.models import PayloadSchemaType

try:
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="metadata.client_id",
        field_schema=PayloadSchemaType.KEYWORD
    )
except Exception:
    pass
vector_store = QdrantVectorStore(
    client=client,
    collection_name=COLLECTION_NAME,
    embedding=embeddings
)

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "property_listings.csv"


def load_csv_to_qdrant():
    df = pd.read_csv(DATA_PATH)

    documents = []

    for _, row in df.iterrows():
        content = f"""
        Property_id: {row['property_id']}
        Title: {row['title']}
        Description: {row['description']}
        Price: {row['price_usd']}
        Area_sqft: {row['area_sqft']}
        Location: {row['location']}
        Bedrooms: {row['bedrooms']}
        Bathrooms: {row['bathrooms']}
        Property_type: {row['property_type']}
        Amenities: {row['amenities']}
        Listing_date: {row['listing_date']}
        image_url: {row['image_url']}
        """
        
        metadata = {
            "property_id": row["property_id"],
            "title": row["title"],
            "price_usd": row["price_usd"],
            "location": row["location"],
            "bedrooms": row["bedrooms"],
            "bathrooms": row["bathrooms"],
            "area_sqft": row["area_sqft"],
            "property_type": row["property_type"],
            "image_url": row["image_url"],  
            "client_id": row["client_id"]
        }

        client_id = row["client_id"]
        property_id = row["property_id"]
        PROPERTY_CACHE[f"{client_id}_{property_id}"] = metadata

        documents.append(Document(page_content=content, metadata=metadata))


    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )

    split_docs = splitter.split_documents(documents)
    # vector_store.add_documents(docs)
    batch_size = 10

    for i in range(0, len(split_docs), batch_size):
        batch = split_docs[i:i + batch_size]
        
        vector_store.add_documents(batch)
    # vector_store.add_documents(documents)


def index_properties_csv(df, client_id):

    from qdrant_client.models import Filter, FieldCondition, MatchValue

    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="client_id",
                    match=MatchValue(value=client_id)
                )
            ]
        )
    )
    documents = []

    for _, row in df.iterrows():

        content = f"""
        Property_id: {row['property_id']}
        Title: {row['title']}
        Description: {row['description']}
        Price: {row['price_usd']}
        Area_sqft: {row['area_sqft']}
        Location: {row['location']}
        Bedrooms: {row['bedrooms']}
        Bathrooms: {row['bathrooms']}
        Property_type: {row['property_type']}
        Amenities: {row['amenities']}
        Listing_date: {row['listing_date']}
        image_url: {row['image_url']}
        """

        metadata = {
            "client_id": client_id,
            "property_id": row["property_id"],
            "title": row["title"],
            "price_usd": row["price_usd"],
            "location": row["location"],
            "bedrooms": row["bedrooms"],
            "bathrooms": row["bathrooms"],
            "area_sqft": row["area_sqft"],
            "property_type": row["property_type"],
            "image_url": row["image_url"],
            
        }

        PROPERTY_CACHE[f"{client_id}_{row['property_id']}"] = metadata

        documents.append(
            Document(
                page_content=content,
                metadata=metadata
            )
        )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )

    split_docs = splitter.split_documents(documents)

    batch_size = 5

    for i in range(0, len(split_docs), batch_size):
        batch = split_docs[i:i + batch_size]
        # upload to Qdrant in small batches to prevent timeout
        vector_store.add_documents(batch)

    return len(df)



#CSV Validation Function

def validate_property_csv(df):

    missing_columns = []

    for col in REQUIRED_PROPERTY_COLUMNS:
        if col not in df.columns:
            missing_columns.append(col)

    if missing_columns:
        raise ValueError(
            f"CSV missing required columns: {', '.join(missing_columns)}"
        )

    if df.empty:
        raise ValueError("CSV file is empty")

    if df["property_id"].duplicated().any():
        raise ValueError("Duplicate property_id detected in CSV")

    return True

def delete_property_from_qdrant(property_id, client_id):

    filter_condition = {
        "must": [
            {"key": "property_id", "match": {"value": property_id}},
            {"key": "client_id", "match": {"value": client_id}}
        ]
    }

    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector={"filter": filter_condition}
    )
    cache_key = f"{client_id}_{property_id}"
    if cache_key in PROPERTY_CACHE:
        del PROPERTY_CACHE[cache_key]
    # if property_id in PROPERTY_CACHE:
    #     del PROPERTY_CACHE[property_id]

    return True

def delete_client_properties(client_id):

    filter_condition = {
        "must": [
            {"key": "client_id", "match": {"value": client_id}}
        ]
    }

    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector={"filter": filter_condition}
    )

    keys_to_delete = [
        k for k, v in PROPERTY_CACHE.items()
        if v.get("client_id") == client_id
    ]

    for k in keys_to_delete:
        del PROPERTY_CACHE[k]

# def get_retriever():
#     return vector_store.as_retriever(search_kwargs={"k": 12})
def get_retriever(client_id):

    return vector_store.as_retriever(
        search_kwargs={
            "k": 12,
            "filter": {
                "must": [
                    {
                        "key": "metadata.client_id",
                        "match": {
                            "value": client_id
                        }
                    }
                ]
            }
        }
    )



