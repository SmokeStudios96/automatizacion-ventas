import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()
database_url = os.getenv("DATABASE_URL")

try:
    conn = psycopg2.connect(database_url)
    print("¡Conexión exitosa a Supabase!")
    conn.close()
except Exception as e:
    print(f"Error de conexión: {e}")