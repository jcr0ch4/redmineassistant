"""Módulo compartilhado de integração com o Redmine via REST API.

Usado pelos scripts de download, atualização da planilha e pelo app Flet.
Lê as credenciais do arquivo credenciais.txt por padrão, mas também aceita
credenciais customizadas (site, login, senha, api_key) informadas via
parâmetros — usadas pela tela de configuração do app.
"""

import json
import re

import requests

from paths import executavel_dir

BASE_DIR = executavel_dir()
CREDENCIAIS_FILE = BASE_DIR / "credenciais.txt"

STATUS_ATIVOS = {"Nova", "Em andamento", "Backlog", "Especificação"}


def _ler_credenciais() -> dict:
    """Lê o arquivo credenciais.txt e retorna site, login, senha e api_key."""
    if not CREDENCIAIS_FILE.exists():
        raise FileNotFoundError(f"Arquivo de credenciais não encontrado: {CREDENCIAIS_FILE}")

    creds = {}
    for linha in CREDENCIAIS_FILE.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        m = re.match(r"^\s*([^:]+)\s*:\s*(.*)$", linha)
        if not m:
            continue
        chave, valor = m.group(1).strip().lower(), m.group(2).strip()
        if "site" in chave:
            creds["site"] = valor.rstrip("/")
        elif "login" in chave:
            creds["login"] = valor
        elif "senha" in chave or "password" in chave:
            creds["senha"] = valor
        elif "api" in chave and "key" in chave:
            creds["api_key"] = valor

    if not creds.get("site") or not creds.get("api_key"):
        raise ValueError("credenciais.txt deve conter 'site' e 'API-access-key'.")

    return creds


class RedmineAPI:
    """Cliente simples da REST API do Redmine.

    Por padrão lê as credenciais do arquivo credenciais.txt. Para usar
    credenciais customizadas, passe o dicionário ``credenciais`` com as
    chaves ``site``, ``api_key``, ``login``/``senha``.
    """

    def __init__(self, credenciais: dict | None = None):
        if credenciais:
            creds = credenciais
        else:
            creds = _ler_credenciais()

        site = (creds.get("site") or "").strip().rstrip("/")
        api_key = (creds.get("api_key") or "").strip()
        if not site or not api_key:
            raise ValueError("É necessário informar 'site' e 'API-access-key'.")

        self.site = site
        self.api_key = api_key
        self.login = creds.get("login")
        self.senha = creds.get("senha")
        self.headers = {
            "X-Redmine-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        self.usuario = None

    def definir_credenciais(self, site: str, api_key: str, login: str = "", senha: str = ""):
        """Atualiza as credenciais em runtime (usado pela tela de configuração)."""
        self.site = (site or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.login = login
        self.senha = senha
        self.headers = {
            "X-Redmine-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        self.usuario = None

    def _url(self, path: str) -> str:
        return f"{self.site}{path}"

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = requests.get(self._url(path), headers=self.headers, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, payload: dict) -> requests.Response:
        resp = requests.put(
            self._url(path), headers=self.headers, data=json.dumps(payload), timeout=60
        )
        resp.raise_for_status()
        return resp

    def _post(self, path: str, payload: dict) -> requests.Response:
        resp = requests.post(
            self._url(path), headers=self.headers, data=json.dumps(payload), timeout=60
        )
        resp.raise_for_status()
        return resp

    def get_usuario_atual(self) -> dict:
        """Retorna o usuário autenticado pela API key."""
        if self.usuario is None:
            data = self._get("/users/current.json")
            self.usuario = data.get("user", {})
        return self.usuario

    def get_issues_atribuidas(self, status_id="*") -> list[dict]:
        """Baixa todas as issues atribuídas ao usuário atual."""
        usuario = self.get_usuario_atual()
        user_id = usuario.get("id")
        todas = []
        offset = 0
        limite = 100
        while True:
            params = {
                "assigned_to_id": user_id,
                "status_id": status_id,
                "limit": limite,
                "offset": offset,
            }
            data = self._get("/issues.json", params=params)
            issues = data.get("issues", [])
            todas.extend(issues)
            if len(issues) < limite:
                break
            offset += limite
            total = data.get("total_count")
            # total_count pode vir como None em algumas versões do Redmine
            if total is not None and offset >= total:
                break
        return todas

    def get_issues_ativas(self) -> list[dict]:
        """Baixa apenas as issues em status ativo (Nova, Em andamento, Backlog, Especificação).

        Usa o filtro de servidor ``status_id=open`` (muito menor que ``*``, que
        baixaria todas as issues inclusive as encerradas) e depois filtra
        localmente pelos status ativos. Isso evita download massivo/erros de
        timeout para usuários com muitas issues atribuídas.
        """
        abertas = self.get_issues_atribuidas(status_id="open")
        return [i for i in abertas if i.get("status", {}).get("name") in STATUS_ATIVOS]

    def get_issue(self, issue_id: int) -> dict:
        """Retorna uma issue individual pelo ID."""
        data = self._get(f"/issues/{issue_id}.json")
        return data.get("issue", {})

    def get_status_ids(self) -> dict:
        """Retorna mapeamento nome -> id de todos os status."""
        data = self._get("/issue_statuses.json", params={"limit": 100})
        return {s["name"]: s["id"] for s in data.get("issue_statuses", [])}

    def get_versions(self, project_id: int) -> list[dict]:
        """Lista as versões/sprints de um projeto."""
        data = self._get(f"/projects/{project_id}/versions.json", params={"limit": 100})
        return data.get("versions", [])

    def get_time_entry_activities(self) -> list[dict]:
        """Lista as atividades possíveis para apontamento de horas."""
        data = self._get("/enumerations/time_entry_activities.json")
        return [a for a in data.get("time_entry_activities", []) if a.get("active")]

    def get_issue_priorities(self) -> list[dict]:
        """Lista as prioridades de issue configuradas no Redmine (ex.: Baixa, Normal, Alta, Urgente)."""
        data = self._get("/enumerations/issue_priorities.json", params={"limit": 100})
        return [p for p in data.get("issue_priorities", []) if p.get("active")]

    def get_projects(self) -> list[dict]:
        """Lista os projetos visíveis ao usuário."""
        data = self._get("/projects.json", params={"limit": 100})
        return data.get("projects", [])

    def get_trackers(self) -> list[dict]:
        """Lista os trackers configurados no Redmine."""
        data = self._get("/trackers.json", params={"limit": 100})
        return data.get("trackers", [])

    def adicionar_comentario(self, issue_id: int, comentario: str) -> requests.Response:
        """Adiciona um comentário/journal a uma issue (campo notes)."""
        return self.atualizar_issue(issue_id, notes=comentario)

    def atualizar_issue(self, issue_id: int, **campos) -> requests.Response:
        """Atualiza campos de uma issue. Campos válidos: status, done_ratio, due_date etc."""
        payload = {"issue": campos}
        return self._put(f"/issues/{issue_id}.json", payload)

    def atualizar_status(self, issue_id: int, status_name: str) -> requests.Response:
        """Muda o status de uma issue pelo nome."""
        status_ids = self.get_status_ids()
        status_id = status_ids.get(status_name)
        if status_id is None:
            raise ValueError(f"Status '{status_name}' não encontrado no Redmine.")
        return self.atualizar_issue(issue_id, status_id=status_id)

    def lancar_horas(self, issue_id: int, horas: float, comentario: str = "", data: str | None = None, activity_id: int | None = None) -> requests.Response:
        """Registra apontamento de horas (time entry) em uma issue."""
        if not data:
            from datetime import date
            data = date.today().isoformat()
        if activity_id is None:
            activity_id = 9  # fallback: Desenvolvimento (ajustar conforme projeto)
        entry = {
            "hours": horas,
            "activity_id": activity_id,
            "spent_on": data,
        }
        if comentario:
            entry["comments"] = comentario
        return self._post(f"/time_entries.json", {"time_entry": entry})

    def atividade_id(self, issue: dict) -> int:
        return issue["id"]
