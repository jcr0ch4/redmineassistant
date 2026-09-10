"""Testes de assistente_db.py (armazenamento local SQLite).

Isoleia o banco em um arquivo temporário via monkeypatch de DB_FILE para
não tocar no assistente_local.db real do projeto.
"""

import pytest

import assistente_db as adb


@pytest.fixture
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "teste.db"
    monkeypatch.setattr(adb, "DB_FILE", caminho)
    adb.inicializar()
    adb._garantir_conversa_inicial()
    return caminho


def test_salvar_e_listar_nota(banco):
    assert adb.notas() == {}
    adb.salvar_nota(123, "Fazer migrate depois")
    assert adb.notas()[123] == "Fazer migrate depois"
    adb.salvar_nota(123, "Atualizado")
    assert adb.notas()[123] == "Atualizado"


def test_prioridade_ordem(banco):
    adb.definir_prioridade_ordem([10, 20, 30], nota="prioridade do sprint")
    prioridades = adb.prioridades()
    assert [prioridades[i]["prioridade"] for i in (10, 20, 30)] == [0, 1, 2]
    assert prioridades[10]["nota"] == "prioridade do sprint"


def test_salvar_e_ler_historico(banco):
    adb.salvar_mensagem("você", "O que tenho para hoje?", "c1")
    adb.salvar_mensagem("assistente", "Você tem 3 atividades.", "c1")
    hist = adb.historico("c1")
    assert [h["autor"] for h in hist] == ["você", "assistente"]
    assert hist[0]["conteudo"] == "O que tenho para hoje?"


def test_limpar_historico(banco):
    adb.salvar_mensagem("você", "msg1", "c2")
    adb.salvar_mensagem("você", "msg2", "c2")
    assert adb.limpar_historico("c2") == 2
    assert adb.historico("c2") == []