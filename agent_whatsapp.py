import json
import os
from datetime import datetime, timezone, timedelta
import requests
from fastapi import FastAPI, Request, Response

# ------------------------------------------------------------------------------
# 1. Configuración desde Variables de Entorno de Render
# ------------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6Kgnd0mzuoF1_SSh735CY_Q8_e00DY_RJJYOxz1VmFx3w")
WHATSAPP_TOKEN = os.environ.get(
    "WHATSAPP_TOKEN",
    "EAAeol1PvNZAIBSnJhPSTbOmewq3xS5H229ZC5PL2vZCyvnnxc6xMSnZBxJC1YygA1mQZBNlT2S14kVp5TlGvo4SoErjciw2pP0S5yqz6ukG8h5GrWKewyV9EzILwf10o515hQEe6ZCuWx3xXQOtcCLQkb3IXUkyfOoAzZC8OZCgZBvZClfz86bEzlKt5PWs3PDbgZDZD"
)
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1293789687158465")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "don_tito_ferreteria_secret_token")

try:
    with open("catalog.json", "r", encoding="utf-8") as f:
        catalog_data = json.load(f)
    catalog_text = "\n".join([
        f"- {p['nombre']} (SKU: {p['sku']}): ${p['precio']:,} CLP | Stock: {p['stock']} un | Categoría: {p['categoria']}"
        for p in catalog_data
    ])
    print("✅ Catálogo cargado correctamente desde catalog.json")
except Exception as e:
    print(f"⚠️ Error cargando catalog.json: {e}")
    catalog_text = "- Bekron Estándar Sacos 25kg (SKU: ADH-019): $6.490 CLP | Stock: 95 un"

def obtener_contexto_horario():
    """Calcula el contexto de fecha y hora para Chile (UTC-3)."""
    tz_chile = timezone(timedelta(hours=-3))
    ahora = datetime.now(tz_chile)
    
    dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_str = dias_semana[ahora.weekday()]
    hora_str = ahora.strftime("%H:%M")
    
    es_domingo = ahora.weekday() == 6
    hora_decimal = ahora.hour + ahora.minute / 60.0
    
    en_turno_manana = 9.0 <= hora_decimal < 13.0
    en_turno_tarde = 14.5 <= hora_decimal < 18.5
    
    esta_abierto = (not es_domingo) and (en_turno_manana or en_turno_tarde)
    estado = "ABIERTO (atención presencial)" if esta_abierto else "CERRADO (fuera de horario de atención)"
    
    return f"Momento actual: {dia_str} a las {hora_str} hrs. Estado del local: {estado}."

# ------------------------------------------------------------------------------
# 2. Funciones de Consulta a Gemini y Envío a WhatsApp
# ------------------------------------------------------------------------------
def send_whatsapp_message(recipient, text):
    """Envía el mensaje de respuesta al cliente vía WhatsApp."""
    token_actual = os.environ.get("WHATSAPP_TOKEN", WHATSAPP_TOKEN)
    phone_id_actual = os.environ.get("PHONE_NUMBER_ID", PHONE_NUMBER_ID)

    url = f"https://graph.facebook.com/v20.0/{phone_id_actual}/messages"
    headers = {
        "Authorization": f"Bearer {token_actual}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"body": text},
    }

    response = requests.post(url, json=payload, headers=headers)
    print(f"📤 Estado del envío a Meta: {response.status_code}")
    if response.status_code != 200:
        print(f"❌ Detalles error Meta: {response.text}")

def ask_don_tito(user_text):
    """Consulta a Gemini 3.8 Flash construyendo el prompt con las reglas de Don Tito."""
    gemini_key = os.environ.get("GEMINI_API_KEY", GEMINI_API_KEY)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={gemini_key}"
    
    contexto = obtener_contexto_horario()

    prompt_instrucciones = f"""Eres Don Tito, un ferretero experto, amable y directo de Chiloé.
Reglas de atención:
1. Eres claro, preciso y directo al responder sobre productos, precios y stock.
2. No hagas ofertas excesivas ni intentes vender de forma pesada; entrega el dato exacto.
3. Si un producto no está disponible o no existe en el catálogo, sugiere solo una alternativa muy cercana.
4. Si el cliente pide compras al por mayor, descuentos por volumen, productos fuera de catálogo o solicita hablar con un humano, activa el Criterio A y deriva al +56939270181.
5. REGLA DE HORARIO: Revisa el contexto de fecha/hora. Si el estado es CERRADO, saluda, responde la duda del catálogo, pero advierte amablemente que el local se encuentra cerrado y que la solicitud quedará registrada.

Contexto horario actual: [{contexto}]

Catálogo de productos disponibles:
{catalog_text}

Mensaje del cliente: {user_text}
"""

    payload = {
        "contents": [
            {
                "parts": [{"text": prompt_instrucciones}]
            }
        ]
    }
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            print(f"❌ Error HTTP de Gemini ({response.status_code}): {response.text}")
            return "Lo siento compadre, ocurrió un problema al consultar el sistema."
    except Exception as e:
        print(f"❌ Excepción en llamada Gemini: {e}")
        return "Lo siento compadre, ocurrió un problema al consultar el sistema."

# ------------------------------------------------------------------------------
# 3. Servidor Web
# ------------------------------------------------------------------------------
app = FastAPI(title="API Ferretería Don Tito")

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    verify_token_actual = os.environ.get("VERIFY_TOKEN", VERIFY_TOKEN)
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == verify_token_actual:
        return Response(content=params.get("hub.challenge"), status_code=200, media_type="text/plain")
    return Response(content="Error de verificación", status_code=403)

@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    body = await request.json()
    try:
        entries = body.get("entry", [])
        if entries:
            changes = entries[0].get("changes", [])
            if changes:
                value = changes[0].get("value", {})
                messages = value.get("messages", [])
                if messages:
                    msg = messages[0]
                    from_number = msg.get("from")
                    if msg.get("type") == "text":
                        text_body = msg.get("text", {}).get("body", "")
                        print(f"\n📩 [WHATSAPP de {from_number}]: {text_body}")

                        reply = ask_don_tito(text_body)
                        print(f"🤖 [DON TITO]: {reply}\n")

                        send_whatsapp_message(from_number, reply)
                        return {"status": "success"}

        return {"status": "ignored"}
    except Exception as e:
        print(f"❌ Error en webhook: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agent_whatsapp:app", host="0.0.0.0", port=8001, reload=True)