import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

# Catálogo genérico de Minimarket
minimarket_data = [
    {
        "nombre": "Coca-Cola Original 1.5L",
        "descripcion": "Bebida fantasía desechable 1.5 Litros.",
        "precio": 1800,
        "stock": 24
    },
    {
        "nombre": "Papas Fritas Lays Corte Americano 220g",
        "descripcion": "Papas fritas saladas formato familiar.",
        "precio": 2200,
        "stock": 15
    },
    {
        "nombre": "Galletas Tritón Chocolate 126g",
        "descripcion": "Galletas de chocolate con relleno crema vainilla.",
        "precio": 950,
        "stock": 40
    },
    {
        "nombre": "Agua Mineral Cachantun Sin Gas 1.5L",
        "descripcion": "Agua mineral purificada embotellada 1.5L.",
        "precio": 1100,
        "stock": 30
    },
    {
        "nombre": "Chocolate Trencito 150g",
        "descripcion": "Barra de chocolate de leche clásico.",
        "precio": 2500,
        "stock": 18
    },
    {
        "nombre": "Bebida Red Bull Tropical 250ml",
        "descripcion": "Lata de bebida energética sabor frutas tropicales.",
        "precio": 2100,
        "stock": 20
    },
    {
        "nombre": "Café Nescafé Fina Selección 100g",
        "descripcion": "Frasco de café instantáneo liofilizado.",
        "precio": 4800,
        "stock": 12
    }
]

def seed_database():
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            print("Limpiando catálogo anterior...")
            # Limpiamos la tabla para que no queden taladros ni productos antiguos
            conn.execute(text("TRUNCATE TABLE productos CASCADE;"))

            print("Insertando productos de Minimarket...")
            for item in minimarket_data:
                conn.execute(
                    text("""
                        INSERT INTO productos (nombre, descripcion, precio, stock)
                        VALUES (:nombre, :descripcion, :precio, :stock)
                    """),
                    item
                )
            trans.commit()
            print("¡Catálogo de Minimarket cargado con éxito en Supabase!")
        except Exception as e:
            trans.rollback()
            print(f"Error al actualizar la base de datos: {e}")

if __name__ == "__main__":
    seed_database()