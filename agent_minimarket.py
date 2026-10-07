import os
import psycopg2
from dotenv import load_dotenv
from google import genai

# Cargar variables de entorno desde el .env
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

if not API_KEY or not DATABASE_URL:
    raise ValueError("Error: Asegúrate de tener GEMINI_API_KEY y DATABASE_URL configuradas en tu archivo .env")

# Corregir la URL por si mantiene el prefijo de SQLAlchemy
if DATABASE_URL.startswith("postgresql+psycopg2://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")

# 1. Función (Tool) para consultar el inventario en Supabase
def consultar_inventario(busqueda: str) -> str:
    """
    Busca productos en la tabla 'productos' del minimarket por nombre.
    Retorna el nombre, precio y stock.
    """
    print(f"\n🔍 [EJECUTANDO TOOL]: Buscando en Supabase -> '{busqueda}'...")
    try:
        conn = psycopg2.connect(dsn=DATABASE_URL)
        cursor = conn.cursor()
        
        # Consultamos las columnas estándar que existen en la tabla
        query = """
            SELECT nombre, precio, stock 
            FROM productos 
            WHERE nombre ILIKE %s;
        """
        param = f"%{busqueda}%"
        cursor.execute(query, (param,))
        resultados = cursor.fetchall()
        
        cursor.close()
        conn.close()

        if not resultados:
            msg = f"No se encontraron productos relacionados con '{busqueda}'."
            print(f"📌 [RESULTADO TOOL]: {msg}")
            return msg

        respuesta = f"Productos encontrados para '{busqueda}':\n"
        for prod in resultados:
            nombre, precio, stock = prod
            respuesta += f"- {nombre} (${precio:,.0f}) | Stock: {stock} unidades\n"
        
        print(f"📌 [RESULTADO TOOL]:\n{respuesta}")
        return respuesta

    except Exception as e:
        error_msg = f"Error al consultar la base de datos: {e}"
        print(f"❌ [ERROR DB]: {error_msg}")
        return error_msg


# 2. Inicializar cliente oficial de Gemini
client = genai.Client(api_key=API_KEY)

sys_instruction = (
    "Eres el asistente virtual interactivo del minimarket de Smoke Studios. "
    "Tu objetivo es responder las consultas de los clientes sobre el stock y precios de productos. "
    "Usa SIEMPRE la herramienta 'consultar_inventario' para revisar la base de datos antes de responder."
)

chat = client.chats.create(
    model="gemini-3.6-flash",
    config={
        "system_instruction": sys_instruction,
        "tools": [consultar_inventario]
    }
)

pregunta_usuario = "¿Tienes Coca-Cola disponible y a qué precio está? ¿O qué snacks me recomiendas?"

print(f"📌 Pregunta del usuario: {pregunta_usuario}\n")

try:
    response = chat.send_message(pregunta_usuario)
    print("\n🤖 Respuesta final del Agente:")
    print(response.text)

except Exception as e:
    print("❌ Error al ejecutar el agente:", e)