from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    "o que o navegador envia no POST/ CHAT"
    session_id: str = Field(..., examples=["id_usuario"])
    pergunta: str = Field(..., min_length=1, examples=["gastei 50 reais no mercado."])

class chatResponse(BaseModel):
    "o que a api devolve no POST / chat"
    resposta: str
    agentes_chamados: list[str] = Field(default_factory=list)

class SessionResponse(BaseModel):
    "o que a api devolve nas rotas de ciclo de vida da sessão (iniciar/encerrar)"
    session_id: str
    resumo: str | None = None
