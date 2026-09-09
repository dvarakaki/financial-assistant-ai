"""Fluxo da conversa usado pela rota POST /chat."""
import re
from langchain.agents import create_agent
from app.guardrail import anonimizar_entrada, guardrail_entrada, guardrail_saida
from app.llms import llm_especialista, llm_rapido
# Só salvar_mensagem entra aqui. iniciar_sessao() é chamada por ela mesma, e
# encerrar_sessao() mudou de camada: virou POST /sessions/{id}/encerrar, em
# app/routes/sessions.py. Este módulo cuida de UM turno; abrir e fechar a
# conversa é evento de outra natureza, disparado pelo usuário — não por uma
# pergunta.
from app.memory import salvar_mensagem
from app.prompts import (
    AGENDA_PROMPT_COMPLETO,
    FAQ_PROMPT,
    FINANCEIRO_PROMPT_COMPLETO,
    ORQUESTRADOR_PROMPT_COMPLETO,
    ROUTER_PROMPT_COMPLETO,
)
from app.tools.faq import faq_retriever
from app.tools.financeiro import TOOLS
from app.tools.memoria import TOOLS_MEMORIA


# create_agent executa o ciclo: modelo -> chamada de tool -> resposta final.
#
# TOOLS_MEMORIA (buscar_historico) vai para o roteador e para os especialistas
# que respondem em linguagem natural derivada de dados — financeiro e agenda —
# porque os dois usam a memória para coisas diferentes:
#
#   roteador     -> perguntas que SÓ dependem do passado ("o que eu te falei
#                   sobre a viagem?"). Sem a tool aqui, a pergunta cairia em
#                   fora_escopo, porque não existe especialista para isso.
#   especialista -> perguntas em que o passado é insumo da RESPOSTA
#                   ("lembrando da viagem, quanto preciso separar?").
#
# O roteador e o especialista de agenda passaram a ser create_agent (antes
# eram chamadas diretas de LLM) só para poderem chamar essa tool — o roteiro
# original desta etapa assumia um grafo LangGraph com nós próprios; este
# projeto não tem essa camada, então a conversão para agente é o jeito mínimo
# de dar tool-calling a eles sem reescrever a arquitetura.
#
# O FAQ fica de fora de propósito: ele responde sobre as regras do
# Assessor.AI a partir do PDF, não sobre o que este usuário conversou.
router_agent = create_agent(
    model=llm_rapido,
    tools=TOOLS_MEMORIA,
    system_prompt=ROUTER_PROMPT_COMPLETO,
)
financeiro_agent = create_agent(
    model=llm_especialista,
    tools=TOOLS + TOOLS_MEMORIA,
    system_prompt=FINANCEIRO_PROMPT_COMPLETO,
)
agenda_agent = create_agent(
    model=llm_especialista,
    tools=TOOLS_MEMORIA,
    system_prompt=AGENDA_PROMPT_COMPLETO,
)
faq_agent = create_agent(
    model=llm_rapido,
    tools=[faq_retriever],
    system_prompt=FAQ_PROMPT,
)


def _texto(resposta) -> str:
    texto = str(getattr(resposta, "content", resposta))
    # Proteção adicional para não expor raciocínio caso um provedor o envie em texto.
    return re.sub(r"<think>.*?</think>\s*", "", texto, flags=re.DOTALL).strip()


def _identificar_rota(pergunta: str, config: dict) -> tuple[str, str]:
    resultado = router_agent.invoke(
        {"messages": [{"role": "user", "content": pergunta}]},
        config=config,
    )
    resposta = _texto(resultado["messages"][-1])
    for linha in resposta.splitlines():
        if linha.strip().startswith("ROUTE="):
            rota = linha.split("=", 1)[1].strip().lower()
            if rota in {"financeiro", "agenda", "faq"}:
                return rota, ""
    return "direta", resposta


def _responder(rota: str, pergunta: str, config: dict) -> str:
    if rota == "financeiro":
        resultado = financeiro_agent.invoke(
            {"messages": [{"role": "user", "content": pergunta}]}, config=config
        )
        resposta = _texto(resultado["messages"][-1])
    elif rota == "faq":
        resultado = faq_agent.invoke({
            "messages": [{"role": "user", "content": pergunta}]
        })
        resposta = _texto(resultado["messages"][-1])
    else:
        resultado = agenda_agent.invoke(
            {"messages": [{"role": "user", "content": pergunta}]}, config=config
        )
        resposta = _texto(resultado["messages"][-1])

    if rota in {"financeiro", "agenda"}:
        resposta = _texto(llm_rapido.invoke(
            f"{ORQUESTRADOR_PROMPT_COMPLETO}\n\nResposta do especialista:\n{resposta}"
        ))
    return resposta

def executar_fluxo_assessor(
    pergunta_usuario: str, session_id: str, user_id: str = "usuario_teste"
) -> str:
    pergunta_usuario_anonimizado, mapa_pii = anonimizar_entrada(pergunta_usuario)

    verificacao = guardrail_entrada(pergunta_usuario_anonimizado)
    if verificacao["bloqueado"]:
        resposta = verificacao["mensagem"]
        salvar_mensagem(session_id, "human",     pergunta_usuario_anonimizado, user_id=user_id)
        salvar_mensagem(session_id, "assistant", resposta, user_id=user_id)
        return resposta

    config = {"configurable": {"thread_id": session_id, "user_id": user_id}}
    rota, resposta_direta = _identificar_rota(pergunta_usuario, config)
    resposta = resposta_direta if rota == "direta" else _responder(rota, pergunta_usuario, config)

    resposta = guardrail_saida(resposta, mapa_pii)["conteudo"]

    salvar_mensagem(session_id, "human",     pergunta_usuario_anonimizado, user_id=user_id)
    salvar_mensagem(session_id, "assistant", resposta, user_id=user_id)

    return resposta