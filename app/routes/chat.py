from fastapi import APIRouter
from app.schemas import ChatResponse, ChatRequest
from app.graph import executar_fluxo_assessor

# O APIRouter é um "mini fastApi"; junta endpoints relacionados num arquivo.
# o main.py depois pluca esse conjunto na aplicação

router= APIRouter(tags=["chat"])

@router.post("/chat", response_model=ChatResponse)
def conversar(requisicao: ChatRequest) -> ChatResponse:
    """Uma mensagem do usuário, uma resposta do assessor."""
    resposta = executar_fluxo_assessor(
        requisicao.pergunta, requisicao.session_id, requisicao.user_id
    )
    return ChatResponse(resposta=resposta)