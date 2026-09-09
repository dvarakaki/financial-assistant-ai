"""
Perfil financeiro do usuário — dado de apoio consultado pelo especialista
financeiro, nunca um domínio próprio.

Dois tipos de dado, duas formas de guardar:
  - Estruturado (renda, gasto fixo, horizonte, perfil de investidor): consulta
    direta por user_id. Vai para o MongoDB, mesma base usada por memory.py.
  - Texto livre (restrições): precisa ser encontrado por assunto, não por
    palavra exata, então cada restrição vira um ponto próprio no Qdrant —
    uma lista de frases indexada como um bloco só faria a última desaparecer
    na busca por similaridade.

Só existe escrita (chamada pela rota POST /perfil). Leitura é feita pelas
tools em app/tools/perfil.py, nunca pelo chat.
"""

import uuid

from pymongo import MongoClient
from qdrant_client import models

from app.config import MONGODB_URI
from app.vectorstore import qdrant, gerar_embedding, EMBEDDING_DIM

_mongo     = MongoClient(MONGODB_URI)
db         = _mongo["assessor"]
col_perfis = db["perfis"]

col_perfis.create_index("user_id", unique=True)

COLLECTION_PERFIL_RESTRICOES = "perfil_restricoes"

if COLLECTION_PERFIL_RESTRICOES not in {c.name for c in qdrant.get_collections().collections}:
    qdrant.create_collection(
        collection_name=COLLECTION_PERFIL_RESTRICOES,
        vectors_config=models.VectorParams(
            size=EMBEDDING_DIM, distance=models.Distance.COSINE
        ),
    )
    # Filtrar por user_id (delete e busca semântica) exige um índice de
    # payload nesse campo — sem isso o Qdrant recusa o filtro.
    qdrant.create_payload_index(
        collection_name=COLLECTION_PERFIL_RESTRICOES,
        field_name="user_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )


def salvar_perfil(perfil: dict) -> dict:
    """Grava (ou substitui) o perfil de um user_id nos dois bancos.

    O dado estruturado sobrescreve o documento existente (upsert por
    user_id). As restrições substituem inteiramente o que estava salvo:
    apaga todos os pontos antigos daquele user_id no Qdrant antes de indexar
    os novos, para que uma restrição removida deixe de ser encontrável.
    """
    user_id = perfil["user_id"]

    col_perfis.update_one(
        {"user_id": user_id},
        {"$set": perfil},
        upsert=True,
    )

    qdrant.delete(
        collection_name=COLLECTION_PERFIL_RESTRICOES,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))]
            )
        ),
    )

    restricoes = perfil.get("restricoes") or []
    if restricoes:
        vetores = [gerar_embedding(texto) for texto in restricoes]
        qdrant.upsert(
            collection_name=COLLECTION_PERFIL_RESTRICOES,
            points=[
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vetor,
                    payload={"user_id": user_id, "texto": texto},
                )
                for texto, vetor in zip(restricoes, vetores)
            ],
        )

    return perfil


def buscar_perfil_estruturado(user_id: str) -> dict | None:
    """Lê o dado estruturado do perfil. None se o usuário nunca cadastrou."""
    doc = col_perfis.find_one({"user_id": user_id}, {"_id": 0})
    return doc


def buscar_restricoes(user_id: str, busca: str, limite: int = 3) -> list[str]:
    """Busca semântica nas restrições cadastradas por este user_id."""
    vetor = gerar_embedding(busca)
    resultados = qdrant.query_points(
        collection_name=COLLECTION_PERFIL_RESTRICOES,
        query=vetor,
        query_filter=models.Filter(
            must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))]
        ),
        limit=limite,
    )
    return [ponto.payload["texto"] for ponto in resultados.points]
