from fastapi import APIRouter
from app.schemas import chatResponse, ChatRequest
from app.graph import executar_fluxo_assessor

# O APIRouter é um "mini fastApi"; junta endpoints relacionados num arquivo.
# o main.py depois pluca esse conjunto na aplicação

router= APIRouter(tags=["chat"])

@router.post("/chat")
def conversar(requisicao: ChatRequest) -> chatResponse:
    resultado = executar_fluxo_assessor(requisicao.pergunta, requisicao.session_id)
    return chatResponse(**resultado)
