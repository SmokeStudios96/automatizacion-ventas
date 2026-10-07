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

# Importar las herramientas del carrito
from cart_tool import agregar_al_carrito, ver_carrito, procesar_cierre_pedido

# ==============================================================================
# 1. Configuración de Credenciales, Supabase y Carga de Catálogo
# ==============================================================================

# Asignar ambas variables de entorno para compatibilidad total con Agno
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_APT_KEY") or ""
os.environ["GOOGLE_API_KEY"] = API_KEY_GEMINI
os.environ["GEMINI_API_KEY"] = API_KEY_GEMINI

# Supabase Credentials (las lee del .env o usa el fallback)
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

# Helper para calcular el estado del local según horario de Chiloé (UTC-3)
def obtener_contexto_horario():
    utc_now = datetime.now(timezone.utc)
    chile_tz = timezone(timedelta(hours=-3))
    ahora = utc_now.astimezone(chile_tz)

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

# ==============================================================================
# 2. Inicialización del Agente Agno (Don Tito)
# ==============================================================================

don_tito_agent = Agent(
    model=Gemini(
        id="gemini-3.6-flash",
        api_key=API_KEY_GEMINI
    ),
    description="Eres Don Tito, un ferretero experto, amable y directo de Chiloé.",
    instructions=[
        "Eres claro, preciso y directo al responder sobre productos, precios y stock.",
        "No hagas ofertas excesivas ni intentes vender de forma pesada; entrega el dato exacto.",
        "Si un producto no está disponible o no existe en el catálogo, sugiere solo una alternativa muy cercana y puntual.",
        "Si el cliente pide compras al por mayor, descuentos por volumen, productos fuera de catálogo o solicita hablar con un humano, activa de inmediato el Criterio A y deriva al +56939270181.",
        "REGLA DE HORARIO: Revisa siempre el contexto de fecha/hora entregado. Si el estado es CERRADO, saluda, responde la duda sobre el catálogo, pero advierte amablemente al cliente que el local se encuentra cerrado en este momento y que su mensaje quedará registrado para revisión prioritaria al abrir.",
        "GESTIÓN DE CARRITO Y COMPRAS:",
        "- Cuando el cliente quiera agregar un producto, utiliza la función 'agregar_al_carrito'.",
        "- Si el cliente pregunta qué tiene en su carrito o quiere ver el total, utiliza 'ver_carrito'.",
        "- Cuando el cliente confirme que desea finalizar/cerrar el pedido o realizar la compra, invoca 'procesar_cierre_pedido'.",
        f"Catálogo de productos disponibles en tienda:\n{catalog_text}"
    ],
    tools=[agregar_al_carrito, ver_carrito, procesar_cierre_pedido],
    markdown=True,
)

# ==============================================================================
# 3. Servidor FastAPI
# ==============================================================================

app = FastAPI(title="Bot Ferretería Agno - Don Tito")

class ChatRequest(BaseModel):
    phone_number: str = "+56912345678"
    message: str

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        contexto_horario = obtener_contexto_horario()
        prompt_completo = f"[{contexto_horario}]\n[Cliente Teléfono: {request.phone_number}]\nMensaje del cliente: {request.message}"
        
        response = don_tito_agent.run(prompt_completo)
        return {"response": response.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==============================================================================
# 4. Simulador CLI para Pruebas Interactivas
# ==============================================================================

def iniciar_simulador_cli():
    print("=" * 50)
    print("  SIMULADOR CLI - DON TITO (AGNO AGENT)")
    print("=" * 50)
    print("Escribe 'salir' para terminar el simulador.\n")
    
    phone_test = "+56912345678"
    
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

# ==============================================================================
# 5. Punto de Entrada Principal
# ==============================================================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        iniciar_simulador_cli()
    else:
        import uvicorn
        uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)