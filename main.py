import json
import os
from datetime import datetime, timezone, timedelta
from agno.agent import Agent
from agno.models.google import Gemini

# Configuración API Key
os.environ["GEMINI_API_KEY"] = "AQ.Ab8RN6Kgnd0mzuoF1_SSh735CY_Q8_e00DY_RJJYOxz1VmFx3w"

# Cargar catálogo de productos desde JSON
with open("catalog.json", "r", encoding="utf-8") as f:
    catalog_data = json.load(f)

catalog_text = "\n".join([
    f"- {p['nombre']} (SKU: {p['sku']}): ${p['precio']:,} CLP | Stock: {p['stock']} un | Categoría: {p['categoria']}"
    for p in catalog_data
])

def obtener_contexto_horario():
    # UTC-3 para Chile Continental (horario oficial de verano)
    tz_chile = timezone(timedelta(hours=-3))
    ahora = datetime.now(tz_chile)
    
    dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_str = dias_semana[ahora.weekday()]
    hora_str = ahora.strftime("%H:%M")
    
    # Evaluar si está dentro de horario (L-S 09:00-13:00 y 14:30-18:30)
    es_domingo = ahora.weekday() == 6
    hora_decimal = ahora.hour + ahora.minute / 60.0
    
    en_turno_manana = 9.0 <= hora_decimal < 13.0
    en_turno_tarde = 14.5 <= hora_decimal < 18.5
    
    esta_abierto = (not es_domingo) and (en_turno_manana or en_turno_tarde)
    
    estado = "ABIERTO (atención presencial)" if esta_abierto else "CERRADO (fuera de horario de atención)"
    
    return f"Momento actual: {dia_str} a las {hora_str} hrs. Estado del local: {estado}."

# Inicializar Agente
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

if __name__ == "__main__":
    contexto = obtener_contexto_horario()
    print(f"--- Contexto inyectado: {contexto} ---\n")
    
    prompt_prueba = f"[{contexto}] Hola Don Tito, ¿tienen taladro percutor disponible y a qué hora cierran hoy?"
    don_tito_agent.print_response(prompt_prueba)