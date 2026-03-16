# app/engine.py

import os
from dotenv import load_dotenv
import json
import dateparser
from langchain_google_genai import ChatGoogleGenerativeAI
# from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import Tool

# from .database import get_retriever
# from .database import save_property_state, load_property_state
from .database import (
    get_retriever,
    save_property_state,
    load_property_state,
    save_message,
    load_recent_messages,
    save_lead,
    save_booking_state,
    load_booking_state,
    clear_booking_state,
    send_to_google_sheet,
    send_whatsapp_notification,
    PROPERTY_CACHE
)
import re


load_dotenv()

#for good title with title id
def format_property_title(metadata):
    return f"{metadata.get('title')} ({metadata.get('property_id')})"

# -----------------------------
# LLM
# -----------------------------

llm = ChatGoogleGenerativeAI(
    model='gemini-3-flash-preview',
    temperature=0.3,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

#--------------------
#global retriever instance to avoid re-creating on every request. This will load at startup.
#-------------------
# retriever = get_retriever() 

#intent classifier 
def classify_intent(user_query: str) -> str:
    q = user_query.lower()

    # ---------- RULE BASED (FAST PATH) ----------
    if any(w in q for w in ["compare", "vs", "difference"]):
        return "COMPARE"

    if any(w in q for w in ["mortgage", "emi", "monthly payment"]):
        return "MORTGAGE"

    if any(w in q for w in ["roi", "investment", "rental yield"]):
        return "ROI"

    if any(w in q for w in ["book", "schedule", "visit", "call", "meeting"]):
        return "BOOKING"

    if any(w in q for w in ["show", "find", "looking for", "apartment", "house"]):
        return "SEARCH"



    intent_prompt = f"""
You are an intent classifier for a real estate assistant.

Classify the user query into exactly one of these categories:

SEARCH → User is searching for properties
COMPARE → User wants to compare properties
MORTGAGE → User wants mortgage/EMI calculation
ROI → User wants investment or ROI analysis
BOOKING → User wants meeting, call, visit, or agent contact
GENERAL → Anything else

Return only one word: SEARCH, COMPARE, MORTGAGE, ROI, BOOKING, or GENERAL.

Query:
{user_query}
"""

    # response = llm.invoke(intent_prompt)
    # return response.content.strip().upper()

    response = llm.invoke(intent_prompt)

    content = response.content

    # Handle list response (Gemini sometimes returns structured blocks)
    if isinstance(content, list):
        content = " ".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
        )

    intent = content.strip().upper()

    # Extract only valid keyword
    for label in ["SEARCH", "COMPARE", "MORTGAGE", "ROI","BOOKING", "GENERAL"]:
        if label in intent:
            return label

    return "GENERAL"

# -----------------------------
# TOOLS
# -----------------------------

def property_search(query: str, client_id=None, user_id=None, thread_id=None, limit=3):
    """Searches the property database for listings based on location, price, or features."""

    retriever = get_retriever(client_id)
    docs = retriever.invoke(query)

    if not docs:
        return {
            "reply": "No matching properties found.",
            "properties": []
        }

    properties = []
    property_ids = []

    for doc in docs:
        metadata = doc.metadata
        pid = metadata.get("property_id")

        if pid not in property_ids:   # 🔥 prevent duplicates
            property_ids.append(pid)

            properties.append({
                "property_id": pid,
                "title": f"{metadata.get('title')} ({pid})",
                "price_usd": metadata.get("price_usd"),
                "location": metadata.get("location"),
                "bedrooms": metadata.get("bedrooms"),
                "bathrooms": metadata.get("bathrooms"),
                "area_sqft": metadata.get("area_sqft"),
                "image_url": metadata.get("image_url"),
            })

        if len(properties) >= limit:  # Limit to top 10 results
            break

    
    if user_id and thread_id and client_id:
        # Store only first 5 for conversational auto-reference
        auto_reference_ids = property_ids[:5]
        save_property_state(client_id, user_id, thread_id, auto_reference_ids)

    return {
        "reply": f"I found {len(properties)} matching properties.",
        "properties": properties,
        "property_ids": property_ids
    }
# def property_search(query: str) -> str:
#     """Searches the property database for listings based on location, price, or features."""
#     docs = retriever.invoke(query)
    
#     if not docs:
#         return "No matching properties found."
    
#     results = []
#     for doc in docs:
#         results.append(doc.page_content)
    
#     return "\n\n".join(results)


def mortgage_calculator(input_text: str) -> str:
    """
    Calculates monthly mortgage payments.

    Supported formats:

    1) principal=5000000, rate=9, years=20
    2) 5000000,9,20  (principal, interest_rate, years)

    If any field is missing, it asks conversationally.

    """

    try:
        cleaned_input = input_text.replace(" ", "")

        # Format 1: key=value pairs
        if "=" in cleaned_input:
            parts = dict(
                item.split("=")
                for item in cleaned_input.split(",")
                if "=" in item
            )

            principal = float(parts.get("principal", 0))
            rate = float(parts.get("rate", 0))
            years = int(parts.get("years", 0))

        # Format 2: plain comma separated values
        else:
            values = cleaned_input.split(",")

            if len(values) != 3:
                return (
                    "Please provide values in one of these formats:\n\n"
                    "principal=5000000, rate=9, years=20\n"
                    "or\n"
                    "5000000,9,20"
                )

            principal = float(values[0])
            rate = float(values[1])
            years = int(values[2])

        # Validation
        missing = []
        if principal <= 0:
            missing.append("property price")
        if rate <= 0:
            missing.append("interest rate")
        if years <= 0:
            missing.append("loan duration (years)")

        if missing:
            return (
                "To calculate EMI, I need:\n\n"
                f"- {chr(10).join(missing)}"
            )

        # EMI calculation
        monthly_rate = rate / 100 / 12
        months = years * 12

        if monthly_rate == 0:
            emi = principal / months
        else:
            emi = (
                principal
                * monthly_rate
                * (1 + monthly_rate) ** months
                / ((1 + monthly_rate) ** months - 1)
            )

        return (
            f"Mortgage Calculation:\n\n"
            f"Property Price: ${principal:,.2f}\n"
            f"Interest Rate: {rate}%\n"
            f"Loan Term: {years} years\n\n"
            f"Estimated Monthly EMI: ${emi:,.2f}"
        )

    except Exception:
        return (
            "I couldn't process the mortgage calculation.\n"
            "Please use one of these formats:\n\n"
            "principal=5000000, rate=9, years=20\n"
            "or\n"
            "5000000,9,20"
        )



def investment_roi(input_text: str) -> str:
    """
    Expected input:
    price=10000000,rent=50000,years=5,appreciation=5
    or
    price,rent,years,appreciation
    Example:
    5000000,30000,5,5
    """
    try:
        parts = dict(item.split("=") for item in input_text.replace(" ", "").split(","))

        price = float(parts["price"])
        monthly_rent = float(parts["rent"])
        years = int(parts["years"])
        appreciation = float(parts["appreciation"])

        total_rent = monthly_rent * 12 * years
        appreciated_value = price * ((1 + appreciation/100) ** years)

        profit = total_rent + (appreciated_value - price)
        roi = (profit / price) * 100

        return f"""
        Total Rental Income: {round(total_rent, 2)}
        Estimated Property Value After {years} Years: {round(appreciated_value, 2)}
        Total Profit: {round(profit, 2)}
        ROI: {round(roi, 2)}%
        """

    except:
        return "Invalid input format. Use: price=..., rent=..., years=..., appreciation=... or Use: purchase_price,monthly_rent,years,appreciation_rate"


# def compare_properties(query: str, client_id: str) -> str:
#     """Compare multiple properties."""
#     retriever = get_retriever(client_id)
#     docs = retriever.invoke(query)

#     if not docs:
#         return "No properties found for comparison."

#     response = "Comparison Results:\n\n"
#     for doc in docs:
#         response += doc.page_content + "\n\n"

#     return response

#compare using property cache

def compare_properties(property_ids,client_id):

    comparison_properties = []

    for pid in property_ids:

        # metadata = PROPERTY_CACHE.get(pid)
        key = f"{client_id}_{pid}"
        metadata = PROPERTY_CACHE.get(key)

        if not metadata:
            continue

        comparison_properties.append({
            "property_id": metadata.get("property_id"),
            "title": f"{metadata.get('title')} ({metadata.get('property_id')})",
            "price_usd": metadata.get("price_usd"),
            "location": metadata.get("location"),
            "bedrooms": metadata.get("bedrooms"),
            "bathrooms": metadata.get("bathrooms"),
            "area_sqft": metadata.get("area_sqft"),
        })

    return comparison_properties

# -----------------------------
# Register Tools
# -----------------------------

tools = [
    Tool(
    name="PropertySearch",
    func=property_search,
    description="Search for properties based on location, price, or features."
    ),
    Tool(
        name="MortgageCalculator",
        func=mortgage_calculator,
        description="Calculate monthly EMI. Input format: principal=..., rate=..., years=..."

    ),
    Tool(
        name="InvestmentROI",
        func=investment_roi,
        description="Calculate property investment ROI. Input: price=..., rent=..., years=..., appreciation=..."
),
    Tool(
        name="PropertyComparison",
        func=compare_properties,
        description="Compare two properties by title. Input format: title1=..., title2=..."

    ),
]

# -----------------------------
# Prompt
# -----------------------------

SYSTEM_PROMPT = """
You are an expert real estate advisor.

You have access to tools:
1. PropertySearch
2. MortgageCalculator
3. PropertyComparison
4. InvestmentROI

Behavior Rules:
- Use PropertySearch for any listing retrieval.
- Use MortgageCalculator for EMI calculations.
- Use InvestmentROI for ROI or rental analysis.
- Use PropertyComparison when user asks to compare properties.
- Never fabricate numbers.
- Always prefer tool outputs over guessing.
- Present results in clean, structured format.
- Ask clarifying questions if needed.

Tone:
Professional, concise, analytical.
"""


from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}")
])

#llm contact extraction test

def llm_extract_contact(user_query: str):
    extraction_prompt = f"""
Extract name, email, and phone from the text below.
Return ONLY valid JSON.

Text:
{user_query}

Format:
{{
  "name": "...",
  "email": "...",
  "phone": "..."
}}

If any field is missing, return null.
"""

    response = llm.invoke(extraction_prompt)

    try:
        cleaned = response.content.strip()

        # Remove markdown wrapping like ```json ... ```
        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "")
            cleaned = cleaned.replace("```", "")
            cleaned = cleaned.strip()

        data = json.loads(cleaned)
        return data

    except Exception as e:
        return {}


#llm time extraction test
def llm_extract_preferred_time(user_query: str):
    prompt = f"""
Extract the preferred contact time from the text below.

Return ONLY valid JSON in this format:
{{
  "preferred_time": "..."
}}

If no time is mentioned, return:
{{
  "preferred_time": null
}}

Text:
{user_query}
"""

    response = llm.invoke(prompt)

    try:
        cleaned = response.content.strip()

        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "").replace("```", "").strip()

        data = json.loads(cleaned)
        return data.get("preferred_time")

    except:
        return None



# -----------------------------
# Agent
# -----------------------------
from langchain.agents import create_agent
agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt=SYSTEM_PROMPT
)

#time ectraction regex test
import datetime

def extract_preferred_time(user_query: str):
    query = user_query.lower()

    # 1️⃣ Exact time range like "8 am to 10 am"
    range_pattern = r"\b\d{1,2}\s*(am|pm)\s*(to|-)\s*\d{1,2}\s*(am|pm)\b"
    match = re.search(range_pattern, query)
    if match:
        return match.group()

    # 2️⃣ Single time like "3 pm"
    single_time_pattern = r"\b\d{1,2}\s*(am|pm)\b"
    match = re.search(single_time_pattern, query)
    if match:
        return match.group()

    # 3️⃣ Relative days
    today = datetime.date.today()

    if "today" in query:
        base_day = today
    elif "tomorrow" in query:
        base_day = today + datetime.timedelta(days=1)
    elif "next monday" in query:
        days_ahead = (0 - today.weekday() + 7) % 7
        days_ahead = 7 if days_ahead == 0 else days_ahead
        base_day = today + datetime.timedelta(days=days_ahead)
    else:
        base_day = None

    # If base_day exists and user gave specific time
    if base_day:
        time_match = re.search(r"\b\d{1,2}\s*(am|pm)\b", query)
        if time_match:
            return f"{base_day} {time_match.group()}"

    # 4️⃣ Morning / Evening
    if "morning" in query:
        return f"{base_day} morning (9 AM - 12 PM)" if base_day else "morning (9 AM - 12 PM)"

    if "afternoon" in query:
        return f"{base_day} afternoon (1 PM - 4 PM)" if base_day else "afternoon (1 PM - 4 PM)"

    if "evening" in query:
        return f"{base_day} evening (5 PM - 8 PM)" if base_day else "evening (5 PM - 8 PM)"

    return None

# -----------------------------
# Public Function for FastAPI
# -----------------------------

def run_agent(user_query: str, client_id: str, user_id: str, thread_id: str, background_tasks=None):
    print("CLIENT_ID:", client_id)
    print("USER_ID:", user_id)
    print("THREAD_ID:", thread_id)


    # retriever = get_retriever(client_id)


    # 1 Save user message
    save_message(client_id, user_id, thread_id, "user", user_query)

    # ---------------------------
    # CONTACT EXTRACTION
    # ---------------------------
    email = None
    phone = None
    name_detected = None
    email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", user_query)
    phone_match = re.search(r"\+?\d{8,15}", user_query)

# ---------------------------
# Comma Separated Contact Format
# ---------------------------
    if "," in user_query:
        parts = [p.strip() for p in user_query.split(",")]

        for part in parts:
            if re.search(r"[A-Za-z]", part) and "@" not in part:
                name_detected = part
            elif re.search(r"@", part):
                email = part
            elif re.search(r"\d{8,}", part):
                phone = re.search(r"\d{8,}", part).group()

    # 2 Fallback to regex only if still empty
    if not email and email_match:
        email = email_match.group()

    if not phone and phone_match:
        phone = phone_match.group()

    # ---------------------------
    # SMART NAME REGEX EXTRACTION
    # ---------------------------

    # 3 Smart name detection (optional)
    name_patterns = [
        r"my name is ([A-Za-z ]+?)(\.|,|$)",
        r"i am ([A-Za-z ]+?)(\.|,|$)",
        r"this is ([A-Za-z ]+?)(\.|,|$)"
    ]

    for pattern in name_patterns:
        match = re.search(pattern, user_query, re.IGNORECASE)
        if match:
            name_detected = match.group(1).strip()
            break

    # email = email_match if isinstance(email_match, str) else (email_match.group() if email_match else None)
    # phone = phone_match if isinstance(phone_match, str) else (phone_match.group() if phone_match else None)

    # ---------------------------
    # TIME WINDOW EXTRACTION
    # ---------------------------
    time_pattern = r"\b\d{1,2}\s*(am|pm)\s*(to|-)\s*\d{1,2}\s*(am|pm)\b"
    time_match = re.search(time_pattern, user_query.lower())

    


    # ---------------------------
    # Load Memory
    # ---------------------------
    history = load_recent_messages(client_id, user_id, thread_id, limit=7)
    stored_ids = load_property_state(client_id, user_id, thread_id)

    # ---------------------------
    # Intent Classification (Safe)
    # ---------------------------
    booking_state = load_booking_state(client_id, user_id, thread_id)
    if booking_state:
        intent = "BOOKING"
    else:
        intent_raw = classify_intent(user_query)

        for label in ["SEARCH", "COMPARE", "MORTGAGE", "ROI", "BOOKING", "GENERAL"]:
            if label in intent_raw:
                intent = label
                break
        else:
            intent = "GENERAL"

    # ---------------------------
    # High Intent Booking Detection
    # ---------------------------
    # intent_words = ["book", "schedule", "visit", "view", "appointment", "meeting", "call", "contact"]
    lower_query = user_query.lower()

    # is_high_intent = any(word in lower_query for word in intent_words)

    # if is_high_intent and stored_ids:
    #     reply = "Great choice. I can help arrange a viewing.\n\nMay I have your name and preferred contact (email or WhatsApp)?"
    #     save_message(user_id, thread_id, "assistant", reply)
    #     return {"reply": reply, "properties": None, "analysis": None}

    # if is_high_intent and not stored_ids:
    #     reply = "I'd be happy to arrange something for you. Could you please tell me which property you're referring to?"
    #     save_message(user_id, thread_id, "assistant", reply)
    #     return {"reply": reply, "properties": None, "analysis": None}
    

    # ---------------------------
    # Booking Block (Lead First Strategy) and booking state
    # ---------------------------
    booking_state = load_booking_state(client_id, user_id, thread_id)

    if intent == "BOOKING" or booking_state:

        if not booking_state:
            save_booking_state(client_id, user_id, thread_id, stage="collecting_contact")
            booking_state = load_booking_state(client_id, user_id, thread_id)

        preferred_time = None

        parsed_time = dateparser.parse(
            user_query,
            settings={
                "PREFER_DATES_FROM": "future"
            }
        )

        # --- TIME EXTRACTION ---
        if parsed_time:
            preferred_time = parsed_time.strftime("%Y-%m-%d %H:%M")
        else:
            time_keywords = [
                "am", "pm", "morning", "afternoon", "evening",
                "today", "tomorrow", "weekend", "week", "day"
            ]

            if (
                booking_state
                and booking_state.get("phone")
                and booking_state.get("property_ids")
                and not booking_state.get("preferred_time")
                and any(word in user_query.lower() for word in time_keywords)
            ):
                preferred_time = user_query.strip()


        # --- 🔥 ALWAYS UPDATE BOOKING STATE ---
        updates = {}

        if name_detected:
            updates["name"] = name_detected

        if email:
            updates["email"] = email

        if phone:
            updates["phone"] = phone

        if preferred_time:
            updates["preferred_time"] = preferred_time

        if updates:
            save_booking_state(client_id, user_id, thread_id, **updates)

        booking_state = load_booking_state(client_id, user_id, thread_id)
        print("UPDATED BOOKING STATE:", booking_state)

        # 1 Collect Contact
        print("CONTACT EXTRACTED:", name_detected, email, phone)
        # print("BOOKING STATE NOW:", booking_state)
        if not booking_state["phone"]:
            reply = (
                "I'd be happy to arrange that.\n\n"
                "May I have your full name, email, and phone number? i.e John,jj@example.com,123456789"
            )
            save_message(client_id, user_id, thread_id, "assistant", reply)
            return {"reply": reply, "properties": None, "analysis": None}
        
        # --- SAVE COLD LEAD ONLY ONCE ---
        if (
            booking_state["phone"]
            and not booking_state.get("lead_stage_saved")
        ):
            save_lead(
                client_id=client_id,
                user_id=user_id,
                thread_id=thread_id,
                name=booking_state["name"],
                email=booking_state["email"],
                whatsapp=booking_state["phone"],
                preferred_time=None,
                preferred_properties=None,
                lead_type="Cold"
            )

            save_booking_state(
                client_id,
                user_id,
                thread_id,
                lead_stage_saved="Cold"
            )            


       
        # 2 Collect Property
        stored_ids = load_property_state(client_id, user_id, thread_id)

        if not booking_state["property_ids"]:

            # Try detecting property ID directly (USA0615 etc.)
            id_match = re.search(r"\b[A-Z]{2,}\d+\b", user_query.upper())

            selected_property = None

            if id_match:
                candidate_id = id_match.group()

                # Validate property exists in database
                cache_key = f"{client_id}_{candidate_id}"
                if cache_key in PROPERTY_CACHE:
                    selected_property = candidate_id
                # if candidate_id in PROPERTY_CACHE:
                #     selected_property = candidate_id
                else:
                    reply = "That property ID does not exist. Please check and try again."
                    save_message(client_id, user_id, thread_id, "assistant", reply)
                    return {"reply": reply, "properties": None, "analysis": None}

            else:
                # Detect ordinal words (first, second, etc.)
                ordinal_map = {
                    "first": 0,
                    "second": 1,
                    "third": 2,
                    "fourth": 3,
                    "fifth": 4
                }

                for word, index in ordinal_map.items():
                    if word in user_query.lower() and index < len(stored_ids):
                        selected_property = stored_ids[index]
                        break

            if selected_property:
                save_booking_state(
                    client_id,
                    user_id,
                    thread_id,
                    property_ids=json.dumps([selected_property])
                )

                booking_state = load_booking_state(client_id, user_id, thread_id)
                if (
                    booking_state["phone"]
                    and booking_state["property_ids"]
                    and booking_state.get("lead_stage_saved") == "Cold"
                ):
                    save_lead(
                        client_id=client_id,
                        user_id=user_id,
                        thread_id=thread_id,
                        name=booking_state["name"],
                        email=booking_state["email"],
                        whatsapp=booking_state["phone"],
                        preferred_time=None,
                        preferred_properties=json.loads(booking_state["property_ids"]),
                        lead_type="Warm"
                    )

                    save_booking_state(
                        client_id,
                        user_id,
                        thread_id,
                        lead_stage_saved="Warm"
                    )
            else:
                reply = (
                    "Which property are you interested in?\n"
                    "You can mention property ID or say first, second, etc."
                )
                save_message(client_id, user_id, thread_id, "assistant", reply)
                return {"reply": reply, "properties": None, "analysis": None}

        

        # 3 Collect Time
        print("EXTRACTED TIME:", preferred_time)
        print("BOOKING STATE BEFORE CHECK:", booking_state)

        if not booking_state["preferred_time"]:
            reply = (
                "What would be your preferred time for a quick call?\n"
                "Example: Tomorrow 5 PM."
            )
            save_message(client_id,user_id, thread_id, "assistant", reply)
            return {"reply": reply, "properties": None, "analysis": None}
        #lead scoring
        
        has_phone = booking_state["phone"] is not None
        has_property = booking_state["property_ids"] is not None
        has_time = booking_state["preferred_time"] is not None

        if has_phone and has_property and has_time:
            lead_type = "Hot"
        elif has_phone and has_property:
            lead_type = "Warm"
        elif has_phone:
            lead_type = "Cold"
        else:
            lead_type = "Cold"


        # 4 Save Final Lead
        confirmed_property_ids = []

        if booking_state["property_ids"]:
            confirmed_property_ids = json.loads(booking_state["property_ids"])

        save_lead(
            client_id=client_id,
            user_id=user_id,
            thread_id=thread_id,
            name=booking_state["name"],
            email=booking_state["email"],
            whatsapp=booking_state["phone"],
            preferred_time=booking_state["preferred_time"],
            preferred_properties=confirmed_property_ids,
            lead_type="Hot"
        )

        save_booking_state(
            client_id,
            user_id,
            thread_id,
            lead_stage_saved="Hot"
        )

        if background_tasks:
            background_tasks.add_task(
                send_to_google_sheet,
                user_id,
                booking_state["name"],
                booking_state["email"],
                booking_state["phone"],
                booking_state["preferred_time"],
                "chatbot",
                confirmed_property_ids,
                lead_type
            )
            background_tasks.add_task(
                send_whatsapp_notification,
                client_id,
                booking_state["name"],
                booking_state["phone"],
                confirmed_property_ids,
                booking_state["preferred_time"]
            )

        # send_to_google_sheet(
        #     user_id=user_id,
        #     name=booking_state["name"],
        #     email=booking_state["email"],
        #     whatsapp=booking_state["phone"],
        #     preferred_time=booking_state["preferred_time"],
        #     preferred_properties=confirmed_property_ids,
        #     lead_type=lead_type
        # )

        clear_booking_state(client_id, user_id, thread_id)

        reply = "Thank you. Our agent will contact you at your preferred time."
        save_message(client_id, user_id, thread_id, "assistant", reply)

        return {"reply": reply, "properties": None, "analysis": None}


    
    # if intent == "BOOKING":

    #     # Check if we already have contact info saved in this message
    #     if not phone:
    #         reply = (
    #             "I'd be happy to arrange that for you.\n\n"
    #             "To proceed, may I have:\n"
    #             "• Your full name\n"
    #             "• Your email address\n"
    #             "• Your phone number (WhatsApp preferred)\n\n"
    #             "Our specialist will contact you shortly."
    #         )

    #         save_message(user_id, thread_id, "assistant", reply)
    #         return {"reply": reply, "properties": None, "analysis": None}

    #     # If phone/email detected, now ask about property
    #     stored_ids = load_property_state(user_id, thread_id)

    #     if not stored_ids:
    #         reply = (
    #             "Thank you. Could you please tell me which property you are interested in?\n"
    #             "You can mention the property ID or say first, second, etc."
    #         )

    #         save_message(user_id, thread_id, "assistant", reply)
    #         return {"reply": reply, "properties": None, "analysis": None}

    #     # If properties exist, ask preferred call time
    #     reply = (
    #         "Perfect. One last thing — what would be your preferred time for a quick call?\n"
    #         "For example: Today 5 PM or Tomorrow morning."
    #     )

    #     save_message(user_id, thread_id, "assistant", reply)
    #     return {"reply": reply, "properties": None, "analysis": None}







    # ---------------------------
    # SEARCH
    # ---------------------------
    if intent == "SEARCH":
        lower_query = user_query.lower()

        if "show more" in lower_query or "more" in lower_query:
            result = property_search(user_query,client_id=client_id, user_id=user_id, thread_id=thread_id, limit=6)
        else:
            result = property_search(user_query, client_id=client_id, user_id=user_id, thread_id=thread_id, limit=3)

        # reply = result.get("reply") + "\n\nIf you'd like, I can arrange a viewing or connect you with the listing agent."
        reply = result.get("reply")
        reply += "\n\nIf you'd like, I can arrange a viewing or connect you with an agent to discuss these options."
        
        
        save_message(client_id,user_id, thread_id, "assistant", reply)
        return {
            "reply": reply,
            "properties": result.get("properties"),
            "analysis": None
        }

    # ---------------------------
    # COMPARE
    # ---------------------------
    if intent == "COMPARE":

        if not stored_ids:
            reply = "Please search for properties first before comparing."
            save_message(client_id,user_id, thread_id, "assistant", reply)
            return {"reply": reply, "properties": None, "analysis": None}

        # ---------------------------
        # 1️⃣ Direct Property ID Detection
        # ---------------------------
        id_matches = re.findall(r"\b[A-Z]{2,}\d+\b", user_query.upper())

        if len(id_matches) >= 2:
            ids_to_compare = id_matches[:2]

        else:
            detected_indexes = []

            # ---------------------------
            # 2️⃣ Word Ordinals
            # ---------------------------
            ordinal_map = {
                "first": 0,
                "second": 1,
                "third": 2,
                "fourth": 3,
                "fifth": 4,
                "sixth": 5,
                "seventh": 6,
                "eighth": 7,
                "ninth": 8,
                "tenth": 9
            }

            for word, index in ordinal_map.items():
                if re.search(rf"\b{word}\b", user_query.lower()):
                    detected_indexes.append(index)

            # ---------------------------
            # 3️⃣ Numeric Ordinals (1st, 2nd, 3rd...)
            # ---------------------------
            numeric_matches = re.findall(r"\b(\d+)(st|nd|rd|th)\b", user_query.lower())

            for match in numeric_matches:
                number = int(match[0]) - 1
                detected_indexes.append(number)

            # ---------------------------
            # 4️⃣ "First two properties"
            # ---------------------------
            if "first two" in user_query.lower():
                detected_indexes = [0, 1]

            detected_indexes = list(set(detected_indexes))

            if len(detected_indexes) < 2:
                reply = "Please mention at least two properties to compare."
                save_message(client_id, user_id, thread_id, "assistant", reply)
                return {"reply": reply, "properties": None, "analysis": None}

            if any(i >= len(stored_ids) for i in detected_indexes):
                reply = "One of the selected properties is not in the current results."
                save_message(client_id, user_id, thread_id, "assistant", reply)
                return {"reply": reply, "properties": None, "analysis": None}

            ids_to_compare = [stored_ids[i] for i in detected_indexes[:2]]

        # ---------------------------
        # Build Comparison
        # ---------------------------
        reply = "Here is a side-by-side comparison of the selected properties."

        # comparison_properties = []
        # analysis = {} #or give it none
        # for pid in ids_to_compare:
        #     metadata = PROPERTY_CACHE.get(pid)

        #     if not metadata:
        #         continue

        #     comparison_properties.append({
        #         "property_id": metadata.get("property_id"),
        #         "title": f"{metadata.get('title')} ({metadata.get('property_id')})",
        #         "price_usd": metadata.get("price_usd"),
        #         "location": metadata.get("location"),
        #         "bedrooms": metadata.get("bedrooms"),
        #         "bathrooms": metadata.get("bathrooms"),
        #         "area_sqft": metadata.get("area_sqft"),
        #     })
        comparison_properties = compare_properties(ids_to_compare,client_id)
        analysis = {}

        if len(comparison_properties) == 2:
            p1 = comparison_properties[0]
            p2 = comparison_properties[1]

            summary = []

            if p1["price_usd"] > p2["price_usd"]:
                summary.append(f"{p1['title']} is more expensive.")
            elif p2["price_usd"] > p1["price_usd"]:
                summary.append(f"{p2['title']} is more expensive.")

            if p1["area_sqft"] > p2["area_sqft"]:
                summary.append(f"{p1['title']} offers more space.")
            elif p2["area_sqft"] > p1["area_sqft"]:
                summary.append(f"{p2['title']} offers more space.")

            analysis = {
                "summary": " ".join(summary)
            }

        if len(comparison_properties) < 2:
            reply = "I couldn't find both properties to compare. Please check the property IDs."
            save_message(client_id, user_id, thread_id, "assistant", reply)
            return {"reply": reply, "properties": None, "analysis": None}
        
        reply = "Here is a side-by-side comparison of the selected properties."

        save_message(client_id, user_id, thread_id, "assistant", reply)

        return {
            "reply": reply,
            "properties": comparison_properties,
            "analysis": analysis
            
        }



    # ---------------------------
    # MORTGAGE
    # ---------------------------
    if intent == "MORTGAGE":

        if not stored_ids:
            reply = "Please search for properties first before calculating a mortgage."
            save_message(client_id,user_id, thread_id, "assistant", reply)
            return {"reply": reply, "properties": None, "analysis": None}

        property_index = 0
        ordinal_map = {
            "first": 0,
            "second": 1,
            "third": 2,
            "fourth": 3,
            "fifth": 4
        }

        for word, index in ordinal_map.items():
            if word in user_query.lower():
                property_index = index

        id_match = re.search(r"\b[A-Z]{2,}\d+\b", user_query)

        if id_match:
            selected_property_id = id_match.group()
        else:
            if property_index >= len(stored_ids):
                reply = "That property is not in the current session results. Please provide the property ID."
                save_message(client_id, user_id, thread_id, "assistant", reply)
                return {"reply": reply, "properties": None, "analysis": None}

            selected_property_id = stored_ids[property_index]

        # docs = retriever.invoke(f"property_id:{selected_property_id}")
        # metadata = PROPERTY_CACHE.get(selected_property_id)
        key=f"{client_id}_{selected_property_id}"
        metadata = PROPERTY_CACHE.get(key)

        if not metadata:
            reply = "Could not find the selected property."
            save_message(client_id, user_id, thread_id, "assistant", reply)
            return {"reply": reply, "properties": None, "analysis": None}
        
        price = metadata.get("price_usd")

        rate_match = re.search(r"(\d+)\s*percent", user_query.lower())
        years_match = re.search(r"(\d+)\s*year", user_query.lower())

        rate = float(rate_match.group(1)) if rate_match else 8.0
        years = int(years_match.group(1)) if years_match else 20

        mortgage_input = f"principal={price}, rate={rate}, years={years}"
        emi_result = mortgage_calculator(mortgage_input)

        default_year_used = False

        if not years_match:
            default_year_used = True

        reply = f"""
        Mortgage Estimate for {metadata.get("title")} ({selected_property_id}):

        Price: ${price}
        Interest Rate: {rate}%
        Loan Term: {years} years

        {emi_result}
        """

        if default_year_used:
            reply += (
                "\n\nThis estimate is based on a 20-year loan term. "
                "Would you like to explore a different duration (e.g., 15 or 30 years)?"
            )
        else:
            reply += "\n\nWould you like to explore other loan term options?"



        reply += "\n\nIf you'd like, I can connect you with a financing specialist to explore your options."
        save_message(client_id, user_id, thread_id, "assistant", reply)

        return {"reply": reply, "properties": None, "analysis": None}

    # ---------------------------
    # ROI
    # ---------------------------
    if intent == "ROI":
        result = investment_roi(user_query)
        result += "\n\nWould you like to speak with an advisor about this investment opportunity?"
        save_message(client_id, user_id, thread_id, "assistant", result)
        return {"reply": result, "properties": None, "analysis": None}

    # ---------------------------
    # FALLBACK AGENT
    # ---------------------------
    result = agent.invoke({
        "messages": [
            *history,
            {"role": "user", "content": user_query}
        ]
    })

    final = result["messages"][-1].content

    if isinstance(final, list):
        final = " ".join(block["text"] for block in final if block["type"] == "text")

    save_message(client_id, user_id, thread_id, "assistant", final)

    return {"reply": final, "properties": None, "analysis": None}
    