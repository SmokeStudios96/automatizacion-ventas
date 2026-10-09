import os
import json
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

def seed_database():
    # Cargar productos desde catalog.json si existe
    if os.path.exists("catalog.json"):
        with open("catalog.json", "r", encoding="utf-8") as f:
            catalog_data = json.load(f)
    else:
        print("❌ No se encontró catalog.json")
        return

    with engine.begin() as connection:
        # 1. Crear las tablas básicas si no existen
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS negocios (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(255) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS productos (
                id SERIAL PRIMARY KEY,
                negocio_id INT,
                sku VARCHAR(100),
                nombre VARCHAR(255) NOT NULL,
                precio INT NOT NULL,
                stock INT NOT NULL,
                categoria VARCHAR(100),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """))

        # 2. Asegurar que exista el negocio
        connection.execute(text("""
            INSERT INTO negocios (id, nombre) 
            VALUES (1, 'Ferretería Don Tito')
            ON CONFLICT (id) DO NOTHING;
        """))

        # 3. Limpiar productos anteriores
        connection.execute(text("TRUNCATE TABLE productos RESTART IDENTITY CASCADE;"))

        # 4. Insertar catálogo de la Ferretería
        for prod in catalog_data:
            connection.execute(text("""
                INSERT INTO productos (negocio_id, sku, nombre, precio, stock, categoria)
                VALUES (1, :sku, :nombre, :precio, :stock, :categoria)
            """), {
                "sku": prod.get("sku"),
                "nombre": prod.get("nombre"),
                "precio": prod.get("precio"),
                "stock": prod.get("stock"),
                "categoria": prod.get("categoria")
            })

    print(f"✅ Base de datos sembrada con éxito con {len(catalog_data)} productos de Ferretería Don Tito.")

if __name__ == "__main__":
    seed_database()