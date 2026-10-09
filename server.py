from dotenv import load_dotenv

# 1. Cargar las variables de entorno desde el archivo .env
load_dotenv()

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
import requests
from supabase import create_client, Client
from agno.agent import Agent
from agno.models.google import Gemini

# Importar las herramientas del carrito y base de datos
from cart_tool import agregar_al_carrito, ver_carrito, procesar_cierre_pedido

# ==============================================================================
# 1. Configuración de Credenciales y Supabase
# ==============================================================================

API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_APT_KEY") or ""
os.environ["GOOGLE_API_KEY"] = API_KEY_GEMINI
os.environ["GEMINI_API_KEY"] = API_KEY_GEMINI

WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID") or os.environ.get("PHONE_NUMBER_ID", "1293789687158465")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "don_tito_ferreteria_token_secret")

SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://hbkwldkkfzlunptemxtw.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or "sb_publishable_31oqg5WiRUqi4kZ9_BxKxw_OKJAi_XF"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Cargar catálogo local
try:
    with open("catalog.json", "r", encoding="utf-8") as f:
        catalog_data = json.load(f)

    catalog_text = "\n".join([
        f"- {p['nombre']} (SKU: {p['sku']}): ${p['precio']:,} CLP | Stock: {p['stock']} un | Categoría: {p['categoria']}"
        for p in catalog_data
    ])
except Exception:
    catalog_text = "Catálogo local no disponible temporalmente."


def obtener_contexto_horario():
    utc_now = datetime.now(timezone.utc)
    chile_tz = timezone(timedelta(hours=-3))
    ahora = utc_now.astimezone(chile_tz)

    dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_str = dias_semana[ahora.weekday()]
    hora_str = ahora.strftime("%H:%M")

    es_domingo = ahora.weekday() == 6
    hora_decimal = ahora.hour + ahora.minute / 60.0

    en_turno_manana = 8.5 <= hora_decimal < 13.0
    en_turno_tarde = 14.5 <= hora_decimal < 18.5

    esta_abierto = (not es_domingo) and (en_turno_manana or en_turno_tarde)
    estado = "ABIERTO (atención presencial)" if esta_abierto else "CERRADO (fuera de horario de atención)"

    return f"Momento actual: {dia_str} a las {hora_str} hrs. Estado del local: {estado}."

# ==============================================================================
# 2. Inicialización del Agente Agno (Don Tito)
# ==============================================================================

don_tito_agent = Agent(
    model=Gemini(
        id="gemini-3.8-flash",
        api_key=API_KEY_GEMINI
    ),
    description="Eres Don Tito, un ferretero experto, amable y directo de Chiloé.",
    instructions=[
        "Eres claro, preciso y directo al responder sobre productos, precios y stock.",
        "No hagas ofertas excesivas ni intentes vender de forma pesada; entrega el dato exacto.",
        "Si un producto no está disponible o no existe en el catálogo, sugiere solo una alternativa muy cercana y puntual.",
        "Si el cliente pide compras al por mayor, descuentos por volumen, productos fuera de catálogo o solicita hablar con un humano, deriva al +56939270181.",
        "REGLA DE HORARIO: Revisa siempre el contexto de fecha/hora entregado. Si el estado es CERRADO, saluda, responde la duda sobre el catálogo, pero advierte amablemente al cliente que el local se encuentra cerrado en este momento.",
        "GESTIÓN DE CARRITO Y COMPRAS:",
        "- Cuando el cliente quiera agregar un producto, utiliza la función 'agregar_al_carrito'.",
        "- Si el cliente pregunta qué tiene en su carrito o quiere ver el total, utiliza 'ver_carrito'.",
        "- Cuando el cliente confirme que desea finalizar/cerrar el pedido o realizar la compra, invoca 'procesar_cierre_pedido'.",
        f"Catálogo de productos disponibles en tienda:\n{catalog_text}"
    ],
    tools=[agregar_al_carrito, ver_carrito, procesar_cierre_pedido],
    markdown=False,
)


def enviar_mensaje_whatsapp(telefono: str, texto: str):
    """Envía un mensaje de texto de regreso al usuario a través de la API oficial de WhatsApp."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        print("⚠️ WHATSAPP_TOKEN o WHATSAPP_PHONE_ID no configurados en .env")
        return

    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "text",
        "text": {"body": texto}
    }

    try:
        res = requests.post(url, json=payload, headers=headers)
        print(f"Status envío WhatsApp: {res.status_code}")
    except Exception as e:
        print(f"Error enviando mensaje a WhatsApp: {e}")

# ==============================================================================
# 3. Servidor FastAPI y Webhook Meta
# ==============================================================================

app = FastAPI(title="Bot Ferretería Agno - Don Tito")


@app.get("/webhook")
async def verificar_webhook(request: Request):
    """Endpoint de verificación para Meta Developers."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("✅ Webhook verificado correctamente con Meta.")
            return Response(content=challenge, status_code=200)
        else:
            raise HTTPException(status_code=403, detail="Token de verificación inválido")
    return Response(content="Webhook de Ferretería Don Tito Activo", status_code=200)


@app.post("/webhook")
async def recibir_mensaje_webhook(request: Request):
    """Endpoint donde Meta envía las notificaciones de mensajes de WhatsApp."""
    try:
        body = await request.json()

        # Extraer el mensaje entrante desde la estructura de Meta
        entry = body.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if messages:
            msg = messages[0]
            raw_phone = msg.get("from", "")
            # Limpiar signo + si viene incluido para coincidir con la DB
            phone_number = raw_phone.replace("+", "").strip()
            text_body = msg.get("text", {}).get("body", "")

            if text_body:
                print(f"\n📩 Mensaje recibido de {phone_number}: {text_body}")

                contexto_horario = obtener_contexto_horario()
                prompt_completo = f"[{contexto_horario}]\n[Cliente Teléfono: {phone_number}]\nMensaje del cliente: {text_body}"

                # Ejecutar Don Tito Agno Agent con herramientas
                response = don_tito_agent.run(prompt_completo)
                respuesta_texto = response.content

                print(f"🤖 Respuesta de Don Tito: {respuesta_texto}\n")

                # Enviar respuesta al número de WhatsApp
                enviar_mensaje_whatsapp(phone_number, respuesta_texto)

        return {"status": "success"}
    except Exception as e:
        print(f"⚠️ Error procesando mensaje del Webhook: {e}")
        return {"status": "error", "message": str(e)}


class ChatRequest(BaseModel):
    phone_number: str = "56912345678"
    message: str


@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        contexto_horario = obtener_contexto_horario()
        clean_phone = request.phone_number.replace("+", "").strip()
        prompt_completo = f"[{contexto_horario}]\n[Cliente Teléfono: {clean_phone}]\nMensaje del cliente: {request.message}"

        response = don_tito_agent.run(prompt_completo)
        return {"response": response.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==============================================================================
# 4. Simulador CLI y Entrada
# ==============================================================================

def iniciar_simulador_cli():
    print("=" * 50)
    print("  SIMULADOR CLI - DON TITO (AGNO AGENT)")
    print("=" * 50)
    print("Escribe 'salir' para terminar el simulador.\n")

    phone_test = "56912345678"

    while True:
        try:
            user_input = input("Cliente: ")
            if user_input.strip().lower() in ["salir", "exit"]:
                print("Simulador finalizado.")
                break

            if not user_input.strip():
                continue

            contexto_horario = obtener_contexto_horario()
            prompt_completo = f"[{contexto_horario}]\n[Cliente Teléfono: {phone_test}]\nMensaje del cliente: {user_input}"

            response = don_tito_agent.run(prompt_completo)
            print(f"\nDon Tito: {response.content}\n")
            print("-" * 50)

        except KeyboardInterrupt:
            print("\nSimulador finalizado.")
            break
        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        iniciar_simulador_cli()
    else:
        import uvicorn
        uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)