import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("Error: No se encontró GEMINI_API_KEY en el archivo .env")

client = genai.Client(api_key=api_key)

try:
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents="Responde solamente: Hola, conexión exitosa."
    )
    print("STATUS: 200 SUCCESS")
    print("RESPONSE:")
    print(response.text)
except Exception as e:
    print("ERROR AL CONECTAR:")
    print(e)