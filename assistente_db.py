"""Armazenamento local (SQLite) do assistente pessoal.

Guarda:
  - histórico de conversas com o assistente
  - ordem de prioridade personalizada das atividades (organizada por prioridade)
  - anotações/observações feitas pelo usuário em cada atividade

Usa Python puro (módulo `sqlite3`), sem dependências externas.
"""

import sqlite3
import threading
import uuid
from datetime import datetime

from paths import executavel_dir

BASE_DIR = executavel_dir()
DB_FILE = BASE_DIR / "assistente_local.db"

_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contexto TEXT NOT NULL DEFAULT 'geral',
    autor TEXT NOT NULL,
    conteudo TEXT NOT NULL,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversacoes (
    contexto TEXT PRIMARY KEY,
    titulo TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prioridades (
    issue_id INTEGER PRIMARY KEY,
    prioridade INTEGER NOT NULL DEFAULT 100,
    nota TEXT NOT NULL DEFAULT '',
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notas (
    issue_id INTEGER PRIMARY KEY,
    nota TEXT NOT NULL DEFAULT '',
    atualizado_em TEXT NOT NULL
);
"""


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def inicializar():
    with _LOCK:
        con = _conectar()
        try:
            con.executescript(_SCHEMA)
            con.commit()
        finally:
            con.close()


def _garantir_conversa_inicial():
    """Garante ao menos uma conversa na tabela conversacoes.

    Migra o histórico legado gravado sob o contexto 'geral' (antes do suporte
    a múltiplas conversas), usando como título a primeira mensagem do usuário.
    """
    with _LOCK:
        con = _conectar()
        try:
            qtde = con.execute("SELECT COUNT(*) FROM conversacoes").fetchone()[0]
            if qtde > 0:
                return
            titulo = "Conversa"
            primeira = con.execute(
                "SELECT conteudo FROM conversas WHERE contexto='geral' AND autor='você' "
                "ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if primeira:
                titulo = " ".join(primeira["conteudo"].strip().split())[:40]
            con.execute(
                "INSERT OR IGNORE INTO conversacoes (contexto, titulo, criado_em, atualizado_em) "
                "VALUES ('geral', ?, ?, ?)",
                (titulo, _agora(), _agora()),
            )
            con.commit()
        finally:
            con.close()


inicializar()
_garantir_conversa_inicial()


# ---------------------------------------------------------------- conversas (múltiplas)
def listar_conversas() -> list[dict]:
    """Lista as conversas por atividade recente, com título e nº de mensagens."""
    with _LOCK:
        con = _conectar()
        try:
            linhas = con.execute(
                "SELECT c.contexto, c.titulo, c.criado_em, c.atualizado_em, "
                "(SELECT COUNT(*) FROM conversas m WHERE m.contexto = c.contexto) AS mensagens "
                "FROM conversacoes c ORDER BY c.atualizado_em DESC"
            ).fetchall()
            return [dict(r) for r in linhas]
        finally:
            con.close()


def criar_conversa(contexto: str | None = None, titulo: str = "Nova conversa") -> str:
    """Cria uma conversa e retorna seu contexto (chave)."""
    if not contexto:
        contexto = f"c-{uuid.uuid4().hex[:8]}"
    with _LOCK:
        con = _conectar()
        try:
            con.execute(
                "INSERT OR IGNORE INTO conversacoes (contexto, titulo, criado_em, atualizado_em) "
                "VALUES (?, ?, ?, ?)",
                (contexto, titulo, _agora(), _agora()),
            )
            con.commit()
            return contexto
        finally:
            con.close()


def renomear_conversa(contexto: str, titulo: str) -> None:
    with _LOCK:
        con = _conectar()
        try:
            con.execute(
                "UPDATE conversacoes SET titulo=?, atualizado_em=? WHERE contexto=?",
                (titulo, _agora(), contexto),
            )
            con.commit()
        finally:
            con.close()


def excluir_conversa(contexto: str) -> None:
    with _LOCK:
        con = _conectar()
        try:
            con.execute("DELETE FROM conversas WHERE contexto=?", (contexto,))
            con.execute("DELETE FROM conversacoes WHERE contexto=?", (contexto,))
            con.commit()
        finally:
            con.close()


# ---------------------------------------------------------------- conversas
def salvar_mensagem(autor: str, conteudo: str, contexto: str = "geral") -> None:
    with _LOCK:
        con = _conectar()
        try:
            con.execute(
                "INSERT INTO conversas (contexto, autor, conteudo, criado_em) VALUES (?,?,?,?)",
                (contexto, autor, conteudo, _agora()),
            )
            criado = _agora()
            con.execute(
                "UPDATE conversacoes SET atualizado_em=? WHERE contexto=?",
                (criado, contexto),
            )
            if autor == "você":
                contagem = con.execute(
                    "SELECT COUNT(*) FROM conversas WHERE contexto=?", (contexto,)
                ).fetchone()[0]
                if contagem == 1:
                    titulo = " ".join(conteudo.strip().split())[:40]
                    con.execute(
                        "UPDATE conversacoes SET titulo=? WHERE contexto=?",
                        (titulo, contexto),
                    )
            con.commit()
        finally:
            con.close()


def historico(contexto: str = "geral", limite: int = 50) -> list[dict]:
    with _LOCK:
        con = _conectar()
        try:
            linhas = con.execute(
                "SELECT autor, conteudo, criado_em FROM conversas "
                "WHERE contexto=? ORDER BY id DESC LIMIT ?",
                (contexto, limite),
            ).fetchall()
            return [dict(r) for r in reversed(linhas)]
        finally:
            con.close()


def limpar_historico(contexto: str = "geral") -> int:
    with _LOCK:
        con = _conectar()
        try:
            cur = con.execute("DELETE FROM conversas WHERE contexto=?", (contexto,))
            con.commit()
            return cur.rowcount
        finally:
            con.close()


# ---------------------------------------------------------------- prioridades
def salvar_prioridade(issue_id: int, prioridade: int, nota: str = "") -> None:
    with _LOCK:
        con = _conectar()
        try:
            con.execute(
                "INSERT INTO prioridades (issue_id, prioridade, nota, atualizado_em) "
                "VALUES (?,?,?,?) "
                "ON CONFLICT(issue_id) DO UPDATE SET prioridade=excluded.prioridade, "
                "nota=excluded.nota, atualizado_em=excluded.atualizado_em",
                (issue_id, int(prioridade), nota or "", _agora()),
            )
            con.commit()
        finally:
            con.close()


def definir_prioridade_ordem(issue_ids: list[int], nota: str = "") -> None:
    """Define a ordem de prioridade a partir de uma lista ordenada (primeiro = mais prioritário)."""
    for posicao, iid in enumerate(issue_ids):
        salvar_prioridade(iid, posicao, nota)


def prioridades() -> dict[int, dict]:
    with _LOCK:
        con = _conectar()
        try:
            linhas = con.execute(
                "SELECT issue_id, prioridade, nota, atualizado_em FROM prioridades ORDER BY prioridade ASC"
            ).fetchall()
            return {r["issue_id"]: dict(r) for r in linhas}
        finally:
            con.close()


def limpar_prioridades() -> None:
    with _LOCK:
        con = _conectar()
        try:
            con.execute("DELETE FROM prioridades")
            con.commit()
        finally:
            con.close()


# ---------------------------------------------------------------- notas
def salvar_nota(issue_id: int, nota: str) -> None:
    with _LOCK:
        con = _conectar()
        try:
            con.execute(
                "INSERT INTO notas (issue_id, nota, atualizado_em) VALUES (?,?,?) "
                "ON CONFLICT(issue_id) DO UPDATE SET nota=excluded.nota, atualizado_em=excluded.atualizado_em",
                (issue_id, nota, _agora()),
            )
            con.commit()
        finally:
            con.close()


def notas() -> dict[int, str]:
    with _LOCK:
        con = _conectar()
        try:
            linhas = con.execute("SELECT issue_id, nota FROM notas").fetchall()
            return {r["issue_id"]: r["nota"] for r in linhas}
        finally:
            con.close()
