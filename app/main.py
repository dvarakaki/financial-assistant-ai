from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routes.chat import router as chat_router
from app.config import validar_config  
from app.routes.sessions import router as sessions_router
from app.routes.perfil import router as perfil_router
from fastapi.middleware.cors import CORSMiddleware
from app.config import FRONTEND_DIR

for _problema in validar_config():
    print(f"[config] ATENÇÃO: {_problema}")
    
app = FastAPI(
    title="AssessorIA",
    description="Assessor financeiro e de agenda com LangChain e LangGraph",
    version="0.1.0",
)

app.include_router(chat_router)
app.include_router(sessions_router)
app.include_router(perfil_router)
@app.get("/health")
def health() -> dict:
    problemas = validar_config()
    return {
        "status": "ok",
        "problemas_de_configuracao": problemas
    }

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if (FRONTEND_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    @app.get("/", tags=["infra"])
    def raiz() -> dict:
        return {"mensagem": "API do Assessor no ar. O frontend ainda não foi criado"}