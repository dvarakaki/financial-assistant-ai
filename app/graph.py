"""Fluxo da conversa usado pela rota POST /chat."""
import re
from langchain.agents import create_agent
from app.guardrail import anonimizar_entrada, guardrail_entrada, guardrail_saida
from app.infra.db import TransacaoTurno
from app.juiz import FRASE_SEGURA, julgar
from app.llms import llm_especialista, llm_rapido
# Só salvar_mensagem entra aqui. iniciar_sessao() é chamada por ela mesma, e
# encerrar_sessao() mudou de camada: virou POST /sessions/{id}/encerrar, em
# app/routes/sessions.py. Este módulo cuida de UM turno; abrir e fechar a
# conversa é evento de outra natureza, disparado pelo usuário — não por uma
# pergunta.
from app.memory import salvar_mensagem
from app.observabilidade import abrir_turno, fechar_turno, no_atual
from app.prompts import (
    AGENDA_PROMPT_COMPLETO,
    FAQ_PROMPT,
    FINANCEIRO_PROMPT_COMPLETO,
    ORQUESTRADOR_PROMPT_COMPLETO,
    ROUTER_PROMPT_COMPLETO,
)
from app.tools.agenda import TOOLS_AGENDA
from app.tools.calendario_google import TOOLS_GOOGLE
from app.tools.faq import faq_retriever
from app.tools.financeiro import TOOLS
from app.tools.memoria import TOOLS_MEMORIA
from app.tools.perfil import TOOLS_PERFIL


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
    tools=TOOLS + TOOLS_MEMORIA + TOOLS_PERFIL,
    system_prompt=FINANCEIRO_PROMPT_COMPLETO,
)
agenda_agent = create_agent(
    model=llm_especialista,
    tools=TOOLS_AGENDA + TOOLS_GOOGLE + TOOLS_MEMORIA,
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


def _identificar_rota(pergunta: str, config: dict) -> tuple[str, str, list]:
    with no_atual("roteador"):
        resultado = router_agent.invoke(
            {"messages": [{"role": "user", "content": pergunta}]},
            config=config,
        )
    mensagens = resultado["messages"]
    resposta = _texto(mensagens[-1])
    for linha in resposta.splitlines():
        if linha.strip().startswith("ROUTE="):
            rota = linha.split("=", 1)[1].strip().lower()
            if rota in {"financeiro", "agenda", "faq"}:
                return rota, "", mensagens
    return "direta", resposta, mensagens


def _responder(rota: str, pergunta: str, config: dict) -> tuple[str, list]:
    if rota == "financeiro":
        with no_atual("financeiro"):
            resultado = financeiro_agent.invoke(
                {"messages": [{"role": "user", "content": pergunta}]}, config=config
            )
        resposta = _texto(resultado["messages"][-1])
        mensagens = resultado["messages"]
    elif rota == "faq":
        with no_atual("faq"):
            resultado = faq_agent.invoke({
                "messages": [{"role": "user", "content": pergunta}]
            })
        resposta = _texto(resultado["messages"][-1])
        mensagens = resultado["messages"]
    else:
        with no_atual("agenda"):
            resultado = agenda_agent.invoke(
                {"messages": [{"role": "user", "content": pergunta}]}, config=config
            )
        resposta = _texto(resultado["messages"][-1])
        mensagens = resultado["messages"]

    if rota in {"financeiro", "agenda"}:
        with no_atual("orquestrador"):
            resposta = _texto(llm_rapido.invoke(
                f"{ORQUESTRADOR_PROMPT_COMPLETO}\n\nResposta do especialista:\n{resposta}"
            ))
    return resposta, mensagens


def executar_fluxo_assessor(
    pergunta_usuario: str, session_id: str, user_id: str = "usuario_teste"
) -> str:
    # O registro abre antes de qualquer chamada de modelo e fecha no finally,
    # inclusive quando algo levanta exceção no meio do fluxo. A rota /monitor
    # só lê o que ficou anotado aqui.
    turno_id = abrir_turno()
    status = "erro"
    rota = ""
    # Toda escrita no Postgres deste turno (add_transaction, update_transaction,
    # add_event) fica nesta transação, sem commit, até o veredito do juiz.
    # As tools a recebem pelo RunnableConfig, como o user_id.
    transacao = TransacaoTurno()
    try:
        pergunta_usuario_anonimizado, mapa_pii = anonimizar_entrada(pergunta_usuario)

        verificacao = guardrail_entrada(pergunta_usuario_anonimizado)
        if verificacao["bloqueado"]:
            resposta = verificacao["mensagem"]
            status = "bloqueado"
            salvar_mensagem(session_id, "human",     pergunta_usuario_anonimizado, user_id=user_id)
            salvar_mensagem(session_id, "assistant", resposta, user_id=user_id)
            return resposta

        config = {"configurable": {
            "thread_id": session_id, "user_id": user_id, "transacao": transacao,
        }}
        rota, resposta_direta, msgs_roteador = _identificar_rota(pergunta_usuario, config)
        if rota == "direta":
            resposta, msgs_especialista = resposta_direta, []
        else:
            resposta, msgs_especialista = _responder(rota, pergunta_usuario, config)

        resposta = guardrail_saida(resposta, mapa_pii)["conteudo"]

        # O juiz fala por último, inclusive no FAQ: a evidência é o que as
        # tools devolveram neste turno (roteador + especialista).
        with no_atual("juiz"):
            resposta = julgar(pergunta_usuario, resposta, [*msgs_roteador, *msgs_especialista])

        # A fronteira da etapa 8: a escrita só permanece se o juiz aprovou.
        # julgar() devolve a resposta original ou FRASE_SEGURA — esta cobre
        # recusa, juiz sem chave, erro HTTP e timeout. Resposta vazia não foi
        # julgada, então também não confirma. Sem confirmar, o finally fecha
        # a conexão e o Postgres descarta o que as tools gravaram.
        if resposta.strip() and resposta != FRASE_SEGURA:
            transacao.confirmar()

        salvar_mensagem(session_id, "human",     pergunta_usuario_anonimizado, user_id=user_id)
        salvar_mensagem(session_id, "assistant", resposta, user_id=user_id)

        status = "ok"
        return resposta
    finally:
        transacao.fechar()
        fechar_turno(turno_id, session_id=session_id, rota=rota, status=status)