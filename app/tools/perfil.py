"""
Tools de perfil — dado de apoio do especialista financeiro.

Duas tools, porque os dois tipos de dado do perfil se consultam de formas
diferentes: consultar_perfil_financeiro é uma leitura direta (sempre a mesma
consulta, sem custo de embedding); buscar_restricoes_perfil é uma busca
semântica que só faz sentido rodar quando o especialista precisa checar uma
restrição sobre um assunto específico.

Em ambas, o user_id NUNCA é preenchido pelo modelo — vem do RunnableConfig da
requisição, no mesmo padrão de buscar_historico em app/tools/memoria.py.
"""

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from app.perfil import buscar_perfil_estruturado, buscar_restricoes

# Função privada para extrair o user_id do RunnableConfig, retornando None se não houver.
def _user_id(config: RunnableConfig) -> str | None:
    return (config or {}).get("configurable", {}).get("user_id")

# Tool para consultar o perfil financeiro estruturado do usuário.
@tool
def consultar_perfil_financeiro(config: RunnableConfig) -> str:
    """Consulta o cadastro financeiro estruturado do usuário: renda mensal,
    gasto fixo mensal, horizonte de investimento (em meses) e perfil de
    investidor (conservador, moderado ou arrojado).

    Use ANTES de qualquer recomendação que dependa de quanto o usuário ganha,
    gasta, em quanto tempo pretende usar o dinheiro ou seu apetite a risco —
    por exemplo "quanto faz sentido guardar por mês?" ou "posso investir tudo
    isso?". Se a tool disser que não há cadastro, NÃO invente números: oriente
    o usuário a preencher a tela de perfil.
    """
    user_id = _user_id(config)
    if not user_id:
        return "Não foi possível identificar o usuário para consultar o perfil."

    perfil = buscar_perfil_estruturado(user_id)
    if not perfil:
        return "Nenhum perfil cadastrado para este usuário. Oriente-o a preencher a tela de perfil."

    return (
        f"renda_mensal: {perfil['renda_mensal']}\n"
        f"gasto_fixo_mensal: {perfil['gasto_fixo_mensal']}\n"
        f"horizonte_meses: {perfil['horizonte_meses']}\n"
        f"perfil_investidor: {perfil['perfil_investidor']}"
    )

# Tool para buscar restrições do perfil financeiro do usuário com base em uma busca semântica.
@tool
def buscar_restricoes_perfil(busca: str, config: RunnableConfig) -> str:
    """Busca, entre as restrições que o usuário cadastrou na tela de perfil,
    as que forem relevantes ao assunto informado (busca semântica: encontra
    a restrição mesmo que ela não use as mesmas palavras da pergunta).

    Use quando o conselho financeiro puder esbarrar em alguma restrição do
    usuário — por exemplo antes de sugerir deixar dinheiro investido e
    travado por um tempo, verifique se não há uma restrição sobre precisar
    desse dinheiro antes.

    Args:
        busca: o assunto a procurar entre as restrições (ex.: "carro", "prazo
            para resgatar", "tolerância a risco").
    """
    user_id = _user_id(config)
    if not user_id:
        return "Não foi possível identificar o usuário para consultar as restrições."

    restricoes = buscar_restricoes(user_id, busca)
    if not restricoes:
        return "Nenhuma restrição cadastrada relevante para esse assunto."

    return "\n".join(f"- {texto}" for texto in restricoes)


TOOLS_PERFIL = [consultar_perfil_financeiro, buscar_restricoes_perfil]
