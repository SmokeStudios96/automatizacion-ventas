import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from supabase import create_client, Client

# ------------------------------------------------------------------------------
# 1. Base de Datos PostgreSQL Principal (Render / Supabase Direct)
# ------------------------------------------------------------------------------
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://admin_ventas:DBPruvLsZoyEXZo4Cu9my8LlNoXTn5h6@dpg-dasmt7m0tbcc7384ivvg-a.virginia-postgres.render.com/ventas_db_48lr"
)

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Verifica la conexión activa antes de ejecutar la consulta
    pool_recycle=300
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class HistorialMensajeGeneral(Base):
    """Tabla unificada de historial para todas las verticales (Ferretería, Estética, Dental)."""
    __tablename__ = "historial_mensajes_general"
    
    id = Column(Integer, primary_key=True, index=True)
    agente = Column(String(30), index=True, default="estetica")  # 'estetica', 'dental', 'ferreteria'
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


def sincronizar_chat_supabase(telefono: str, cliente_nombre: str, ultimo_mensaje: str, requiere_humano: bool, agente: str = "estetica"):
    """
    Sincroniza el chat entrante con la tabla whatsapp_chats de Supabase.
    """
    if not supabase_client:
        return

    estado = "humano_activo" if requiere_humano else "bot_activo"

    try:
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
            "agente": agente
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
        print(f"⚠️ Aviso (no crítico): Error sincronizando con Supabase: {e}")


def guardar_historial_seguro(telefono: str, remitente: str, mensaje: str, agente: str = "estetica"):
    """Guarda el historial en la BD asegurando que un fallo de red no bote al bot."""
    try:
        db = SessionLocal()
        nuevo = HistorialMensajeGeneral(
            agente=agente,
            cliente_telefono=telefono,
            remitente=remitente,
            mensaje=mensaje
        )
        db.add(nuevo)
        db.commit()
        db.close()
    except Exception as e:
        print(f"⚠️ Aviso (no crítico): No se pudo guardar historial en BD: {e}")


def init_db():
    """Inicializa la base de datos."""
    try:
        Base.metadata.create_all(bind=engine)
        print("✅ Tablas PostgreSQL verificadas.")
    except Exception as e:
        print(f"⚠️ Error inicializando BD: {e}")


if __name__ == "__main__":
    init_db()