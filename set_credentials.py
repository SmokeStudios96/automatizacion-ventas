from database import SessionLocal, NegocioConfig, init_db

# Primero aseguramos que las tablas y columnas existan en la nube
init_db()

db = SessionLocal()

# Buscamos tu negocio actual (por ejemplo, Ferretería Don Tito)
negocio = db.query(NegocioConfig).first()

if negocio:
    # Le asignamos usuario y contraseña
    negocio.usuario = "tito"
    negocio.password = "1234"
    
    db.commit()
    print(f"✅ ¡Credenciales asignadas al negocio '{negocio.nombre_negocio}'!")
    print(f"   Usuario: tito")
    print(f"   Contraseña: 1234")
else:
    print("❌ No se encontró ningún negocio en la base de datos.")

db.close()