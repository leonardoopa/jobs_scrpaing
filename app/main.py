from fastapi import FastAPI, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.core.database import SessionLocal, Vaga

app = FastAPI(
    title="Job Scraper API",
    description="RESTful API connected to PostgreSQL for consolidated job searches.",
    version="1.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/health", tags=["Health Check"])
def health_check():
    """Endpoint to verify if the API is up and running."""
    return {"status": "online", "database": "PostgreSQL", "message": "API is running at 100% capacity!"}

@app.get("/api/jobs", tags=["Jobs"])
def get_jobs(
    role: str = Query(None, description="Filter by job title (e.g., Developer)"),
    location: str = Query(None, description="Filter by city or location (e.g., Recife)"),
    platform: str = Query(None, description="Filter by source platform (e.g., InfoJobs)"),
    db: Session = Depends(get_db) # FastAPI injects the DB connection here!
):
    """Fetches jobs directly from PostgreSQL applying the provided filters."""
    
    query = db.query(Vaga)

    if role:
        query = query.filter(
            or_(
                Vaga.titulo.ilike(f"%{role}%"),
                Vaga.cargo_buscado.ilike(f"%{role}%")
            )
        )
    
    if location:
        query = query.filter(Vaga.localizacao.ilike(f"%{location}%"))
        
    if platform:
        query = query.filter(Vaga.plataforma.ilike(f"%{platform}%"))

    found_jobs = query.all()

    return {
        "total_found": len(found_jobs),
        "jobs": found_jobs
    }