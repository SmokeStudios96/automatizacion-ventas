import os
import json
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://hbkwldkkfzlunptemxtw.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: SUPABASE_URL o SUPABASE_KEY no están definidas en el .env")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def seed_database():
    if not os.path.exists("catalog.json"):
        print("❌ No se encontró catalog.json")
        return

    with open("catalog.json", "r", encoding="utf-8") as f:
        catalog_data = json.load(f)

    print("🔌 Conectando a Supabase...")
    
    # 1. Limpiar productos anteriores
    print("🧹 Limpiando productos anteriores en la tabla 'productos'...")
    supabase.table("productos").delete().neq("id", 0).execute()
    print("   ↳ Tabla limpiada exitosamente.")

    # 2. Sanitizar datos según esquema de la tabla (omitir 'categoria' si da conflicto o adaptarla)
    # Mapeamos los productos asegurando las columnas clave
    productos_a_insertar = []
    for item in catalog_data:
        prod = {
            "nombre": item.get("nombre"),
            "descripcion": item.get("descripcion", ""),
            "precio": item.get("precio"),
            "stock": item.get("stock", 0)
        }
        # Incluir sku/categoria si existen en tu JSON
        if "sku" in item:
            prod["sku"] = item["sku"]
        if "categoria" in item:
            prod["categoria"] = item["categoria"]
            
        productos_a_insertar.append(prod)

    print(f"\n📦 Enviando {len(productos_a_insertar)} productos a Supabase...")
    for index, prod in enumerate(productos_a_insertar, 1):
        print(f"   [{index}/{len(productos_a_insertar)}] Insertando: {prod['nombre']} - ${prod['precio']:,} CLP")

    # 3. Inserción masiva en la base de datos
    res = supabase.table("productos").insert(productos_a_insertar).execute()
    
    print("\n" + "="*50)
    print(f"✅ ¡ÉXITO TOTAL! Base de datos sembrada correctamente.")
    print(f"   Total de registros insertados: {len(res.data)}")
    print("="*50)

if __name__ == "__main__":
    seed_database()