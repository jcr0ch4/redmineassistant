"""Gerencia a configuração persistente do app (credenciais do Redmine e do LLM).

Salva em um arquivo JSON junto ao app (config.json). Permite que o usuário
defina a URL do Redmine, a API key, o provedor de LLM (Ollama, OpenAI, Claude,
Gemini, Kimi), modelo, chave de API, prompt system, parâmetros do modelo e
quais ferramentas (ações) o assistente pode usar.
"""

import json

from ferramentas import DEFAULT_HABILITADAS, TOOLS_POR_ID
from ollama_client import PROVIDERS
from paths import executavel_dir

BASE_DIR = executavel_dir()
CONFIG_FILE = BASE_DIR / "config.json"

DEFAULT_CONFIG = {
    "site": "",
    "login": "",
    "senha": "",
    "api_key": "",
    # LLM
    "llm_provider": "ollama",
    "ollama_url": "http://localhost:11434/api/chat",
    "ollama_model": "llama3.1:latest",
    "llm_api_key": "",
    "llm_url": "",
    "llm_model": "",
    "llm_temperature": 0.4,
    "llm_max_tokens": "",
    "llm_prompt_system": "",
    # Ferramentas do assistente (ações permitidas)
    "ferramentas_habilitadas": DEFAULT_HABILITADAS,
}


def _fabricar_config() -> dict:
    """Retorna a config padrão, com valores específicos do provedor selecionado."""
    cfg = dict(DEFAULT_CONFIG)
    prov = cfg.get("llm_provider", "ollama")
    meta = PROVIDERS.get(prov, PROVIDERS["ollama"])
    cfg["llm_url"] = meta["default_url"]
    cfg["llm_model"] = meta["default_model"]
    return cfg


def carregar_config() -> dict:
    config = _fabricar_config()
    dados_arquivo = {}
    if CONFIG_FILE.exists():
        try:
            dados_arquivo = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            config.update({k: v for k, v in dados_arquivo.items() if k in config})
        except (json.JSONDecodeError, OSError):
            pass
    _migrar_legado(config, dados_arquivo)
    _sanear_ferramentas(config)
    return config


def _sanear_ferramentas(config: dict) -> None:
    """Garante que ferramentas_habilitadas seja uma lista válida de IDs conhecidos."""
    lista = config.get("ferramentas_habilitadas") or DEFAULT_HABILITADAS
    if not isinstance(lista, list):
        lista = DEFAULT_HABILITADAS
    config["ferramentas_habilitadas"] = [i for i in lista if i in TOOLS_POR_ID] or list(DEFAULT_HABILITADAS)


def _migrar_legado(config: dict, dados_arquivo: dict) -> None:
    """Transfere valores das chaves antigas (ollama_url/ollama_model) para as novas (llm_*)
    quando o provedor for ollama e as novas chaves ainda não constarem no arquivo salvo."""
    if config.get("llm_provider") != "ollama":
        return
    if "llm_url" not in dados_arquivo and config.get("ollama_url"):
        config["llm_url"] = config["ollama_url"]
    if "llm_model" not in dados_arquivo and config.get("ollama_model"):
        config["llm_model"] = config["ollama_model"]


def salvar_config(config: dict) -> None:
    # garante que campos conhecidos existam, mesmo os que vierem sem valor
    dados = _fabricar_config()
    dados.update({k: v for k, v in config.items() if k in dados})
    _sanear_ferramentas(dados)
    CONFIG_FILE.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )
