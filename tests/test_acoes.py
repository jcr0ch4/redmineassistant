"""Testes de acoes.py (execução das ações do assistente, lógica pura).

Cobre a validação de data das ações lancar_horas/atualizar_previsao e a regra
de não alterar % concluído quando a opção de permissão está desligada.
Não inicializa nenhuma ft.Page.
"""

import acoes


class _FakeSemApi:
    """Dublê que registra chamadas em vez de fazer HTTP."""

    def __init__(self):
        self.chamadas = []

    def get_time_entry_activities(self):
        return [{"id": 9, "name": "Desenvolvimento", "active": True}]

    def get_issue_priorities(self):
        return [{"id": 4, "name": "Alta", "active": True}, {"id": 5, "name": "Urgente", "active": True}]

    def lancar_horas(self, issue_id, horas, comentario, data, activity_id=None):
        self.chamadas.append(("lancar_horas", issue_id, horas, comentario, data, activity_id))
        return None

    def atualizar_issue(self, issue_id, **campos):
        self.chamadas.append(("atualizar_issue", issue_id, dict(campos)))
        return None

    def atualizar_status(self, issue_id, status):
        self.chamadas.append(("atualizar_status", issue_id, status))
        return None

    def get_issues_ativas(self):
        return []


def _executor(config=None):
    c = dict(config or {})
    c.setdefault("ferramentas_habilitadas", [
        "lancar_horas", "atualizar_status", "atualizar_percentual",
        "atualizar_previsao", "atualizar_prioridade", "adicionar_comentario",
        "definir_prioridade", "salvar_nota", "listar_atividades",
    ])
    c.setdefault("atualizar_percentual", True)
    return acoes.ExecutorDeAcoes(c, _FakeSemApi(), issues=[])


def test_data_ivalida_no_lancamento_nao_chama_api():
    ex = _executor()
    relatorio = ex.executar([
        {"acao": "lancar_horas", "dados": {"issue_id": 1, "horas": 2, "data": "próxima sexta"}}
    ])
    assert "use AAAA-MM-DD" in relatorio
    assert ex.api.chamadas == []


def test_data_ivalida_na_previsao_nao_chama_api():
    ex = _executor()
    relatorio = ex.executar([
        {"acao": "atualizar_previsao", "dados": {"issue_id": 1, "data": "próxima sexta"}}
    ])
    assert "use AAAA-MM-DD" in relatorio
    assert ex.api.chamadas == []


def test_lancamento_com_atividade_por_nome():
    ex = _executor()
    relatorio = ex.executar([
        {"acao": "lancar_horas", "dados": {"issue_id": 1, "horas": 1.5, "data": "2026-09-30", "atividade": "Desenvolvimento"}}
    ])
    assert ex.api.chamadas[0][0] == "lancar_horas"
    assert ex.api.chamadas[0][5] == 9  # activity_id resolvido por nome
    assert "Lançadas 1.5h" in relatorio


def test_percentual_ignorado_quando_desligado():
    ex = acoes.ExecutorDeAcoes(_config_com_pct(False), _FakeSemApi(), issues=[])
    relatorio = ex.executar([
        {"acao": "atualizar_percentual", "dados": {"issue_id": 1, "percentual": 50}}
    ])
    assert "desabilitada" in relatorio
    assert ex.api.chamadas == []


def test_acesso_redmine_quando_nao_configurado_retorna_aviso():
    # api criada a partir de config vazia -> None -> aviso, sem exceção
    c = {"ferramentas_habilitadas": ["lancar_horas"], "atualizar_percentual": True}
    ex = acoes.ExecutorDeAcoes(c, None, issues=[])
    relatorio = ex.executar([{"acao": "lancar_horas", "dados": {"issue_id": 1, "horas": 1}}])
    assert "Não configurado" in relatorio


def _config_com_pct(permitido):
    c = {
        "ferramentas_habilitadas": [
            "lancar_horas", "atualizar_status", "atualizar_percentual",
            "atualizar_previsao", "atualizar_prioridade", "adicionar_comentario",
            "definir_prioridade", "salvar_nota", "listar_atividades",
        ],
        "atualizar_percentual": permitido,
    }
    return c