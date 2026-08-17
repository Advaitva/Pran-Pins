import math
import httpx
from fastapi import FastAPI, Request

app = FastAPI()

# Configuration
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_FROM_BOTFATHER"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
SHEET_API_URL = "https://docs.google.com/spreadsheets/d/1PVvVnUfudCfcl2LAMKf0VITaSevPn6JKpkcswrGDByU/edit?resourcekey=&gid=1143725382#gid=1143725382"

# 1. Haversine Distance Formula (km)
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# 2. Fetch Places from Google Sheet
async def find_recommendations(user_lat: float, user_lng: float, max_radius_km: float = 15.0):
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

# 3. Outbound Message Dispatcher (Telegram)
async def send_telegram_message(chat_id: int, text: str):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)

# 4. Inbound Telegram Webhook Receiver
@app.post("/webhook")
async def telegram_webhook(request: Request):
    payload = await request.json()
    
    if "message" not in payload:
        return {"status": "ok"}
    
    message = payload["message"]
    chat_id = message["chat"]["id"]
    
    # Handle Location Pin
    if "location" in message:
        user_lat = message["location"]["latitude"]
        user_lng = message["location"]["longitude"]
        
        recs = await find_recommendations(user_lat, user_lng)
        
        if not recs:
            reply = "📍 *No saved recommendations found within 15 km of your location.*"
        else:
            reply = "📍 *Top Places Near You:*\n\n"
            for r in recs:
                reply += f"⭐ *{r['name']}* ({r['category']})\n"
                reply += f"• Distance: `{r['distance']} km`\n"
                reply += f"• Rating: {r['rating']}/5\n"
                if r['notes']:
                    reply += f"• Note: _{r['notes']}_\n"
                if r['maps']:
                    reply += f"• [Open in Google Maps]({r['maps']})\n"
                reply += "\n"
                
        await send_telegram_message(chat_id, reply)
    
    # Handle Text / Welcome Commands
    else:
        text = message.get("text", "")
        if text.startswith("/start"):
            welcome = (
                "👋 *Welcome to SpotFinder!*\n\n"
                "Send me your current location or drop a pin using the attachment button (📎 $\rightarrow$ Location), "
                "and I'll show you my top-rated places nearby."
            )
            await send_telegram_message(chat_id, welcome)
        else:
            await send_telegram_message(chat_id, "📍 Please share a location pin to find nearby spots.")
            
    return {"status": "ok"}
