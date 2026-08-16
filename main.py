import math
import httpx
from fastapi import FastAPI, Request, Query, Response

app = FastAPI()

# Configuration
VERIFY_TOKEN = "MY_SECURE_VERIFY_TOKEN"
WHATSAPP_TOKEN = "YOUR_META_ACCESS_TOKEN"
PHONE_NUMBER_ID = "YOUR_WHATSAPP_PHONE_NUMBER_ID"
SHEET_API_URL = "https://script.google.com/macros/s/AKfycbzgOMGpzbRkBSJWNPfvWeo4qKbOpVFkoW2xkRuhQSm3M7TAK3siq2rhFAfb64PAOr6cOA/exec"

# 1. Haversine Distance Calculation (in km)
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0  # Earth's radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# 2. WhatsApp Verification Handshake
@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(status_code=403)

# 3. Core Engine: Fetch, Filter, and Rank
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

    # Sort by nearest distance first
    return sorted(results, key=lambda x: x["distance"])[:3]

# 4. Outbound WhatsApp Message Dispatcher
async def send_whatsapp_message(to_number: str, message_text: str):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
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

# 5. Inbound Webhook Listener
@app.post("/webhook")
async def handle_incoming(request: Request):
    payload = await request.json()
    
    try:
        entry = payload["entry"][0]["changes"][0]["value"]
        if "messages" not in entry:
            return {"status": "ignored"}
            
        message = entry["messages"][0]
        sender = message["from"]

        # If user sends a live/pin location
        if message["type"] == "location":
            lat = message["location"]["latitude"]
            lng = message["location"]["longitude"]
            
            recs = await find_recommendations(lat, lng)
            if not recs:
                reply = "No saved recommendations found within 15 km of your location."
            else:
                reply = "📍 *Top Places Near You:*\n\n"
                for r in recs:
                    reply += f"⭐ *{r['name']}* ({r['category']})\n"
                    reply += f"• Distance: {r['distance']} km\n"
                    reply += f"• Rating: {r['rating']}/5\n"
                    if r['notes']:
                        reply += f"• Note: {r['notes']}\n"
                    if r['maps']:
                        reply += f"• Link: {r['maps']}\n"
                    reply += "\n"
            await send_whatsapp_message(sender, reply)
        else:
            await send_whatsapp_message(sender, "Send your location pin via WhatsApp to find nearby recommendations!")
            
    except Exception as e:
        print(f"Error: {e}")
        
    return {"status": "ok"}
