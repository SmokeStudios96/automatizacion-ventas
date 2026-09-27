import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

# URL de conexión externa optimizada para pruebas desde tu entorno local
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2://admin_ventas:DBPruvLsZoyEXZo4Cu9my8LlNoXTn5h6@dpg-dasmt7m0tbcc7384ivvg-a.virginia-postgres.render.com/ventas_db_48lr")

# Asegurar explícitamente el uso de psycopg2 para evitar errores en la nube
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
    nombre_negocio = Column(String(100), nullable=False)
    persona_ia = Column(String(100), nullable=False)
    reglas_atencion = Column(Text, nullable=True)
    telefono_contacto = Column(String(20), nullable=True)

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
    remitente = Column(String(20)) # 'cliente' o 'bot'
    mensaje = Column(Text, nullable=False)
    fecha = Column(DateTime, default=datetime.utcnow)

def init_db():
    """Crea las tablas en la base de datos si no existen."""
    Base.metadata.create_all(bind=engine)
    print("✅ Tablas genéricas verificadas/creadas en PostgreSQL.")

if __name__ == "__main__":
    init_db()