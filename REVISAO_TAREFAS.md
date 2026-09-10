# Lista de Revisão — RedmineAssistant

> Documento de trabalho para execução por uma IA de codificação (ou desenvolvedor).
> Cada item traz: contexto do problema, arquivos/linhas afetados, passos concretos de
> implementação e critério de aceite. Execute na ordem de prioridade (P0 → P2), um item
> por commit/PR, para permitir revisão isolada de cada mudança.
>
> Convenção de severidade: **P0** = crítico (segurança/corretude de dados), **P1** =
> importante (qualidade/manutenibilidade), **P2** = menor/cosmético.

---

## Status de execução (concluídos)

> Todos os itens abaixo foram implementados e estão no histórico `main`.
> **Decisão (P0-1):** o histórico do git **não** foi reescrito — o blob de 64MB
> (`dist/RedmineAssitant.exe`) permanece nos commits antigos, conforme decisão explícita
> do usuário.

| Item | Status | Referência |
|---|---|---|
| P0-1 — `.gitignore` e proteção de arquivos sensíveis | ✅ Concluído | commit `85fa1d7` |
| P0-2 — Confirmação obrigatória antes de ações da IA no Redmine | ✅ Concluído (pré-existente) | `ferramentas.py`/`app_flet.py` |
| P0-3 — `activity_id` dinâmico no lançamento de horas | ✅ Concluído (pré-existente) | `redmine_api.py` |
| P1-1 — Vocabulário único de status | ✅ Concluído | commit `a4d2190` (scripts); app pré-existente |
| P1-2 — Validação de datas (`normalizar_data`) | ✅ Concluído | commit `a850b45` (script); `acoes.py`/`redmine_api.py` |
| P1-3 — Deduplicação de `_criar_api` | ✅ Concluído | commit `72823b8` |
| P1-4 — Cobertura mínima de testes + CI | ✅ Concluído | commit `1113a71` (`tests/`, `.github/`) |
| P1-5 — Extração de `acoes.py` | ✅ Concluído (pré-existente) | `acoes.py` |
| P2-1 — Remoção de `RedmineAPI.atividade_id` | ✅ Concluído (pré-existente) | `redmine_api.py` |
| P2-2 — Remoção de `paramiko` órfão | ✅ Concluído | commit `67c4a5b` |
| P2-3 — Logging de erros silenciosos | ✅ Concluído | commit `6718754` (`logger_app.py` + usos) |

---

## ✅ P0-1 — Adicionar `.gitignore` e proteger arquivos sensíveis

**Problema:** o repositório não tem `.gitignore`. Os arquivos `config.json`,
`credenciais.txt`, `assistente_local.db`, `atividades_ativas.xlsx`, `.venv/`, `dist/`,
`build/` e `*.spec` gerados por build não têm nenhuma proteção contra commit acidental,
apesar de o `README.md` (seção "Segurança") já instruir "não versione". O histórico do
git já mostra o padrão de risco: o primeiro commit trouxe `dist/RedmineAssitant.exe`
(64.698.849 bytes) e `flet-runtime/flet-windows.zip` (40.111.107 bytes); o `.exe` foi
removido no commit seguinte, mas **permanece no histórico** (blobs não são apagados por
um novo commit).

**Arquivos:** raiz do repositório (novo arquivo `.gitignore`).

**Passos:**
1. Criar `.gitignore` na raiz contendo pelo menos:
   ```
   .venv/
   __pycache__/
   *.pyc
   config.json
   credenciais.txt
   assistente_local.db
   atividades_ativas.xlsx
   dist/
   build/
   *.spec.bak
   ```
   Não ignore `RedmineAssistant.spec` (é rastreado intencionalmente — é o spec do
   PyInstaller usado pelo build, não um artefato gerado).
2. Rodar `git status` e confirmar que nenhum arquivo sensível já rastreado aparece
   (nesta revisão, nenhum estava rastreado — apenas prevenir o futuro).
3. Não reescrever o histórico automaticamente. Abrir uma pergunta separada ao usuário
   perguntando se ele autoriza `git filter-repo` (ou BFG Repo-Cleaner) para remover o
   blob do `.exe` de 64MB do histórico — essa é uma operação destrutiva (reescreve SHAs
   de commits) que exige confirmação explícita antes de executar, e nunca deve ser feita
   silenciosamente.
4. Mover a documentação de build (`flet-runtime/flet-windows.zip`) para fora do controle
   de versão OU documentar por que ele precisa ficar versionado (o `compilar_windows.bat`
   depende dele para seed do cache do Flet offline — se for mantido, registrar
   explicitamente no README que é um binário grande intencional, não um artefato de
   build esquecido).

**Critério de aceite:** `.gitignore` existe e cobre os arquivos citados; `git status`
depois de rodar o app localmente (gerando `config.json`/`assistente_local.db`) não
mostra esses arquivos como "untracked to be committed"; decisão sobre reescrever
histórico foi explicitamente perguntada ao usuário (não assumida).

---

## ✅ P0-2 — Confirmação obrigatória antes de executar ações da IA no Redmine

**Problema:** em `app_flet.py`, a função `_enviar_assistente` (linhas ~1309-1348) recebe
o resultado de `ollama.chat_assistente(...)` e, se houver `acoes`, chama
`_executar_acoes(acoes)` (linha ~1339) **sem nenhuma confirmação do usuário**. As ações
incluem gravações reais no Redmine: lançar horas, mudar status, mudar prioridade,
adicionar comentário (ver `_acao_redmine` em `app_flet.py` linhas ~1169-1225). O prompt
do assistente (`ollama_client.py`, `_PROMPT_ASSISTENTE`, linhas ~331-365 e
`_montar_system_assistente`, linhas ~367-407) injeta `subject`/`descricao` de issues do
Redmine diretamente no contexto do LLM sem sanitização — texto que pode ter sido escrito
por qualquer pessoa com permissão de editar issues naquele Redmine. Isso é um vetor de
**prompt injection**: uma descrição de issue manipulada pode induzir o modelo a
retornar uma ação indevida (`format_actions`), e o app aplica no Redmine sem perguntar.

**Arquivos:**
- `app_flet.py` — `_enviar_assistente` (~1309), `_executar_acoes` (~1113),
  `_processar_acao`/`_acao_redmine` (~1150-1225).
- `ferramentas.py` — catálogo de ferramentas (para adicionar um flag de risco).

**Passos:**
1. Em `ferramentas.py`, adicionar ao dict de cada ferramenta em `TOOLS` uma chave
   `requer_confirmacao: bool` — `True` para todas as ferramentas de categoria
   `"Redmine"` (elas gravam dado real), `False` para as de categoria `"Local"`
   (`definir_prioridade`, `salvar_nota` — são reversíveis e não afetam o Redmine).
2. Em `app_flet.py`, alterar o fluxo de `_enviar_assistente`:
   - Ao receber `acoes` do LLM, **não chamar `_executar_acoes` diretamente**. Em vez
     disso, separar as ações em duas listas: as que `requer_confirmacao` é `False`
     (executam direto, como hoje) e as que é `True` (aguardam confirmação).
   - Para as que exigem confirmação, montar um resumo legível de cada ação (ex.:
     "Lançar 2h na #123 com o comentário: '...'", "Mudar status da #456 de 'Nova' para
     'Encerrada'") e exibir um `ft.AlertDialog` (ou `ft.BottomSheet`) com a lista de
     ações propostas, um botão **"Confirmar e aplicar"** e um **"Cancelar"**.
   - Só chamar `_executar_acoes` para essas ações depois do clique em "Confirmar".
   - Se o usuário cancelar, adicionar ao chat uma mensagem indicando que as ações
     propostas foram descartadas, sem aplicar nada.
3. Adicionar, na tela de Configuração (`view_config`), uma opção "Executar ações da
   IA sem confirmação (avançado)" — desmarcada por padrão — para usuários que
   entendam o risco e queiram o comportamento atual (execução imediata). Persistir
   essa opção em `config.json` via `config_manager.py` (nova chave, ex.:
   `"assistente_auto_executar": false`).
4. Não alterar o comportamento das ações manuais disparadas por botões explícitos da
   UI (ex.: "Lançar horas" na tela de atividade) — essas já são um clique intencional
   do usuário sobre dados que ele mesmo digitou, o risco de prompt injection não se
   aplica a elas.

**Critério de aceite:** pedir ao assistente algo que gere uma ação de categoria
"Redmine" (ex.: "lance 1h na #123") resulta em uma tela de confirmação antes de
qualquer chamada à API do Redmine, a menos que o usuário tenha ativado
explicitamente a opção de execução automática nas configurações. Ações locais
(prioridade/nota) continuam executando sem fricção.

---

## ✅ P0-3 — Corrigir fallback hardcoded de `activity_id` no lançamento de horas

**Problema:** em `redmine_api.py`, `lancar_horas` (linha ~216) usa
`activity_id = 9  # fallback: Desenvolvimento (ajustar conforme projeto)` quando
nenhum `activity_id` é informado. O assistente de IA chama essa função via
`_acao_redmine` em `app_flet.py` (linha ~1178, ação `lancar_horas`) **sem nunca passar
`activity_id`**, então todo lançamento de horas feito pelo assistente cai nesse
fallback. Em qualquer instância Redmine onde o ID 9 não corresponda a
"Desenvolvimento" (ou não exista), o apontamento de horas será lançado na atividade
errada ou falhará com erro genérico da API — silenciosamente incorreto na melhor
hipótese.

**Arquivos:** `redmine_api.py` (`lancar_horas`, ~linha 210-224), `app_flet.py`
(`_acao_redmine`, ação `lancar_horas`, ~linha 1171-1179), `ferramentas.py` (formato da
ferramenta `lancar_horas`, ~linha 21-30).

**Passos:**
1. Em `redmine_api.py`, adicionar um método `get_activity_id_padrao(self) -> int | None`
   que chama `get_time_entry_activities()` e retorna o `id` da atividade cujo nome
   contenha "desenvolvimento" (case-insensitive) ou, na ausência, a primeira atividade
   ativa da lista. Cachear o resultado na instância (`self._activity_id_padrao`) para
   não repetir a chamada a cada lançamento.
2. Em `lancar_horas`, remover o hardcode `activity_id = 9` e, quando `activity_id` for
   `None`, chamar `self.get_activity_id_padrao()`. Se isso também retornar `None`
   (nenhuma atividade configurada no Redmine), levantar `ValueError` explicando que é
   necessário informar `activity_id` — não silenciar o problema.
3. Em `app_flet.py`, na ação `lancar_horas` do assistente (`_acao_redmine`), permitir
   que o LLM informe opcionalmente `atividade` (nome, ex.: "Desenvolvimento",
   "Reunião") no `dados` da ação; se vier, resolver o `id` via
   `api.get_time_entry_activities()` comparando por nome (case-insensitive); se não
   vier, deixar `activity_id=None` para cair no novo fallback dinâmico do passo 2.
4. Atualizar o `formato` da ferramenta `lancar_horas` em `ferramentas.py` para incluir
   o campo opcional `"atividade": "<opcional, nome da atividade de apontamento>"`.

**Critério de aceite:** lançar horas pelo assistente sem especificar atividade usa a
atividade "Desenvolvimento" (ou equivalente) resolvida dinamicamente a partir do
Redmine configurado, não mais um ID fixo; testar contra uma instância onde a atividade
"Desenvolvimento" tenha um ID diferente de 9 confirma que o lançamento cai na
atividade certa.

---

## ✅ P1-1 — Unificar o vocabulário de status entre `app_flet.py` e `atualizar_redmine.py`

**Problema:** `app_flet.py` (linha 27) define
`STATUS_VALIDOS = ["Nova", "Backlog", "Especificação", "Em andamento", "Validação", "Encerrada", "Cancelada", "Suspensa"]`
(usado na tela de lançamento manual de horas), enquanto `atualizar_redmine.py` (linha
39) define `STATUS_VALIDOS = {"Nova", "Em andamento", "Backlog", "Especificação"}` (só
4 valores, usado para validar a coluna Status da planilha). Um status escolhido no app
(ex.: "Encerrada") é silenciosamente rejeitado se o mesmo fluxo for repetido via
planilha, sem nenhum aviso ao usuário do porquê da divergência.

**Arquivos:** `app_flet.py` (linha 27), `atualizar_redmine.py` (linha 39),
`redmine_api.py` (linha 19, `STATUS_ATIVOS`), `download_atividades.py` (usa
`STATUS_ATIVOS` para a validação de lista da planilha).

**Passos:**
1. Decidir uma fonte única de verdade: usar `RedmineAPI.get_status_ids()` (já existe,
   consulta `/issue_statuses.json`) para obter a lista real de status configurados no
   Redmine do usuário, em vez de listas fixas espalhadas em três arquivos.
2. Em `redmine_api.py`, manter `STATUS_ATIVOS` apenas como o subconjunto de status que
   definem "atividade ativa" (isso é uma regra de negócio do app, não vem do Redmine),
   mas expor também um método `get_todos_status(self) -> list[str]` que retorna todos
   os nomes de status cadastrados no Redmine (via `get_status_ids()`).
3. Em `app_flet.py`, trocar a lista fixa `STATUS_VALIDOS` por uma chamada a
   `self.api.get_todos_status()` ao montar o dropdown de status (com fallback para a
   lista fixa atual caso a API falhe/esteja indisponível nesse momento).
4. Em `atualizar_redmine.py`, trocar o `STATUS_VALIDOS` fixo pela mesma lista dinâmica
   (buscar via `RedmineAPI` ao iniciar o script, uma única vez, e usar para validar
   cada linha da planilha).
5. Atualizar `download_atividades.py` para que a aba "Config" de validação de lista
   também reflita todos os status do Redmine, não apenas `STATUS_ATIVOS` — ou, se a
   intenção for mesmo restringir a edição da planilha só aos 4 status "ativos",
   documentar isso explicitamente no cabeçalho da coluna/README para não parecer bug.

**Critério de aceite:** um status aceito pela tela de lançamento do app também é aceito
pelo fluxo de planilha (`atualizar_redmine.py`), e vice-versa — ou a diferença de
comportamento está documentada de forma explícita e visível ao usuário (ex.: texto na
UI dizendo "apenas 4 status podem ser atualizados via planilha").

---

## ✅ P1-2 — Adicionar validação de data nas ações de IA (`atualizar_previsao`)

**Problema:** a ação `atualizar_previsao` em `app_flet.py` (`_acao_redmine`, ~linha
1191-1195) envia `dados.get("data")` direto para `api.atualizar_issue(issue_id,
due_date=data)` sem validar o formato. Se o LLM alucinar uma data fora do padrão
`AAAA-MM-DD` (ex.: "30/09/2026" ou "próxima sexta"), a chamada falha com um erro
genérico da API do Redmine, sem mensagem clara para o usuário. `atualizar_redmine.py`
já tem uma função `_tratar_data` (linha ~71-91) que resolve exatamente esse problema
para o fluxo de planilha, mas ela não é reaproveitada pelo assistente de IA.

**Arquivos:** `atualizar_redmine.py` (`_tratar_data`, ~linha 71), `app_flet.py`
(`_acao_redmine`, ação `atualizar_previsao`, ~linha 1191).

**Passos:**
1. Mover `_tratar_data` de `atualizar_redmine.py` para `redmine_api.py` (como função de
   módulo, ex.: `normalizar_data(valor) -> str | None`), já que agora seria usada por
   dois consumidores. Atualizar o import em `atualizar_redmine.py` para usar a versão
   compartilhada.
2. Em `app_flet.py`, na ação `atualizar_previsao`, chamar
   `redmine_api.normalizar_data(dados.get("data"))` antes de enviar; se o resultado for
   `None` ou não bater com o padrão `AAAA-MM-DD` esperado pelo Redmine, retornar uma
   mensagem de erro clara (ex.: `"⚠️ Data '<valor>' inválida para #<id> — use
   AAAA-MM-DD."`) sem chamar a API.
3. Aplicar a mesma validação ao campo `data` da ação `lancar_horas` (mesmo raciocínio:
   hoje só cai no formato certo se o LLM acertar por conta própria).

**Critério de aceite:** enviar uma data em formato diferente de `AAAA-MM-DD` através do
assistente resulta numa mensagem de erro específica sobre formato de data, não numa
exceção genérica de HTTP.

---

## ✅ P1-3 — Eliminar duplicação de `_criar_api()`

**Problema:** `download_atividades.py` (linha ~49) e `atualizar_redmine.py` (linha
~94) têm a função `_criar_api()` copiada palavra por palavra (lê `config.json` via
`config_manager.carregar_config()`, cai para `credenciais.txt` se não houver
site/api_key). Qualquer mudança futura na lógica de criação do cliente (ex.: suporte a
timeout customizado, proxy, etc.) precisa ser replicada manualmente nos dois lugares —
risco real de divergência (como já aconteceu com o vocabulário de status no item
P1-1).

**Arquivos:** `download_atividades.py` (~linha 49-60), `atualizar_redmine.py` (~linha
94-105), `redmine_api.py`.

**Passos:**
1. Mover a função para `redmine_api.py` como `criar_api_da_config() -> RedmineAPI`
   (importando `config_manager.carregar_config` dentro da própria função, para evitar
   import circular — `config_manager.py` já importa de `ferramentas`/`ollama_client`,
   não de `redmine_api`, então não há ciclo).
2. Atualizar `download_atividades.py` e `atualizar_redmine.py` para importar e usar
   `redmine_api.criar_api_da_config()`, removendo as duas cópias locais de
   `_criar_api`.
3. Avaliar se `app_flet.py` (que hoje monta as credenciais manualmente em `_carregar` e
   em `_executar_acoes`, repetindo o mesmo dicionário `{"site":..., "api_key":...,
   "login":..., "senha":...}` duas vezes) também pode reusar essa função — ela recebe
   `self.config` (já carregado em memória, não precisa reler o arquivo), então talvez
   valha uma segunda função `criar_api(config: dict) -> RedmineAPI | None` que receba o
   dict já carregado, usada tanto pelos scripts quanto pelo app.

**Critério de aceite:** `grep -rn "_criar_api"` no repositório mostra apenas uma
definição (em `redmine_api.py`), usada pelos dois scripts standalone; comportamento de
autenticação permanece idêntico ao atual (testado rodando `download_atividades.py` e
`atualizar_redmine.py` sem `--aplicar`).

---

## ✅ P1-4 — Cobertura mínima de testes automatizados

**Problema:** o repositório não tem nenhum teste (`find . -iname "*test*"` não retorna
nada) nem CI. Para uma ferramenta que grava dados em produção no Redmine (horas,
status, prioridade), a ausência de testes é um risco real de regressão silenciosa —
principalmente após as mudanças dos itens anteriores (P0-3, P1-1, P1-2, P1-3 alteram
lógica de negócio compartilhada).

**Arquivos:** novo diretório `tests/`.

**Passos:**
1. Adicionar `pytest` a `requirements-dev.txt`.
2. Criar `tests/test_config_manager.py`: testar `carregar_config`/`salvar_config`
   (usando `tmp_path` do pytest para isolar o `CONFIG_FILE`, via monkeypatch do
   `config_manager.CONFIG_FILE`), cobrindo: config padrão quando arquivo não existe,
   migração legado (`_migrar_legado`), saneamento de `ferramentas_habilitadas`
   (`_sanear_ferramentas` com lista inválida/IDs desconhecidos).
3. Criar `tests/test_redmine_api.py`: testar `_ler_credenciais` (parsing de
   `credenciais.txt` com variações de chave/maiúsculas), `normalizar_data` (do item
   P1-2, casos: `AAAA-MM-DD`, `DD/MM/AAAA`, `DD/MM/AA`, texto inválido), e
   `get_activity_id_padrao` (do item P0-3) usando `requests_mock` ou um stub de
   `requests.get`/`requests.post` (não bater em um Redmine real).
4. Criar `tests/test_assistente_db.py`: testar `salvar_prioridade`/`prioridades`,
   `salvar_nota`/`notas`, `salvar_mensagem`/`historico`/`limpar_historico` usando um
   `DB_FILE` temporário (monkeypatch de `assistente_db.DB_FILE` para um arquivo em
   `tmp_path`).
5. Criar `tests/test_atualizar_redmine.py`: testar `_tratar_data`/`normalizar_data`
   (se movida, importar de `redmine_api`) e a lógica de validação de `main()` (status
   inválido, percentual fora de 0-100, horas <= 0) com um fake `RedmineAPI` (dublê
   simples que registra chamadas em vez de fazer HTTP).
6. Adicionar um workflow de CI (`.github/workflows/tests.yml`) rodando
   `pip install -r requirements.txt -r requirements-dev.txt && pytest` em pushes/PRs.
   Não é necessário testar `app_flet.py` fim a fim (UI do Flet é mais difícil de testar
   automaticamente) — focar nos módulos de lógica pura listados acima.

**Critério de aceite:** `pytest` roda localmente e no CI sem exigir um Redmine real ou
um provedor de LLM real; cobre pelo menos os pontos de risco tratados nos itens P0-3,
P1-1, P1-2 e P1-3.

---

## ✅ P1-5 — Extrair a camada de ações do assistente para fora de `app_flet.py`

**Problema:** `app_flet.py` é uma única classe `App` com 1537 linhas, misturando
construção de UI (Flet), estado de navegação e lógica de negócio (execução de ações no
Redmine/local). Isso dificulta testar a lógica de ações isoladamente (ver item P1-4) e
aumenta o custo de qualquer mudança futura na regra de negócio, porque ela está
entrelaçada com código de interface.

**Arquivos:** `app_flet.py` (métodos `_executar_acoes`, `_processar_acao`,
`_acao_local`, `_acao_redmine`, ~linhas 1113-1225).

**Passos:**
1. Criar um novo módulo `acoes.py` com uma classe `ExecutorDeAcoes` (ou funções livres)
   que recebem `api: RedmineAPI | None`, `config: dict` e a lista de ações, e
   implementam exatamente a lógica hoje em `_executar_acoes`/`_processar_acao`/
   `_acao_local`/`_acao_redmine` — sem nenhuma dependência de `ft`/Flet.
2. Em `app_flet.py`, `_executar_acoes` passa a apenas instanciar/chamar
   `acoes.ExecutorDeAcoes(...)` e traduzir o resultado para a UI (snackbar, mensagens
   no chat) — sem lógica de negócio residual.
3. Os testes do item P1-4 relativos a ações (se ainda não cobertos) passam a testar
   `acoes.py` diretamente, sem precisar instanciar `ft.Page`/Flet.

**Critério de aceite:** `acoes.py` não importa `flet`; `app_flet.py` reduz o tamanho
dos métodos relacionados a execução de ações para "cola" de UI; testes de ações rodam
sem inicializar uma `ft.Page`.

---

## ✅ P2-1 — Remover método morto `RedmineAPI.atividade_id`

**Problema:** `redmine_api.py` (linha 226-227) define
`def atividade_id(self, issue: dict) -> int: return issue["id"]`, que não é chamado em
nenhum lugar do repositório (confirmado via grep). O nome também é enganoso — parece
que devolveria o ID de uma *atividade de apontamento de horas*, mas na verdade devolve
o ID da *issue*.

**Arquivos:** `redmine_api.py` (linha ~226-227).

**Passos:**
1. Remover o método completamente (não é usado por nada).
2. Rodar `grep -rn "atividade_id" --include="*.py" .` de novo para confirmar que a
   única ocorrência restante é a variável local `atividade_id` em `app_flet.py`
   (linha ~622, sem relação com o método removido — é o valor selecionado no dropdown
   de atividade de apontamento).

**Critério de aceite:** método removido; `py_compile` de todos os módulos continua
passando; nenhuma referência quebrada.

---

## ✅ P2-2 — Esclarecer/remover dependência órfã `paramiko` em `requirements-dev.txt`

**Problema:** `requirements-dev.txt` lista `paramiko==5.0.0` com o comentário
`# Instalação de tema no servidor (script tarefa_64402/instalar_tema.py)`, mas esse
script não existe em nenhum lugar do repositório. Isso é uma dependência de build sem
uso aparente no código versionado, e vale confirmar se a versão `5.0.0` do paramiko de
fato existe no PyPI antes de qualquer `pip install -r requirements-dev.txt` (versões
recentes do paramiko na época deste projeto giravam em torno da série 3.x — um número
de versão inexistente quebraria a instalação).

**Arquivos:** `requirements-dev.txt`.

**Passos:**
1. Perguntar ao autor do repositório (não assumir) se o script
   `tarefa_64402/instalar_tema.py` existe fora deste repositório e ainda é usado; se
   sim, documentar isso claramente no `DEVELOP.md` ou mover para um repositório
   separado de scripts operacionais.
2. Se não for mais necessário, remover a linha de `requirements-dev.txt`.
3. Se for mantido, verificar a versão real disponível no PyPI (`pip index versions
   paramiko` ou consultar https://pypi.org/project/paramiko/) e corrigir o pin se
   `5.0.0` não existir.

**Critério de aceite:** `pip install -r requirements-dev.txt` funciona sem erro de
versão inexistente; a razão de cada dependência em `requirements-dev.txt` está
documentada ou o item foi removido.

---

## ✅ P2-3 — Padronizar tratamento de exceções amplas com logging

**Problema:** vários pontos usam `except Exception:` (por exemplo,
`atualizar_redmine.py` linha ~122, ao buscar cada issue: `except Exception: continue`)
sem registrar nada sobre o motivo da falha. No app compilado (`.exe` sem console —
`console=False` no `RedmineAssistant.spec`), isso significa que um erro inesperado é
completamente invisível ao usuário final, dificultando suporte/diagnóstico.

**Arquivos:** `atualizar_redmine.py` (~linha 120-123), demais blocos `except
Exception` em `app_flet.py` e scripts standalone.

**Passos:**
1. Adicionar um módulo simples `logger_app.py` usando `logging` da stdlib, gravando em
   um arquivo `app.log` ao lado do executável (reusar `paths.executavel_dir()`), com
   rotação simples (ex.: `logging.handlers.RotatingFileHandler`, 1MB, 3 backups).
2. Nos pontos onde hoje há `except Exception: continue` ou `except Exception: pass`
   silenciosos que escondem falhas reais (priorizar `atualizar_redmine.py` linha ~122
   e os blocos de `app_flet.py` que capturam erros de carregamento/execução de ações),
   adicionar `logger.exception(...)` antes de continuar/ignorar, mantendo o
   comportamento de não interromper o fluxo principal.
3. Não aplicar logging genérico em blocos que já reportam o erro adequadamente ao
   usuário (ex.: os `except Exception as ex: self.lbl_status_config.value = f"Erro:
   {ex}"` já mostram a mensagem na UI) — o foco é só nos pontos onde o erro hoje
   desaparece silenciosamente.

**Critério de aceite:** falhas hoje silenciosas (ex.: uma issue inexistente na
planilha) ficam registradas em `app.log` com o traceback completo, mesmo quando o
fluxo principal continua normalmente para o usuário.

---

## Ordem de execução recomendada

> **Situação atual: todos os itens concluídos** — a ordem abaixo foi usada para
> executar e rever cada item isoladamente (um commit por item em `main`).

1. P0-1 (`.gitignore`) — trivial, zero risco, faça primeiro. ✅
2. P0-3 (`activity_id`) — corretude de dados, isolado, baixo risco de quebrar outras
   partes. ✅
3. P0-2 (confirmação de ações da IA) — maior mudança de comportamento, mexe na UI;
   fazer depois de P0-3 porque reaproveita o mesmo caminho de execução de ações. ✅
4. P1-3 (deduplicar `_criar_api`) e P1-1 (vocabulário de status) — pequenas refatorações
   que preparam o terreno para P1-4 (testes). ✅
5. P1-2 (validação de data) — depende de P1-3 se `normalizar_data` for movida para
   `redmine_api.py` como sugerido. ✅
6. P1-5 (extrair `acoes.py`) — antes ou junto de P1-4, já que testar a lógica de ações
   fica mais fácil fora da classe `App`. ✅
7. P1-4 (testes) — depois das refatorações acima, para já testar a forma final do
   código. ✅
8. P2-1, P2-2, P2-3 — podem ser feitos a qualquer momento, são independentes entre si e
   de baixo risco. ✅
