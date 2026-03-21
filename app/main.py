from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import redis
import json
import os
from fastapi.responses import JSONResponse, ORJSONResponse



from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

DEBUG = os.getenv("DEBUG", "false").lower() == "true"

app = FastAPI(docs_url="/docs" if DEBUG else None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Em produção, trocaremos para o domínio real do seu site
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def conectar_banco():
    """Conecta ao Redis para buscar as vagas armazenadas pelos Workers."""
    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", 6379))
    try:
        redis_client = redis.Redis(host=host, port=port, db=0, decode_responses=True, socket_timeout=2)
        redis_client.ping()
        return redis_client
    except Exception:
        return None

@app.get("/helth", tags=["Health"])
def status_api():
    """Endpoint de verificação de saúde da API."""
    return {"status": "online", "mensage": "API in execution"}

@app.get("/api/vagas")
def buscar_vagas(
    cargo: str = Query(None, description="filter per name of job. Ex: Developer"),
    cidade: str = Query(None, description="filter per city. Ex: Recife"),
    plataforma: str = Query(None, description="filter per platform. Ex: InfoJobs")
):
    """
    Busca e filtra as vagas extraídas e consolidadas no banco de dados.
    """
    banco = conectar_banco()
    if not banco:
        raise HTTPException(status_code=503, detail="Banco de dados de vagas temporariamente indisponível.")

    vagas_brutas = banco.hgetall("vagas_database")
    
    lista_vagas = []
    for id_vaga, vaga_str in vagas_brutas.items():
        try:
            vaga = json.loads(vaga_str)
            lista_vagas.append(vaga)
        except json.JSONDecodeError:
            continue

    # Motor de Filtros
    if cargo:
        lista_vagas = [v for v in lista_vagas if cargo.lower() in v.get("titulo", "").lower() or cargo.lower() in v.get("cargo_buscado", "").lower()]
    
    if cidade:
        lista_vagas = [v for v in lista_vagas if cidade.lower() in v.get("localizacao", "").lower()]
        
    if plataforma:
        lista_vagas = [v for v in lista_vagas if plataforma.lower() == v.get("plataforma", "").lower()]

    return {
        "total_encontrado": len(lista_vagas),
        "vagas": lista_vagas
    }