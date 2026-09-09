"""Execução das ações retornadas pelo assistente (lógica pura, sem Flet).

Extraída de app_flet.py (_executar_acoes/_processar_acao/_acao_local/_acao_redmine)
para permitir testes sem inicializar uma ft.Page e facilitar o reaproveitamento
em outros fluxos.

Não importa `flet`: opera apenas com um RedmineAPI (ou None), a config do app
e a lista de issues já carregadas.
"""

from datetime import date

import assistente_db as adb
import debug_log
from ferramentas import TOOLS
from redmine_api import RedmineAPI, criar_api, normalizar_data


class ExecutorDeAcoes:
    """Executa ações solicitadas pelo assistente conforme as ferramentas habilitadas."""

    def __init__(self, config: dict, api: RedmineAPI | None = None, issues: list[dict] | None = None):
        self.config = config or {}
        self.api = api
        self.issues = issues or []
        self.hoje = date.today().isoformat()

    def executar(self, acoes: list) -> str:
        """Executa a lista de ações e retorna o relatório em texto ('' se nenhum aviso)."""
        habilitadas = set(self.config.get("ferramentas_habilitadas") or [])
        # regra das Configurações: % concluído nunca é alterado quando desligado
        if not self.config.get("atualizar_percentual", False):
            habilitadas.discard("atualizar_percentual")
        # ferramentas locais não precisam de API
        locais = {t["id"] for t in TOOLS if not t.get("requer_redmine")}
        precisa_api = any(
            isinstance(a, dict) and (a.get("acao") or a.get("tipo")) in habilitadas - locais
            for a in acoes
        )
        if precisa_api and self.api is None:
            self.api = criar_api(self.config)
            if self.api is None:
                return "Não configurado: informe URL e API key do Redmine na aba Configuração."

        avisos = []
        for item in acoes:
            if not isinstance(item, dict):
                continue
            acao = item.get("acao") or item.get("tipo")
            if acao not in habilitadas:
                debug_log.log("acao_ignorada", acao=acao, motivo="ferramenta desabilitada")
                avisos.append(f"⚠️ Ferramenta '{acao}' desabilitada — ação ignorada.")
                continue
            dados = item.get("dados") or {}
            try:
                msg = self._processar(acao, dados)
                debug_log.log("acao_executada", acao=acao, dados=dados, resultado=msg or "")
                if msg:
                    avisos.append(msg)
            except Exception as ex:
                debug_log.log("acao_falhou", acao=acao, dados=dados, erro=str(ex))
                avisos.append(f"❌ Ação '{acao}' falhou: {ex}")
        return "\n".join(avisos)

    def _processar(self, acao: str, dados: dict) -> str:
        """Executa uma ação individual e retorna mensagem de resultado (ou '')."""
        if acao in ("definir_prioridade", "salvar_nota"):
            return self._local(acao, dados)
        return self._redmine(acao, dados)

    def _local(self, acao: str, dados: dict) -> str:
        if acao == "definir_prioridade":
            ids = [int(x) for x in (dados.get("issue_ids") or []) if str(x).isdigit() or isinstance(x, int)]
            nota = str(dados.get("nota") or "")
            adb.definir_prioridade_ordem(ids, nota)
            return f"✅ Prioridade definida para {len(ids)} atividades (ordem local)."
        if acao == "salvar_nota":
            issue_id = int(dados.get("issue_id"))
            nota = str(dados.get("nota") or "")
            adb.salvar_nota(issue_id, nota)
            return f"✅ Anotação salva para #{issue_id} (local)."
        return ""

    def _redmine(self, acao: str, dados: dict) -> str:
        api = self.api
        if acao == "lancar_horas":
            issue_id = int(dados.get("issue_id"))
            horas = float(dados.get("horas"))
            comentario = str(dados.get("comentario") or "")
            if horas <= 0:
                return f"⚠️ Horas inválidas (<=0) para #{issue_id}."
            data = normalizar_data(dados.get("data") or "")
            if data is None:
                return f"⚠️ Data '{dados.get('data')}' inválida para #{issue_id} — use AAAA-MM-DD."
            ativ_nome = str(dados.get("atividade") or "").strip()
            activity_id = None
            if ativ_nome:
                atividades = api.get_time_entry_activities()
                alvo = next(
                    (a for a in atividades if (a.get("name") or "").lower() == ativ_nome.lower()),
                    None,
                )
                if alvo is None:
                    raise ValueError(f"Atividade de apontamento '{ativ_nome}' não encontrada no Redmine.")
                activity_id = alvo["id"]
            api.lancar_horas(issue_id, horas, comentario, data, activity_id=activity_id)
            msg = f"✅ Lançadas {horas}h em #{issue_id} no Redmine."
            if ativ_nome:
                msg += f" (atividade: {ativ_nome})"
            return msg
        if acao == "atualizar_status":
            issue_id = int(dados.get("issue_id"))
            status = str(dados.get("status") or "")
            api.atualizar_status(issue_id, status)
            return f"✅ Status #{issue_id} alterado para '{status}'."
        if acao == "atualizar_percentual":
            issue_id = int(dados.get("issue_id"))
            pct = int(float(dados.get("percentual")))
            pct = max(0, min(100, pct))
            api.atualizar_issue(issue_id, done_ratio=pct)
            return f"✅ % concluído de #{issue_id} definido para {pct}%."
        if acao == "atualizar_previsao":
            issue_id = int(dados.get("issue_id"))
            data = normalizar_data(dados.get("data") or self.hoje)
            if data is None:
                return f"⚠️ Data '{dados.get('data')}' inválida para #{issue_id} — use AAAA-MM-DD."
            api.atualizar_issue(issue_id, due_date=data)
            return f"✅ Data prevista de #{issue_id} alterada para {data}."
        if acao == "atualizar_prioridade":
            issue_id = int(dados.get("issue_id"))
            prioridade = str(dados.get("prioridade") or "")
            prioridades = api.get_issue_priorities()
            prio_id = next((p["id"] for p in prioridades if p["name"].lower() == prioridade.lower()), None)
            if prio_id is None:
                raise ValueError(f"Prioridade '{prioridade}' não encontrada no Redmine.")
            api.atualizar_issue(issue_id, priority_id=prio_id)
            return f"✅ Prioridade #{issue_id} alterada para '{prioridade}'."
        if acao == "adicionar_comentario":
            issue_id = int(dados.get("issue_id"))
            comentario = str(dados.get("comentario") or "")
            api.adicionar_comentario(issue_id, comentario)
            return f"✅ Comentário adicionado a #{issue_id}."
        if acao == "listar_atividades":
            termo = str(dados.get("termo") or "").lower()
            status_filtro = str(dados.get("status") or "").lower()
            prio_filtro = str(dados.get("prioridade") or "").lower()
            lista = list(self.issues) or (api.get_issues_ativas() if api else [])
            if termo:
                lista = [i for i in lista if termo in str(i.get("id")) or termo in (i.get("subject") or "").lower()]
            if status_filtro:
                lista = [i for i in lista if status_filtro in (i.get("status") or {}).get("name", "").lower()]
            if prio_filtro:
                lista = [i for i in lista if prio_filtro in (i.get("priority") or {}).get("name", "").lower()]
            if not lista:
                return "📭 Nenhuma atividade encontrada com esses filtros."
            linhas = [f"- #{i.get('id')} · {(i.get('status') or {}).get('name','')} · {i.get('subject')}" for i in lista[:20]]
            return "📋 Atividades encontradas:\n" + "\n".join(linhas)
        return f"⚠️ Ferramenta '{acao}' não implementada."