"""Log de depuração das interações entre o app, a IA e o Redmine.

Quando o modo debug está habilitado na tela de Configuração, as requisições
ao LLM e à API do Redmine (e o resultado/ações executadas) são gravadas em
linhas JSON no arquivo ``debug.log``, criado ao lado do executável/projeto.

O log só grava quando ``habilitar(True)`` foi chamado (o app chama ao carregar
e ao salvar a configuração). Os módulos de integração apenas registram os
eventos — nunca bloqueiam o fluxo normal.
"""

import json
import threading
from datetime import datetime

from paths import executavel_dir

LOG_FILE = executavel_dir() / "debug.log"

_TRAVA = threading.Lock()
_HABILITADO = False
_MAX_STR = 4000  # tamanho máximo por campo de texto no log


def habilitar(valor: bool = True) -> None:
    """Liga ou desliga o registro de depuração (thread-safe)."""
    global _HABILITADO
    _HABILITADO = bool(valor)


def ativo() -> bool:
    return _HABILITADO


def log(evento: str, **campos) -> None:
    """Grava uma linha JSON no log de depuração — no-op quando desabilitado."""
    if not _HABILITADO:
        return
    dados = {"ts": datetime.now().isoformat(timespec="seconds"), "evento": evento}
    for chave, valor in campos.items():
        if isinstance(valor, str) and len(valor) > _MAX_STR:
            valor = valor[:_MAX_STR] + "…[truncado]"
        dados[chave] = valor
    linha = json.dumps(dados, ensure_ascii=False, default=str)
    with _TRAVA:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(linha + "\n")
        except OSError:
            pass


def limpar() -> None:
    """Apaga o arquivo de log (usado no começo de uma sessão de debug)."""
    with _TRAVA:
        try:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write("")
        except OSError:
            pass