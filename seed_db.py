from database import SessionLocal, init_db, NegocioConfig, Producto

def poblar_datos_iniciales():
    init_db()
    db = SessionLocal()
    
    # Verificamos si ya existe un negocio configurado
    negocio_existente = db.query(NegocioConfig).first()
    if negocio_existente:
        print("ℹ️ La base de datos ya contiene un negocio registrado.")
        db.close()
        return

    # Creamos un negocio genérico inicial
    nuevo_negocio = NegocioConfig(
        nombre_negocio="Ferretería Don Tito",
        persona_ia="Don Tito",
        reglas_atencion="1. Eres claro, preciso y directo. 2. No hagas ofertas excesivas. 3. Si un producto no está disponible, sugiere una alternativa muy cercana. 4. Deriva al +56939270181 para ventas al por mayor o humano.",
        telefono_contacto="+56939270181"
    )
    db.add(nuevo_negocio)
    db.commit()
    db.refresh(nuevo_negocio)

    # Catálogo inicial de prueba
    productos_iniciales = [
        Producto(negocio_id=nuevo_negocio.id, sku="ADH-019", nombre="Bekron Estándar Sacos 25kg", categoria="Adhesivos", precio=6490, stock=95),
        Producto(negocio_id=nuevo_negocio.id, sku="HER-102", nombre="Martillo Galponero 16oz Mango Fibra", categoria="Herramientas", precio=8990, stock=18),
        Producto(negocio_id=nuevo_negocio.id, sku="HER-105", nombre="Taladro Percutor 650W", categoria="Herramientas", precio=29990, stock=12)
    ]

    db.add_all(productos_iniciales)
    db.commit()
    db.close()
    print("✅ ¡Datos iniciales cargados con éxito en PostgreSQL!")

if __name__ == "__main__":
    poblar_datos_iniciales()