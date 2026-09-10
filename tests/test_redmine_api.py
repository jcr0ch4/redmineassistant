"""Testes de redmine_api.py (integração com a REST API do Redmine).

Não toca em um Redmine real: usa pytest e sobrescreve requests/métodos de
rede vias `monkeypatch`. Foco em funções puras e lógica de resolução de
atividade padrão.
"""

import pytest

from redmine_api import RedmineAPI, normalizar_data


# ------------------------------------------------------------ normalizar_data
@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("2026-09-30", "2026-09-30"),
        ("30/09/2026", "2026-09-30"),
        ("30/09/26", "2026-09-30"),
        ("15-08-2025", None),  # formato não reconhecido
        ("texto inválido", None),
        ("", None),
        (None, None),
    ],
)
def test_normalizar_data(entrada, esperado):
    resultado = normalizar_data(entrada)
    assert resultado == esperado


def test_normalizar_data_aceita_date():
    from datetime import date

    assert normalizar_data(date(2025, 11, 3)) == "2025-11-03"


# ------------------------------------------------------------ atividade padrão
class _FakeAtividades:
    """Simula uma API que retorna a lista de atividades de apontamento."""

    def __init__(self, atividades):
        self._atividades = atividades
        self.chamadas = 0

    def get_time_entry_activities(self):
        self.chamadas += 1
        return list(self._atividades)


def _api_do_fake(fake):
    api = RedmineAPI.__new__(RedmineAPI)
    api._atividade_id_padrao = None
    api.get_time_entry_activities = fake.get_time_entry_activities
    return api


def test_atividade_padrao_prefere_desenvolvimento():
    fake = _FakeAtividades(
        [
            {"id": 5, "name": "Reunião", "active": True},
            {"id": 9, "name": "Desenvolvimento", "active": True},
            {"id": 12, "name": "Planejamento", "active": True},
        ]
    )
    api = _api_do_fake(fake)
    assert api.get_activity_id_padrao() == 9
    assert api.get_activity_id_padrao() == 9  # cacheado sem nova chamada
    assert fake.chamadas == 1


def test_atividade_padrao_usa_primeira_quando_sem_desenvolvimento():
    fake = _FakeAtividades([{"id": 3, "name": "Suporte", "active": True}])
    api = _api_do_fake(fake)
    assert api.get_activity_id_padrao() == 3


def test_atividade_padrao_none_quando_vazio():
    fake = _FakeAtividades([])
    api = _api_do_fake(fake)
    assert api.get_activity_id_padrao() is None


# ------------------------------------------------------------ _ler_credenciais
def test_ler_credenciais_case_insensitive(tmp_path, monkeypatch):
    import redmine_api as rm

    arquivo = tmp_path / "credenciais.txt"
    arquivo.write_text(
        "SITE: https://redmine.exemplo.com/\n"
        "Login: usuario\n"
        "Senha: 1234\n"
        "API-access-key: chave-123\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rm, "CREDENCIAIS_FILE", arquivo)
    creds = rm._ler_credenciais()
    assert creds["site"] == "https://redmine.exemplo.com"
    assert creds["login"] == "usuario"
    assert creds["senha"] == "1234"
    assert creds["api_key"] == "chave-123"


def test_ler_credenciais_sem_site_ou_key_levanta(tmp_path, monkeypatch):
    import redmine_api as rm

    arquivo = tmp_path / "credenciais.txt"
    arquivo.write_text("login: alguem\n", encoding="utf-8")
    monkeypatch.setattr(rm, "CREDENCIAIS_FILE", arquivo)
    with pytest.raises(ValueError):
        rm._ler_credenciais()


def test_ler_credenciais_arquivo_inexistente(tmp_path, monkeypatch):
    import redmine_api as rm

    arquivo = tmp_path / "nao_existe.txt"
    monkeypatch.setattr(rm, "CREDENCIAIS_FILE", arquivo)
    with pytest.raises(FileNotFoundError):
        rm._ler_credenciais()