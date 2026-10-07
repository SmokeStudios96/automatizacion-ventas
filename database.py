import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from supabase import create_client, Client

# ------------------------------------------------------------------------------
# 1. Base de Datos PostgreSQL Principal (Render)
# ------------------------------------------------------------------------------
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://admin_ventas:DBPruvLsZoyEXZo4Cu9my8LlNoXTn5h6@dpg-dasmt7m0tbcc7384ivvg-a.virginia-postgres.render.com/ventas_db_48lr"
)

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class NegocioConfig(Base):
    __tablename__ = "negocios"
    id = Column(Integer, primary_key=True, index=True)
    nombre_negocio = Column(String(100), nullable=False, default="Smoke Studios")
    usuario = Column(String(50), unique=True, index=True, nullable=True)
    password = Column(String(100), nullable=True)
    persona_ia = Column(String(100), nullable=False, default="Ejecutivo Comercial Virtual")
    reglas_atencion = Column(Text, nullable=True)
    telefono_contacto = Column(String(20), nullable=True, default="+56939270181")
    productos = relationship("Producto", back_populates="negocio")


class Producto(Base):
    __tablename__ = "productos"
    id = Column(Integer, primary_key=True, index=True)
    negocio_id = Column(Integer, ForeignKey("negocios.id"))
    sku = Column(String(50), unique=True, index=True)
    nombre = Column(String(150), nullable=False)
    categoria = Column(String(100), nullable=True)
    precio = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    negocio = relationship("NegocioConfig", back_populates="productos")


class HistorialMensaje(Base):
    __tablename__ = "historial_mensajes"
    id = Column(Integer, primary_key=True, index=True)
    cliente_telefono = Column(String(30), index=True)
    remitente = Column(String(20))  # 'cliente' o 'bot'
    mensaje = Column(Text, nullable=False)
    fecha = Column(DateTime, default=datetime.utcnow)


# ------------------------------------------------------------------------------
# 2. Conexión y Sincronización Directa con Supabase ('whatsapp_chats')
# ------------------------------------------------------------------------------
SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    or os.environ.get("SUPABASE_ANON_KEY", "")
)

supabase_client: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"⚠️ Error inicializando Supabase Client en database.py: {e}")


def sincronizar_chat_supabase(telefono: str, cliente_nombre: str, ultimo_mensaje: str, requiere_humano: bool):
    """
    Sincroniza el chat entrante con la tabla whatsapp_chats de Supabase
    para que se actualice de inmediato en el Dashboard de Next.js (Smoke Studios).
    """
    if not supabase_client:
        return

    estado = "humano_activo" if requiere_humano else "bot_activo"

    try:
        # Buscar si ya existe el chat
        res = (
            supabase_client.table("whatsapp_chats")
            .select("id")
            .eq("telefono", telefono)
            .limit(1)
            .execute()
        )

        datos = {
            "cliente_nombre": cliente_nombre,
            "ultimo_mensaje": ultimo_mensaje,
            "requiere_humano": requiere_humano,
            "estado": estado,
        }

        if res.data and len(res.data) > 0:
            chat_id = res.data[0]["id"]
            supabase_client.table("whatsapp_chats").update(datos).eq("id", chat_id).execute()
        else:
            supabase_client.table("whatsapp_chats").insert({
                "telefono": telefono,
                **datos
            }).execute()

    except Exception as e:
        print(f"⚠️ Error sincronizando con tabla 'whatsapp_chats' en Supabase: {e}")


def init_db():
    """Inicializa y asegura las tablas de PostgreSQL."""
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        conn.execute(text('ALTER TABLE negocios ADD COLUMN IF NOT EXISTS usuario VARCHAR(50);'))
        conn.execute(text('ALTER TABLE negocios ADD COLUMN IF NOT EXISTS password VARCHAR(100);'))
        conn.commit()
    print("✅ Tablas PostgreSQL verificadas.")


if __name__ == "__main__":
    init_db()