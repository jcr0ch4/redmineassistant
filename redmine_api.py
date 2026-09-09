"""Módulo compartilhado de integração com o Redmine via REST API.

Usado pelos scripts de download, atualização da planilha e pelo app Flet.
Lê as credenciais do arquivo credenciais.txt por padrão, mas também aceita
credenciais customizadas (site, login, senha, api_key) informadas via
parâmetros — usadas pela tela de configuração do app.
"""

import json
import re
import time
from datetime import date, datetime, timezone

import requests

import debug_log
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


def normalizar_data(valor):
    """Normaliza um valor de data para o formato AAAA-MM-DD.

    Aceita datetime/date, ``AAAA-MM-DD``, ``DD/MM/AAAA`` e ``DD/MM/AA``.
    Retorna ``None`` para valores vazios ou que não correspondam a nenhum
    formato reconhecido (para a IA nunca enviar data ilegível à API).
    """
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    texto = str(valor).strip()
    if not texto:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", texto)
    if m:
        return texto
    m2 = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", texto)
    if m2:
        d, mo, a = m2.groups()
        a = a if len(a) == 4 else f"20{a}"
        return f"{a}-{int(mo):02d}-{int(d):02d}"
    return None


def criar_api(config: dict) -> "RedmineAPI | None":
    """Cria um cliente RedmineAPI a partir de um dict de config já carregado.

    Retorna ``None`` quando faltam site/api_key (sem levantar erro) para que
    os consumidores decidam o que fazer (ex.: cair em credenciais.txt).
    """
    if not config:
        return None
    site = (config.get("site") or "").strip().rstrip("/")
    api_key = (config.get("api_key") or "").strip()
    if not (site and api_key):
        return None
    return RedmineAPI(credenciais={
        "site": site,
        "api_key": api_key,
        "login": config.get("login"),
        "senha": config.get("senha"),
    })


def criar_api_da_config() -> "RedmineAPI":
    """Cria a API usando as credenciais de config.json (app) quando disponíveis,
    caso contrário cai em credenciais.txt."""
    from config_manager import carregar_config

    api = criar_api(carregar_config())
    return api or RedmineAPI()


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
        self.verificar_escritas = True

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
        self.verificar_escritas = True

    def _url(self, path: str) -> str:
        return f"{self.site}{path}"

    def _log_http(self, metodo: str, url: str, payload, resp=None, erro=None) -> None:
        debug_log.log(
            "redmine_http",
            metodo=metodo,
            url=url,
            payload=payload,
            status=getattr(resp, "status_code", None),
            resposta=(resp.text[:500] if resp is not None and resp.text else None),
            erro=str(erro) if erro else None,
        )

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = None
        try:
            resp = requests.get(self._url(path), headers=self.headers, params=params, timeout=60)
            resp.raise_for_status()
            self._log_http("GET", self._url(path), params, resp)
            return resp.json()
        except Exception as ex:
            self._log_http("GET", self._url(path), params, resp, ex)
            raise

    def _put(self, path: str, payload: dict) -> requests.Response:
        resp = None
        try:
            resp = requests.put(
                self._url(path), headers=self.headers, data=json.dumps(payload), timeout=60
            )
            resp.raise_for_status()
            self._log_http("PUT", self._url(path), payload, resp)
            return resp
        except Exception as ex:
            self._log_http("PUT", self._url(path), payload, resp, ex)
            raise

    def _post(self, path: str, payload: dict) -> requests.Response:
        resp = None
        try:
            resp = requests.post(
                self._url(path), headers=self.headers, data=json.dumps(payload), timeout=60
            )
            resp.raise_for_status()
            self._log_http("POST", self._url(path), payload, resp)
            return resp
        except Exception as ex:
            self._log_http("POST", self._url(path), payload, resp, ex)
            raise

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

    def get_issues_concluidas(self, sprint_id: int) -> list[dict]:
        """Baixa as issues fechadas (status closed) atribuídas ao usuário em uma sprint/versão.

        Usado pela visão kanban para exibir as atividades concluídas da sprint
        (o status ``Encerrada`` é filtrado pela interface).
        """
        usuario = self.get_usuario_atual()
        user_id = usuario.get("id")
        todas = []
        offset = 0
        limite = 100
        while True:
            params = {
                "assigned_to_id": user_id,
                "status_id": "closed",
                "fixed_version_id": sprint_id,
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
            if total is not None and offset >= total:
                break
        return todas

    def get_issue(self, issue_id: int) -> dict:
        """Retorna uma issue individual pelo ID."""
        data = self._get(f"/issues/{issue_id}.json")
        return data.get("issue", {})

    def get_status_ids(self) -> dict:
        """Retorna mapeamento nome -> id de todos os status."""
        data = self._get("/issue_statuses.json", params={"limit": 100})
        return {s["name"]: s["id"] for s in data.get("issue_statuses", [])}

    def get_todos_status(self) -> list[str]:
        """Retorna todos os nomes de status cadastrados no Redmine."""
        return sorted(self.get_status_ids())

    def get_versions(self, project_id: int) -> list[dict]:
        """Lista as versões/sprints de um projeto."""
        data = self._get(f"/projects/{project_id}/versions.json", params={"limit": 100})
        return data.get("versions", [])

    def get_time_entry_activities(self) -> list[dict]:
        """Lista as atividades possíveis para apontamento de horas."""
        data = self._get("/enumerations/time_entry_activities.json")
        return [a for a in data.get("time_entry_activities", []) if a.get("active")]

    def get_activity_id_padrao(self) -> int | None:
        """Resolve a atividade de apontamento padrão a partir do Redmine.

        Prefere a atividade cujo nome contenha "desenvolvimento"
        (case-insensitive); na ausência, usa a primeira atividade ativa.
        O resultado é cacheado na instância para evitar a chamada a cada
        lançamento de horas.
        """
        if getattr(self, "_activity_id_padrao", None) is None:
            atividades = self.get_time_entry_activities()
            if not atividades:
                self._activity_id_padrao = None
            else:
                alvo = next(
                    (a for a in atividades if "desenvolvimento" in (a.get("name") or "").lower()),
                    atividades[0],
                )
                self._activity_id_padrao = alvo.get("id")
        return self._activity_id_padrao

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
        """Atualiza campos de uma issue e confere se o Redmine persistiu a alteração.

        Alguns ambientes (proxy/firewall/espelho read-only) respondem 200/204
        para escritas via REST e descartam o JSON — o "sucesso" nada grava.
        A verificação faz um GET depois do PUT e, se o campo não mudou, lança
        erro para que a ação NÃO seja reportada como executada.
        """
        self._ts_antes = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = self._put(f"/issues/{issue_id}.json", {"issue": campos})
        if self.verificar_escritas:
            self._verificar_issue(issue_id, campos)
        return resp

    # campos do Redmine cujo valor chega aninhado em objeto (id) no GET
    _CAMPOS_ID_ANINHADO = (
        "project_id", "tracker_id", "status_id", "priority_id", "author_id",
        "assigned_to_id", "fixed_version_id", "category_id", "parent_id",
    )

    def _ler_campo_atual(self, issue: dict, campo: str):
        """Lê o valor atual de um campo a partir do dict retornado pelo GET."""
        if campo in self._CAMPOS_ID_ANINHADO:
            sub = issue.get(campo[:-3]) or {}
            return sub.get("id") if isinstance(sub, dict) else sub
        return issue.get(campo)

    def _verificar_issue(self, issue_id: int, campos: dict, max_tentativas: int = 3) -> None:
        """Confere via GET se os campos alterados foram persistidos.

        Tenta algumas vezes com pequena pausa para tolerar atrasos de
        replicação; se continuar sem aplicar, lança ValueError.
        """
        precisa_journal = bool((campos.get("notes") or "").strip())
        params = {"include": "journals"} if precisa_journal else None

        for tentativa in range(max_tentativas):
            data = self._get(f"/issues/{issue_id}.json", params=params)
            issue = data.get("issue", {})
            falhas = []

            for campo, novo in campos.items():
                if campo == "notes":
                    if not self._nota_persistida(issue, novo):
                        falhas.append((campo, novo, "(sem journal)"))
                    continue
                esperado = int(novo) if campo.endswith("_id") else novo
                if campo == "due_date" and novo == "":
                    esperado = None
                atual = self._ler_campo_atual(issue, campo)
                if atual != esperado:
                    falhas.append((campo, esperado, atual))

            if not falhas:
                debug_log.log("verificacao_escrita_ok", issue_id=issue_id, campos=list(campos))
                return
            if tentativa < max_tentativas - 1:
                time.sleep(0.4)

        for campo, esperado, atual in falhas:
            debug_log.log(
                "verificacao_escrita_falhou", issue_id=issue_id,
                campo=campo, esperado=esperado, atual=atual,
            )
        primeiro = falhas[0]
        raise ValueError(
            f"⚠️ O servidor aceitou a escrita mas NÃO salvou — campo '{primeiro[0]}' de "
            f"#{issue_id} continua {primeiro[2]!r} (esperado {primeiro[1]!r}). "
            "Verifique rede/proxy ou espelho read-only do Redmine."
        )

    def _nota_persistida(self, issue: dict, nota: str) -> bool:
        """Confere se o comentário (notes) virou um journal criado após o PUT."""
        nota = str(nota).strip()
        if not nota:
            return True
        journals = issue.get("journals") or []
        recentes = [
            j for j in journals if str(j.get("created_on") or "") >= self._ts_antes
        ]
        return any(
            nota in (str(j.get("notes") or "")) for j in recentes
        )

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
            data = date.today().isoformat()
        if activity_id is None:
            activity_id = self.get_activity_id_padrao()
        if activity_id is None:
            raise ValueError(
                "Nenhuma atividade de apontamento encontrada no Redmine — não foi "
                "possível definir 'activity_id' automaticamente."
            )
        entry = {
            "hours": horas,
            "activity_id": activity_id,
            "spent_on": data,
        }
        if comentario:
            entry["comments"] = comentario
        resp = self._post(f"/time_entries.json", {"time_entry": entry})
        if self.verificar_escritas:
            self._confirmar_time_entry(resp)
        return resp

    def _confirmar_time_entry(self, resp: requests.Response) -> None:
        """Garante que o POST de horas retornou 201 com time_entry criada."""
        try:
            criado = (resp.json() or {}).get("time_entry") or {}
            confirmado = resp.status_code == 201 and criado.get("id")
        except Exception:
            confirmado = False
        if not confirmado:
            debug_log.log(
                "verificacao_escrita_falhou", campo="time_entry",
                esperado=201, atual=resp.status_code,
            )
            raise ValueError(
                "⚠️ O servidor aceitou a escrita mas NÃO confirmou o lançamento de "
                "horas (esperava 201 + time_entry.id). Verifique rede/proxy ou "
                "espelho read-only do Redmine."
            )
