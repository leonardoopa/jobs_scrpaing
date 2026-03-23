import os
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "adminpassword")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "jobscrap_db")

SQLALCHEMY_DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class Vaga(Base):
    __tablename__ = "vagas"

    id = Column(Integer, primary_key=True, index=True)
    id_vaga_hash = Column(String, unique=True, index=True, nullable=False)
    plataforma = Column(String, index=True)  # Ex: InfoJobs, LinkedIn
    cargo_buscado = Column(String, index=True)  # Ex: Desenvolvedor Backend
    titulo = Column(String, nullable=False)  # Título real da vaga
    empresa = Column(String)
    localizacao = Column(String)
    modalidade = Column(String)  # Remoto, Presencial
    regime = Column(String)  # CLT, PJ
    salario = Column(String)
    descricao = Column(
        Text
    )  # Text é usado para strings gigantes (como a descrição da vaga)
    link = Column(String)
    data_extracao = Column(DateTime, default=datetime.utcnow)


def init_db():
    """Função que cria as tabelas no banco de dados se elas não existirem."""
    print("Criando tabelas no PostgreSQL...")
    Base.metadata.create_all(bind=engine)
    print("Banco de dados sincronizado com sucesso!")


def get_db():
    """Gera uma sessão segura para a API usar e fecha logo depois."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
