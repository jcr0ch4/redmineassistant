"""Resolução de caminhos compatível com modo compilado (PyInstaller).

Em modo dev, os arquivos de dados (config.json, assistente_local.db, etc.)
ficam na pasta do projeto. Quando o app é compilado com `flet pack`
(PyInstaller --onefile), ``__file__`` aponta para o diretório temporário de
extração (_MEIPASS), que é apagado ao fechar o app — os dados seriam perdidos.

Nesse caso usamos o diretório do executável (sys.executable), deixando os
arquivos persistentes ao lado do executável.
"""

import sys
from pathlib import Path


def executavel_dir() -> Path:
    """Diretório de dados persistente do app (dev ou compilado)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent