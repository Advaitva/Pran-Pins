import os
import math
import httpx
from fastapi import FastAPI, Request, Query, Response

app = FastAPI(title="Multi-Channel Recommendation Bot")

# ---------------------------------------------------------
# CONFIGURATION & ENVIRONMENT VARIABLES
# ---------------------------------------------------------
SHEET_API_URL = os.getenv("SHEET_API_URL", "https://docs.google.com/spreadsheets/d/1PVvVnUfudCfcl2LAMKf0VITaSevPn6JKpkcswrGDByU/edit?resourcekey=&gid=1143725382#gid=1143725382")

# Telegram Config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8811090240:AAFNMoQKp3h99xVFQhbK9-MqV1rSsEIO2Ig")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# WhatsApp (Meta) Config
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

async def get_nearby_recommendations(user_lat: float, user_lng: float, max_radius_km: float = 15.0):
    """Fetches places from Google Sheets and filters by distance."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        res = await client.get(SHEET_API_URL)
        places = res.json()

    results = []
    for place in places:
        try:
            p_lat = float(place.get("Latitude"))
            p_lng = float(place.get("Longitude"))
            dist = haversine(user_lat, user_lng, p_lat, p_lng)
            if dist <= max_radius_km:
                results.append({
                    "name": place.get("Name"),
                    "category": place.get("Category"),
                    "rating": place.get("Rating"),
                    "notes": place.get("Notes / Must-Try"),
                    "maps": place.get("Maps Link"),
                    "distance": round(dist, 2)
                })
        except (ValueError, TypeError):
            continue

    return sorted(results, key=lambda x: x["distance"])[:3]

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
            text += f"• Note: _{r['notes']}_\n" if is_telegram else f"• Note: {r['notes']}\n"
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
                "👋 *Welcome to SpotFinder!*\n\n"
                "Send your location pin (📎 $\rightarrow$ Location) to get top-rated nearby spots."
            )
            await send_telegram_message(chat_id, welcome)
        else:
            await send_telegram_message(chat_id, "📍 Please drop a location pin to find recommendations.")

    return {"status": "ok"}


# ---------------------------------------------------------
# 3. WHATSAPP (META) CHANNEL ADAPTER
# ---------------------------------------------------------
async def send_whatsapp_message(to_number: str, message_text: str):
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message_text}
    }
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload, headers=headers)

# Meta Handshake Verification
@app.get("/whatsapp/webhook")
async def verify_whatsapp_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    if hub_mode == "subscribe" and hub_verify_token == META_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(status_code=403)

# Meta Inbound Message Handler
@app.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    payload = await request.json()
    try:
        entry = payload["entry"][0]["changes"][0]["value"]
        if "messages" not in entry:
            return {"status": "ignored"}

        message = entry["messages"][0]
        sender = message["from"]

        if message["type"] == "location":
            lat = message["location"]["latitude"]
            lng = message["location"]["longitude"]
            recs = await get_nearby_recommendations(lat, lng)
            reply = format_recommendation_text(recs, is_telegram=False)
            await send_whatsapp_message(sender, reply)
        else:
            await send_whatsapp_message(sender, "📍 Send a location pin via WhatsApp to see nearby recommendations!")

    except Exception as e:
        print(f"WhatsApp Webhook Error: {e}")

    return {"status": "ok"}
