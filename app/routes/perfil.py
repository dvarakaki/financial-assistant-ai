"""
A rota da tela Perfil.

Só existe escrita: o POST valida o contrato (app.schemas.PerfilRequest),
grava (app.perfil.salvar_perfil) e devolve o perfil gravado — é assim que a
tela confirma o salvamento. Dado inválido nunca chega até aqui: o Pydantic já
recusa antes, com 422.
"""

from fastapi import APIRouter

from app.perfil import salvar_perfil
from app.schemas import PerfilRequest

router = APIRouter(tags=["perfil"])


@router.post("/perfil", response_model=PerfilRequest)
def salvar(requisicao: PerfilRequest) -> PerfilRequest:
    """Grava o perfil financeiro do usuário. Salvar de novo com o mesmo
    user_id atualiza o cadastro por inteiro, inclusive as restrições."""
    salvar_perfil(requisicao.model_dump())
    return requisicao
