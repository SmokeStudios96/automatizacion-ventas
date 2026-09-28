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

# ------------------------------------------------------------------------------
# 1. Configuración de Credenciales, Supabase y Carga de Catálogo
# ------------------------------------------------------------------------------
os.environ["GEMINI_API_KEY"] = "AQ.Ab8RN6Kgnd0mzuoF1_SSh735CY_Q8_e00DY_RJJYOxz1VmFx3w"

# Supabase Credentials (extraídas de las variables de entorno o configuración)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://hbkwldkkfzlunptemxtw.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "tu-supabase-anon-key-aqui")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Parámetros de Meta WhatsApp Cloud API
META_ACCESS_TOKEN = "EAAeol1PvNZAIBSiydWCrGsx32nTdbRd8OQqRFtgZA1ba1h8AZAyS1IqV5uzWk6XjMlWB5QhnU8lm3FCWCHFrJgXE0QoIZCsImu4RWLyVoj7ZB4E3iJ9cSAZAQAg3UgHmelML6EJehlM7f3IHYHZBiNLvbscrFWslZBczFXAtvL6U9xaBZCZBpyLaZCSeLTr7TqnZC4e5AA6COfi7GgJPsOJHfM17dY17SLYqOCMy8a4YH36bZBz8Qv6IEnZBcTrGAuAmuRarwZAMLH2Fwh2TFaLyiScQTtDTgZDZD"
PHONE_NUMBER_ID = "1293789687158465"
VERIFY_TOKEN = "don_tito_ferreteria_secret_token"

with open("catalog.json", "r", encoding="utf-8") as f:
    catalog_data = json.load(f)

catalog_text = "\n".join([
    f"- {p['nombre']} (SKU: {p['sku']}): ${p['precio']:,} CLP | Stock: {p['stock']} un | Categoría: {p['categoria']}"
    for p in catalog_data
])

def obtener_contexto_horario():
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
# 2. Inicialización del Agente Agno
# ------------------------------------------------------------------------------
don_tito_agent = Agent(
    model=Gemini(id="gemini-3.6-flash"),
    description="Eres Don Tito, un ferretero experto, amable y directo de Chiloé.",
    instructions=[
        "Eres claro, preciso y directo al responder sobre productos, precios y stock.",
        "No hagas ofertas excesivas ni intentes vender de forma pesada; entrega el dato exacto.",
        "Si un producto no está disponible o no existe en el catálogo, sugiere solo una alternativa muy cercana y puntual.",
        "Si el cliente pide compras al por mayor, descuentos por volumen, productos fuera de catálogo o solicita hablar con un humano, activa de inmediato el Criterio A y deriva al +56939270181.",
        "REGLA DE HORARIO: Revisa siempre el contexto de fecha/hora entregado. Si el estado es CERRADO, saluda, responde la duda sobre el catálogo, pero advierte amablemente al cliente que el local se encuentra cerrado en este momento y que su mensaje quedará registrado para revisión prioritaria al abrir.",
        f"Catálogo de productos disponibles en tienda:\n{catalog_text}"
    ],
    markdown=True,
)

# ------------------------------------------------------------------------------
# 3. Inicialización de la Aplicación FastAPI
# ------------------------------------------------------------------------------
app = FastAPI(
    title="API Agente Ferretería Don Tito",
    description="Backend FastAPI con soporte de Webhooks para WhatsApp, BSale y Agno",
    version="1.0.0"
)

class ChatRequest(BaseModel):
    message: str
    phone_number: str | None = None

class ChatResponse(BaseModel):
    response: str
    status: str = "success"

# ------------------------------------------------------------------------------
# 4. Endpoints de la API
# ------------------------------------------------------------------------------
@app.get("/health")
def health_check():
    return {"status": "ok", "service": "Don Tito Sales Agent API"}

@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")
    
    try:
        contexto = obtener_contexto_horario()
        prompt_completo = f"[{contexto}] Mensaje del cliente: {request.message}"
        agent_response = don_tito_agent.run(prompt_completo)
        
        return ChatResponse(response=agent_response.content, status="success")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando la consulta: {str(e)}")

@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(content=challenge, status_code=200)
    else:
        raise HTTPException(status_code=403, detail="Error de verificación de token")

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
                    text_body = msg.get("text", {}).get("body", "")

                    if text_body:
                        contexto = obtener_contexto_horario()
                        prompt_completo = f"[{contexto}] Mensaje del cliente: {text_body}"
                        agent_response = don_tito_agent.run(prompt_completo)

                        # Enviar respuesta a WhatsApp mediante Meta Graph API
                        url = f"https://graph.facebook.com/v26.0/{PHONE_NUMBER_ID}/messages"
                        headers = {
                            "Authorization": f"Bearer {META_ACCESS_TOKEN}",
                            "Content-Type": "application/json"
                        }
                        payload = {
                            "messaging_product": "whatsapp",
                            "to": from_number,
                            "type": "text",
                            "text": {"body": agent_response.content}
                        }
                        requests.post(url, json=payload, headers=headers)

                        print(f"\n[WHATSAPP RECIBIDO de {from_number}]: {text_body}")
                        print(f"[RESPUESTA ENVIADA]: {agent_response.content}\n")

                        return {
                            "status": "success",
                            "recipient": from_number,
                            "response": agent_response.content
                        }

        # Fallback para pruebas con payload simple de mensaje plano
        user_msg = body.get("message") or body.get("text")
        if user_msg:
            contexto = obtener_contexto_horario()
            prompt_completo = f"[{contexto}] Mensaje del cliente: {user_msg}"
            agent_response = don_tito_agent.run(prompt_completo)
            return {"status": "success", "response": agent_response.content}

        return {"status": "ignored", "reason": "No text message payload found"}
    except Exception as e:
        print(f"Error procesando Webhook de WhatsApp: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/webhooks/bsale")
async def bsale_webhook_handler(request: Request):
    """
    Endpoint para recibir cambios de stock o precio desde BSale en tiempo real.
    """
    try:
        data = await request.json()
        
        # Obtener datos relevantes del evento de BSale
        variant_id = data.get("variantId") or data.get("id")
        sku = data.get("code")
        new_stock = data.get("quantity")
        new_price = data.get("price")

        if not sku and not variant_id:
            return {"status": "ignored", "reason": "No SKU or Variant ID provided"}

        # Mapear datos a actualizar
        update_fields = {}
        if new_stock is not None:
            update_fields["stock"] = int(new_stock)
        if new_price is not None:
            update_fields["precio"] = int(new_price)

        if not update_fields:
            return {"status": "ignored", "reason": "No stock or price changes"}

        # Actualizar en Supabase
        if sku:
            supabase.table("productos").update(update_fields).eq("sku", sku).execute()
        else:
            supabase.table("productos").update(update_fields).eq("bsale_variant_id", variant_id).execute()

        return {"status": "success", "updated_fields": update_fields}

    except Exception as e:
        print(f"Error procesando Webhook de BSale: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Error procesando webhook de BSale: {str(e)}"
        )

# ------------------------------------------------------------------------------
# 5. Simulador Interactivo en Consola
# ------------------------------------------------------------------------------
def iniciar_simulador_cli():
    print("\n=======================================================")
    print("   SIMULADOR DE CHAT - FERRETERÍA DON TITO (CONSOLA)")
    print("   Escribe 'salir' para cerrar el simulador.")
    print("=======================================================\n")
    
    contexto_inicial = obtener_contexto_horario()
    print(f"--> [Sistema]: {contexto_inicial}\n")
    
    while True:
        try:
            mensaje_usuario = input("Cliente: ")
            if mensaje_usuario.strip().lower() in ["salir", "exit", "quit"]:
                print("\nDon Tito: ¡Que le vaya muy bien, vuelva pronto!\n")
                break
                
            if not mensaje_usuario.strip():
                continue

            contexto = obtener_contexto_horario()
            prompt = f"[{contexto}] Mensaje del cliente: {mensaje_usuario}"
            
            print("\nDon Tito: ", end="")
            don_tito_agent.print_response(prompt)
            print("-" * 50)
            
        except KeyboardInterrupt:
            print("\nSimulador finalizado.")
            break

# ------------------------------------------------------------------------------
# 6. Punto de Entrada Principal
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        iniciar_simulador_cli()
    else:
        import uvicorn
        uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)