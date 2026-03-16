from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from .db import Base
from sqlalchemy import Index



class PropertyState(Base):
    __tablename__ = "property_state"

    client_id = Column(String, primary_key=True)
    user_id = Column(String, primary_key=True)
    thread_id = Column(String, primary_key=True)

    property_ids = Column(Text)


class User(Base):

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)

    client_id = Column(String, index=True)

    email = Column(String, unique=True)

    password_hash = Column(String)


class Company(Base):

    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)

    client_id = Column(String, unique=True, index=True)

    agency_name = Column(String)

    api_key = Column(String, unique=True)

    brand_color = Column(String)
    welcome_message = Column(Text)
    widget_position = Column(String)

    whatsapp_token = Column(Text)
    whatsapp_phone_number_id = Column(String)
    agency_whatsapp = Column(String)

    google_sheet_webhook = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    
class BookingState(Base):
    __tablename__ = "booking_state"

    client_id = Column(String, primary_key=True)
    user_id = Column(String, primary_key=True)
    thread_id = Column(String, primary_key=True)

    name = Column(String)
    email = Column(String)
    phone = Column(String)

    property_ids = Column(Text)
    preferred_time = Column(String)

    stage = Column(String)
    lead_stage_saved = Column(String)

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    client_id = Column(String, index=True)
    user_id = Column(String)
    thread_id = Column(String)
    role = Column(String)
    content = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_user_thread", "user_id", "thread_id"),
    )


class Lead(Base):

    __tablename__ = "leads"

    id = Column(Integer, primary_key=True)

    client_id = Column(String, index=True)
    user_id = Column(String)
    thread_id = Column(String)

    name = Column(String)
    email = Column(String)
    whatsapp = Column(String)

    preferred_time = Column(String)
    preferred_properties = Column(Text)

    lead_type = Column(String)
    status = Column(String, default="New")

    timestamp = Column(DateTime(timezone=True), server_default=func.now())