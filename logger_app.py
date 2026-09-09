"""Logging padronizado da aplicação em um arquivo ``app.log``.

Usa ``logging`` da stdlib com rotação simples, gravando ao lado do executável
(reutiliza ``paths.executavel_dir()`` — no build compilado, onde o console fica
escondido, esse registro é a única forma de diagnosticar falhas silenciosas).
"""

import logging
from logging.handlers import RotatingFileHandler

from paths import executavel_dir

LOGGER_NAME = "redmineassistant"


def _configurar() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, "_configurado", False):
        return logger
    logger.setLevel(logging.DEBUG)
    caminho = executavel_dir() / "app.log"
    handler = RotatingFileHandler(
        caminho, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger._configurado = True  # evita reconfigurar handlers em múltiplas importações
    return logger


def get_logger(nome: str | None = None) -> logging.Logger:
    """Retorna o logger do app (ou um filho nomeado, ex.: "acoes")."""
    logger = _configurar()
    return logger.getChild(nome) if nome else logger