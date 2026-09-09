"""Gerencia a configuração persistente do app (credenciais do Redmine e do LLM).

Salva em um arquivo JSON junto ao app (config.json). Permite que o usuário
defina a URL do Redmine, a API key, o provedor de LLM (Ollama, OpenAI, Claude,
Gemini, Kimi), modelo, chave de API, prompt system, parâmetros do modelo e
quais ferramentas (ações) o assistente pode usar.

As chaves de API (Redmine e LLM) são salvas com uma **ofuscação básica**
(base64 com marcador próprio). Não é criptografia forte — apenas evita que a
chave apareça em texto puro ao inspecionar o arquivo.
"""

import base64
import json

from ferramentas import DEFAULT_HABILITADAS, TOOLS_POR_ID
from ollama_client import PROVIDERS
from paths import executavel_dir

BASE_DIR = executavel_dir()
CONFIG_FILE = BASE_DIR / "config.json"

# Campos sensíveis que ficam ofuscados em base64 no arquivo
CAMPOS_PROTEGIDOS = ("api_key", "llm_api_key")
_PREFIXO = "b64:"

# Status de issue conhecidos (usado para sanear as colunas do kanban)
STATUS_VALIDOS = ["Nova", "Backlog", "Especificação", "Em andamento", "Validação", "Encerrada", "Cancelada", "Suspensa"]

# Quadro kanban padrão: cada coluna = {"titulo", "status": [...nomes...], "concluida": bool}.
# "concluida": True -> a coluna lista as atividades já fechadas da sprint selecionada.
DEFAULT_KANBAN_COLUNAS = [
    {"titulo": "Nova", "status": ["Nova"], "concluida": False},
    {"titulo": "Backlog", "status": ["Backlog"], "concluida": False},
    {"titulo": "Especificação", "status": ["Especificação"], "concluida": False},
    {"titulo": "Em andamento", "status": ["Em andamento"], "concluida": False},
    {"titulo": "Concluídas", "status": ["Encerrada"], "concluida": True},
]

DEFAULT_CONFIG = {
    "site": "",
    "api_key": "",
    # Depuração
    "debug": False,
    # Regras de atualização: o servidor pode bloquear o ajuste manual do % concluído.
    # Quando desativado, o app nunca envia done_ratio (o % só muda via regras do servidor).
    "atualizar_percentual": False,
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
    # Quadro kanban personalizado
    "kanban_colunas": [dict(c) for c in DEFAULT_KANBAN_COLUNAS],
    # Visualização e sprint da última sessão (persistidas para reabrir igual)
    "visualizacao": "lista",
    "kanban_sprint_id": "",
    # IA: sem confirmação, as ações que gravam no Redmine são exibidas para o
    # usuário confirmar antes de aplicar (proteção contra prompt injection).
    "assistente_auto_executar": False,
}


def _proteger(valor: str) -> str:
    """Ofusca uma chave para salvar no arquivo (base64 com marcador)."""
    if not valor:
        return ""
    try:
        codificado = base64.urlsafe_b64encode(str(valor).encode("utf-8")).decode("ascii")
    except (UnicodeError, ValueError):
        return str(valor)
    return _PREFIXO + codificado


def _desproteger(valor: str) -> str:
    """Recupera o texto original de uma chave salva (e dados legados sem marcador)."""
    if not valor:
        return ""
    if not isinstance(valor, str) or not valor.startswith(_PREFIXO):
        return valor  # config legado gravada em texto puro
    try:
        return base64.urlsafe_b64decode(valor[len(_PREFIXO):]).decode("utf-8")
    except (base64.binascii.Error, UnicodeError, ValueError):
        return valor


def _fabricar_config(provider: str | None = None) -> dict:
    """Retorna a config padrão, com valores específicos do provedor selecionado."""
    cfg = dict(DEFAULT_CONFIG)
    prov = (provider or cfg.get("llm_provider", "ollama")) or "ollama"
    meta = PROVIDERS.get(prov, PROVIDERS["ollama"])
    cfg["llm_url"] = meta["default_url"]
    cfg["llm_model"] = meta["default_model"]
    return cfg


def carregar_config() -> dict:
    dados_arquivo = {}
    if CONFIG_FILE.exists():
        try:
            dados_arquivo = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    config = _fabricar_config(provider=dados_arquivo.get("llm_provider"))
    config.update({k: v for k, v in dados_arquivo.items() if k in config})
    _migrar_legado(config, dados_arquivo)
    _sanear_ferramentas(config)
    _sanear_kanban(config)
    for campo in CAMPOS_PROTEGIDOS:
        config[campo] = _desproteger(config.get(campo, ""))
    return config


def _sanear_kanban(config: dict) -> None:
    """Garante que kanban_colunas seja uma lista válida de colunas com status conhecidos."""
    colunas = config.get("kanban_colunas")
    valido = isinstance(colunas, list) and colunas
    if not valido:
        config["kanban_colunas"] = [dict(c) for c in DEFAULT_KANBAN_COLUNAS]
        return
    novas = []
    for c in colunas:
        if not isinstance(c, dict):
            continue
        statuses = []
        vistos = set()
        for s in (c.get("status") or []):
            if s in STATUS_VALIDOS and s not in vistos:
                vistos.add(s)
                statuses.append(s)
        titulo = str(c.get("titulo") or "").strip() or ", ".join(statuses) or "Coluna"
        novas.append({"titulo": titulo, "status": statuses, "concluida": bool(c.get("concluida", False))})
    config["kanban_colunas"] = novas or [dict(c) for c in DEFAULT_KANBAN_COLUNAS]


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
    dados = _fabricar_config(provider=config.get("llm_provider"))
    dados.update({k: v for k, v in config.items() if k in dados})
    _sanear_ferramentas(dados)
    _sanear_kanban(dados)
    for campo in CAMPOS_PROTEGIDOS:
        dados[campo] = _proteger(dados.get(campo, ""))
    CONFIG_FILE.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )