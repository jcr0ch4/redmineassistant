"""Testes de config_manager.py (leitura/gravação da config persistente).

Isoleia o arquivo CONFIG_FILE em tmp_path para não tocar no config.json real
do projeto (que contém credenciais do usuário).
"""

import json

import pytest

import config_manager as cm
from ferramentas import DEFAULT_HABILITADAS


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    caminho = tmp_path / "config.json"
    monkeypatch.setattr(cm, "CONFIG_FILE", caminho)
    return caminho


def test_config_padrao_quando_arquivo_inexistente(config_file):
    cfg = cm.carregar_config()
    assert cfg["site"] == ""
    assert cfg["api_key"] == ""
    assert cfg["llm_provider"] == "ollama"
    assert cfg["assistente_auto_executar"] is False
    assert cfg["ferramentas_habilitadas"] == DEFAULT_HABILITADAS


def test_config_padrao_quando_arquivo_corrompido(config_file):
    config_file.write_text("{json inválido", encoding="utf-8")
    cfg = cm.carregar_config()
    assert cfg["site"] == ""
    assert cfg["ferramentas_habilitadas"] == DEFAULT_HABILITADAS


def test_migra_legado_ollama_para_llm(config_file):
    config_file.write_text(
        json.dumps(
            {
                "llm_provider": "ollama",
                "ollama_url": "http://localhost:11434/api/chat",
                "ollama_model": "llama3.1:latest",
            }
        ),
        encoding="utf-8",
    )
    cfg = cm.carregar_config()
    assert cfg["llm_url"] == "http://localhost:11434/api/chat"
    assert cfg["llm_model"] == "llama3.1:latest"


def test_sanear_ferramentas_descarta_ids_desconhecidos(config_file):
    config_file.write_text(
        json.dumps({"ferramentas_habilitadas": ["lancar_horas", "ferramenta_inexistente"]}),
        encoding="utf-8",
    )
    cfg = cm.carregar_config()
    assert cfg["ferramentas_habilitadas"] == ["lancar_horas"]


def test_sanear_ferramentas_valor_nao_lista_usar_default(config_file):
    config_file.write_text(json.dumps({"ferramentas_habilitadas": "lancar_horas"}), encoding="utf-8")
    cfg = cm.carregar_config()
    assert cfg["ferramentas_habilitadas"] == DEFAULT_HABILITADAS


def test_apikey_fica_ofuscada_no_arquivo(config_file):
    cfg = cm.carregar_config()
    cfg["api_key"] = "chave-secreta-123"
    cfg["llm_api_key"] = "llm-secret"
    cm.salvar_config(cfg)

    dados_arquivo = json.loads(config_file.read_text(encoding="utf-8"))
    assert dados_arquivo["api_key"].startswith(cm._PREFIXO)
    assert "chave-secreta-123" not in config_file.read_text(encoding="utf-8")

    recarregado = cm.carregar_config()
    assert recarregado["api_key"] == "chave-secreta-123"
    assert recarregado["llm_api_key"] == "llm-secret"


def test_apikey_legada_em_texto_puro_continua_funcionando(config_file):
    config_file.write_text(json.dumps({"api_key": "texto-puro"}), encoding="utf-8")
    cfg = cm.carregar_config()
    assert cfg["api_key"] == "texto-puro"