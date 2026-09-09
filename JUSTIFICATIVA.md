# JUSTIFICATIVA - Perfil do usuário

## Arquivos criados ou modificados

| Arquivo | Tipo | O que tem |
|---|---|---|
| `app/perfil.py` | criado | Camada de domínio: `salvar_perfil`, `buscar_perfil_estruturado` (Mongo) e `buscar_restricoes` (Qdrant). |
| `app/tools/perfil.py` | criado | `consultar_perfil_financeiro` e `buscar_restricoes_perfil`, as duas tools do especialista financeiro. |
| `app/routes/perfil.py` | criado | `POST /perfil`. |
| `app/schemas.py` | modificado | Acrescenta `PerfilRequest` (contrato + validações). |
| `app/main.py` | modificado | Registra o router de perfil. |
| `app/graph.py` | modificado | `financeiro_agent` passa a receber `TOOLS_PERFIL`. |
| `app/prompts.py` | modificado | Seção "PERFIL DO USUÁRIO" no `FINANCEIRO_PROMPT`. |
| `frontend/perfil.html`, `frontend/perfil.css`, `frontend/perfil.js` | copiados, sem alteração | Tela de perfil fornecida pronta. |

## Por onde o perfil entra, e onde cada parte é gravada?

Entra só pelo `POST /perfil` (`app/routes/perfil.py`), validado por `PerfilRequest`. `salvar_perfil()` grava os campos numéricos e o `perfil_investidor` num upsert por `user_id` na collection `perfis` do MongoDB; as `restricoes` são apagadas (todas as anteriores daquele `user_id`) e reinseridas, uma por uma, como pontos na collection `perfil_restricoes` do Qdrant.

## Por que o texto livre não é busca por palavra

Cada restrição é salva como um ponto separado no Qdrant, com seu próprio embedding, não um bloco único com todas juntas. Isso importa porque a pergunta do usuário raramente usa as mesmas palavras da restrição: perguntar sobre deixar dinheiro travado precisa achar a frase sobre o carro, mesmo sem a palavra "travado" nela. Busca por palavra-chave não pega essa relação; busca vetorial pega, porque compara significado, não texto.

## Uma tool ou duas

Duas. `consultar_perfil_financeiro` lê os números direto do Mongo (sem custo de embedding, é sempre a mesma consulta) e deve ser chamada toda vez que a resposta depende de renda, gasto, horizonte ou perfil de risco. `buscar_restricoes_perfil` já tem custo de embedding e só compensa rodar quando dá pra suspeitar de alguma restrição relevante. Separar evita gastar embedding à toa numa pergunta que só precisa dos números, e reflete que os dois tipos de dado já são guardados de formas diferentes.

## Isolamento entre usuários

No Mongo a leitura e a escrita sempre passam por `user_id` (upsert e `find_one` pela mesma chave). No Qdrant, toda escrita e toda busca carrega um filtro obrigatório por `user_id`, com índice de payload criado na collection pra esse campo funcionar como filtro. Não existe caminho no código que leia sem esse filtro.

## Tool consulta o banco direto ou via HTTP

Direto. Chama as funções de `app.perfil`, sem passar por HTTP. Mesmo padrão que `buscar_historico` já usa em `app/tools/memoria.py`. Não faz sentido dar uma volta pela rede pra um dado que já está acessível no mesmo processo, e assim reaproveita o cliente Qdrant e a conexão Mongo que já existem como singletons.

## Por que não um agente "perfil"

Porque ninguém conversa sobre o cadastro em si, perfil só existe como apoio pra uma pergunta que já é financeira (quanto investir, quanto guardar, se dá pra travar o dinheiro). Um agente próprio ia duplicar roteamento pra um caso que sempre acaba caindo no financeiro de qualquer jeito.

## Por que o chat não altera o cadastro

Porque o cadastro é a base que sustenta o conselho, e a tela já valida ele direito (gasto sempre menor que renda, por exemplo). Se o chat pudesse editar isso em linguagem natural, um pedido ambíguo passaria batido por essa validação e corromperia o dado sem ninguém perceber.
