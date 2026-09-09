from typing import Literal

from pydantic import BaseModel, Field, model_validator

class ChatRequest(BaseModel):
    """O que o navegador envia no POST /chat."""

    session_id: str = Field(
        ...,
        description="Identifica a conversa (UUID gerado pelo front a cada sessão).",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    user_id: str = Field(
        default="usuario_teste",
        description="Identifica o usuário de forma estável entre sessões. "
                    "É o que permite a memória de longo prazo funcionar.",
        examples=["usuario_teste"],
    )
    pergunta: str = Field(
        ...,
        min_length=1,
        description="A mensagem do usuário — o que antes vinha do input().",
        examples=["gastei 50 reais no mercado hoje"],
    )
    
class ChatResponse(BaseModel):
    """O que a api devolve no POST /chat."""
    resposta: str
    agentes_chamados: list[str] = Field(default_factory=list)

class SessionResponse(BaseModel):
    """O que a api devolve nas rotas de ciclo de vida da sessão (iniciar/encerrar)"""
    session_id: str
    resumo: str | None = None

class PerfilRequest(BaseModel):
    """Contrato com a tela Perfil — o POST /perfil aceita exatamente estes
    campos, e a resposta devolve o mesmo formato (é assim que a tela confirma
    o salvamento)."""

    user_id: str = Field(
        ...,
        min_length=1,
        description="Identificador estável do usuário, o mesmo que o chat usa.",
        examples=["usuario_teste"],
    )
    renda_mensal: float = Field(
        ..., gt=0, description="Número maior que zero.", examples=[6000]
    )
    gasto_fixo_mensal: float = Field(
        ...,
        ge=0,
        description="Número maior ou igual a zero e menor que a renda mensal.",
        examples=[3800],
    )
    horizonte_meses: int = Field(
        ..., ge=1, le=120, description="Inteiro entre 1 e 120.", examples=[18]
    )
    perfil_investidor: Literal["conservador", "moderado", "arrojado"] = Field(
        ..., examples=["conservador"]
    )
    restricoes: list[str] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Lista de 1 a 5 frases livres, cada uma independente da outra.",
        examples=[[
            "não quero nada muito arriscado, prefiro dormir tranquilo",
            "preciso deixar uma reserva para consertar o carro",
        ]],
    )

    @model_validator(mode="after")
    def _gasto_menor_que_renda(self) -> "PerfilRequest":
        if self.gasto_fixo_mensal >= self.renda_mensal:
            raise ValueError("gasto_fixo_mensal deve ser menor que renda_mensal.")
        return self
