import os
import math
import httpx
from fastapi import FastAPI, Request, Query, Response, Form
from fastapi.responses import PlainTextResponse

# ---------------------------------------------------------
# FASTAPI APP INITIALIZATION
# ---------------------------------------------------------
app = FastAPI(title="Multi-Channel Recommendation Bot")

# ---------------------------------------------------------
# CONFIGURATION & ENVIRONMENT VARIABLES
# ---------------------------------------------------------
# NOTE: This MUST be the Google Apps Script Web App URL ending in /exec
SHEET_API_URL = os.getenv("SHEET_API_URL", "https://script.google.com/macros/s/AKfycbxUO_gkGP30LVozcxZWl_BjtaaOJC-q23SgG-0fn32RSpU7l1Jn89oeMgc8aoxJyN1ynQ/exec")

# Telegram Config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8811090240:AAFNMoQKp3h99xVFQhbK9-MqV1rSsEIO2Ig")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Twilio WhatsApp Config
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "whatsapp:+17372212163")

# WhatsApp (Meta Cloud API) Config
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "MY_SECURE_VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "YOUR_META_PERMANENT_ACCESS_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "YOUR_PHONE_NUMBER_ID")


# ---------------------------------------------------------
# 1. CORE RECOMMENDATION LOGIC (SHARED ENGINE)
# ---------------------------------------------------------
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates distance between two coordinates in kilometers."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

async def get_nearby_recommendations(
    user_lat: float,
    user_lng: float,
    max_radius_km: float = 15.0
):
    async with httpx.AsyncClient(
        follow_redirects=True
    ) as client:

        res = await client.get(SHEET_API_URL)

        print("====================================")
        print("SHEET STATUS:", res.status_code)
        print("SHEET CONTENT TYPE:", res.headers.get("content-type"))
        print("SHEET URL:", str(res.url))
        print("SHEET RESPONSE:")
        print(res.text[:2000])
        print("====================================")

        res.raise_for_status()

        places = res.json()

    results = []

    for place in places:
        try:
            p_lat = float(place.get("Latitude"))
            p_lng = float(place.get("Longitude"))

            dist = haversine(
                user_lat,
                user_lng,
                p_lat,
                p_lng
            )

            if dist <= max_radius_km:
                results.append({
                    "name": place.get("Name"),
                    "category": place.get("Category"),
                    "rating": place.get("Rating"),
                    "notes": place.get("Notes/Must-Try"),
                    "maps": place.get("Final Maps Link"),
                    "distance": round(dist, 2)
                })

        except (ValueError, TypeError):
            continue

    return sorted(
        results,
        key=lambda x: x["distance"]
    )[:3]

def format_recommendation_text(recs: list, is_telegram: bool = True) -> str:
    """Formats recommendations into clean Markdown for messaging apps."""
    if not recs:
        return "📍 *No saved recommendations found within 15 km of your location.*"

    text = "📍 *Top Places Near You:*\n\n"
    for r in recs:
        text += f"⭐ *{r['name']}* ({r['category']})\n"
        text += f"• Distance: {r['distance']} km\n"
        text += f"• Rating: {r['rating']}/5\n"
        if r['notes']:
            text += f"• Notes/Must-Try: _{r['notes']}_\n" if is_telegram else f"• Note: {r['notes']}\n"
        if r['maps']:
            text += f"• [Google Maps]({r['maps']})\n" if is_telegram else f"• Maps: {r['maps']}\n"
        text += "\n"
    return text


# ---------------------------------------------------------
# 2. TELEGRAM CHANNEL ADAPTER
# ---------------------------------------------------------
async def send_telegram_message(chat_id: int, text: str):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    payload = await request.json()
    if "message" not in payload:
        return {"status": "ok"}

    message = payload["message"]
    chat_id = message["chat"]["id"]

    if "location" in message:
        lat = message["location"]["latitude"]
        lng = message["location"]["longitude"]
        recs = await get_nearby_recommendations(lat, lng)
        reply = format_recommendation_text(recs, is_telegram=True)
        await send_telegram_message(chat_id, reply)
    else:
        text = message.get("text", "")
        if text.startswith("/start"):
            welcome = (
             "✨ *Welcome to Pran’s Pins!*\n\n"
    "Whether you need a cozy cafe, great food, or a quiet getaway, I’ve got you covered.\n\n"
    "📍 Share your location pin with me (📎 / ➕ ➔ Location), and I’ll show you the best hand-picked spots near you!"          )
            await send_telegram_message(chat_id, welcome)
        else:
            await send_telegram_message(chat_id, "📍 Please drop a location pin to find recommendations.")

    return {"status": "ok"}
