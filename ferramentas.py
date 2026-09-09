"""Catálogo de ferramentas (ações) do assistente pessoal.

Cada ferramenta representa uma capacidade que o assistente pode executar no
Redmine (via REST API) ou localmente (SQLite). O usuário habilita/desabilita
as ferramentas na tela de Configuração, e apenas as habilitadas são enviadas
ao prompt da IA e executadas.

Estrutura de cada ferramenta:
  id: chave única usada no config e no formato de ação [EXECUTAR]
  nome: nome amigável exibido na UI
  descricao: o que a ferramenta faz (explicado à IA)
  categoria: "Redmine" (faz chamadas na API) ou "Local" (banco local SQLite)
  formato: exemplo de JSON que a IA deve retornar em format_actions
  requer_redmine: se precisa de conexão com o Redmine
  requer_confirmacao: se o app deve pedir confirmação do usuário antes de
    executar. True para ações que GRAVAM dado real no Redmine (proteção contra
    prompt injection em descrições de issues); False para ações locais
    (reversíveis) e para leitura pura (listar_atividades não altera nada).
"""


# ------------------------------------------------------------------ catálogo
TOOLS = [
    {
        "id": "lancar_horas",
        "nome": "Lançar horas",
        "descricao": "Registra apontamento de horas trabalhadas em uma atividade (time entry) no Redmine.",
        "categoria": "Redmine",
        "requer_redmine": True,
        "requer_confirmacao": True,
        "formato": (
            '{"acao": "lancar_horas", "dados": {"issue_id": <int>, "horas": <float>, '
            '"comentario": "<string>", "data": "<AAAA-MM-DD>", '
            '"atividade": "<opcional, nome da atividade de apontamento>"}} '
            '/* data opcional, default hoje; atividade opcional, default = atividade padrão do Redmine */'
        ),
    },
    {
        "id": "atualizar_status",
        "nome": "Alterar status",
        "descricao": "Muda o status de uma atividade (ex.: Nova, Em andamento, Encerrada).",
        "categoria": "Redmine",
        "requer_redmine": True,
        "requer_confirmacao": True,
        "formato": (
            '{"acao": "atualizar_status", "dados": {"issue_id": <int>, "status": "<nome do status>"}}'
        ),
    },
    {
        "id": "atualizar_percentual",
        "nome": "Atualizar % concluído",
        "descricao": "Define o percentual concluído de uma atividade (0 a 100).",
        "categoria": "Redmine",
        "requer_redmine": True,
        "requer_confirmacao": True,
        "formato": (
            '{"acao": "atualizar_percentual", "dados": {"issue_id": <int>, "percentual": <int 0-100>}}'
        ),
    },
    {
        "id": "atualizar_previsao",
        "nome": "Alterar data prevista",
        "descricao": "Altera a data prevista (due date) de uma atividade (AAAA-MM-DD).",
        "categoria": "Redmine",
        "requer_redmine": True,
        "requer_confirmacao": True,
        "formato": (
            '{"acao": "atualizar_previsao", "dados": {"issue_id": <int>, "data": "<AAAA-MM-DD>"}}'
        ),
    },
    {
        "id": "atualizar_prioridade",
        "nome": "Alterar prioridade",
        "descricao": "Altera a prioridade da atividade no Redmine (ex.: Baixa, Normal, Alta, Urgente).",
        "categoria": "Redmine",
        "requer_redmine": True,
        "requer_confirmacao": True,
        "formato": (
            '{"acao": "atualizar_prioridade", "dados": {"issue_id": <int>, "prioridade": "<nome>"}}'
        ),
    },
    {
        "id": "adicionar_comentario",
        "nome": "Adicionar comentário",
        "descricao": "Adiciona um comentário/nota na atividade no Redmine.",
        "categoria": "Redmine",
        "requer_redmine": True,
        "requer_confirmacao": True,
        "formato": (
            '{"acao": "adicionar_comentario", "dados": {"issue_id": <int>, "comentario": "<texto>"}}'
        ),
    },
    {
        "id": "definir_prioridade",
        "nome": "Organizar prioridade (local)",
        "descricao": "Organiza a lista de atividades por importância em ordem personalizada (armazenada localmente).",
        "categoria": "Local",
        "requer_redmine": False,
        "requer_confirmacao": False,
        "formato": (
            '{"acao": "definir_prioridade", "dados": {"issue_ids": [<int>, ...], '
            '"nota": "<justificativa curta>"}} /* primeiro é o mais importante */'
        ),
    },
    {
        "id": "salvar_nota",
        "nome": "Salvar anotação (local)",
        "descricao": "Guarda uma anotação pessoal sobre uma atividade (armazenada localmente).",
        "categoria": "Local",
        "requer_redmine": False,
        "requer_confirmacao": False,
        "formato": (
            '{"acao": "salvar_nota", "dados": {"issue_id": <int>, "nota": "<texto>"}}'
        ),
    },
    {
        "id": "listar_atividades",
        "nome": "Listar atividades",
        "descricao": "Busca atividades no Redmine por status, prioridade ou palavra-chave no assunto.",
        "categoria": "Redmine",
        "requer_redmine": True,
        "requer_confirmacao": False,  # leitura (GET) — não grava nada no Redmine
        "formato": (
            '{"acao": "listar_atividades", "dados": {"status": "<opcional>", '
            '"prioridade": "<opcional>", "termo": "<opcional>"}}'
        ),
    },
]

TOOLS_POR_ID = {t["id"]: t for t in TOOLS}
DEFAULT_HABILITADAS = [t["id"] for t in TOOLS]


def categorias() -> list[str]:
    """Lista as categorias em ordem de exibição."""
    ordem = ["Redmine", "Local"]
    return [c for c in ordem if any(t["categoria"] == c for t in TOOLS)]


def ferramentas_por_categoria() -> dict[str, list]:
    grupo: dict[str, list] = {c: [] for c in categorias()}
    for t in TOOLS:
        grupo[t["categoria"]].append(t)
    return grupo


def formatos_habilitados(habitadas: list[str]) -> str:
    """Retorna o bloco de texto com os formatos das ferramentas habilitadas."""
    selecionadas = [t for t in TOOLS if t["id"] in (habitadas or DEFAULT_HABILITADAS)]
    if not selecionadas:
        return "Nenhuma ferramenta habilitada. Apenas converse."
    return "\n".join(f"- {t['formato']}" for t in selecionadas)


def descricao_habilitadas(habitadas: list[str]) -> str:
    """Retorna descrição resumida das ferramentas habilitadas para a IA saber para que servem."""
    selecionadas = [t for t in TOOLS if t["id"] in (habitadas or DEFAULT_HABILITADAS)]
    if not selecionadas:
        return ""
    return "\n".join(f"- {t['id']}: {t['descricao']}" for t in selecionadas)


def requer_confirmacao(acao: str) -> bool:
    """Diz se uma ação precisa de confirmação do usuário antes de ser executada."""
    tool = TOOLS_POR_ID.get(acao or "")
    return bool(tool and tool.get("requer_confirmacao", False))