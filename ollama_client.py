"""Cliente multi-provedor de LLM — usado pelo app Flet para gerar sugestões e conversar.

Provedores suportados:
  - ollama  (padrão, local)
  - openai  (OpenAI / Azure OpenAI)
  - claude  (Anthropic)
  - gemini  (Google)
  - kimi    (Moonshot)

Fornece:
  - sugestão de lançamento (horas, previsão, sprint/versão, status, %)
  - chat de apoio (conversa livre sobre a atividade)
  - assistente pessoal com ações (lancar horas, priorizar, anotar)

Configurações configuráveis por provedor: modelo, chave de API, URL (base),
prompt system personalizado, temperatura e max_tokens.
"""

import json
import re
from datetime import date

import requests

MODELO_PADRAO = "llama3.1:latest"
OLLAMA_URL = "http://localhost:11434/api/chat"

# ------------------------------------------------------------------ endpoints por provedor
PROVIDERS = {
    "ollama": {
        "label": "Ollama (local)",
        "default_url": "http://localhost:11434/api/chat",
        "default_model": "llama3.1:latest",
        "multi_model": True,
    },
    "openai": {
        "label": "OpenAI",
        "default_url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o-mini",
        "multi_model": True,
    },
    "claude": {
        "label": "Claude (Anthropic)",
        "default_url": "https://api.anthropic.com/v1/messages",
        "default_model": "claude-3-5-sonnet-latest",
        "multi_model": True,
    },
    "gemini": {
        "label": "Gemini (Google)",
        "default_url": "https://generativelanguage.googleapis.com/v1beta/models",
        "default_model": "gemini-1.5-flash",
        "multi_model": True,
    },
    "kimi": {
        "label": "Kimi (Moonshot)",
        "default_url": "https://api.moonshot.cn/v1/chat/completions",
        "default_model": "moonshot-v1-8k",
        "multi_model": True,
    },
}

PROMPT_SUGESTAO = """Você é um assistente de gestão de projetos que ajuda um desenvolvedor a lançar horas no Redmine.

Dados da atividade:
- ID: {issue_id}
- Projeto: {projeto}
- Tipo: {tipo}
- Status atual: {status}
- Prioridade: {prioridade}
- Sprint/Versão atual: {versao}
- Assunto: {assunto}
- Descrição: {descricao}
- Data início: {inicio}
- Data prevista atual: {previsao}
- % concluído: {done_ratio}
- Horas estimadas: {estimadas}
- Horas já gastas: {gastas}
- Hoje: {hoje}

Tarefa: gere uma SUGESTÃO de lançamento de horas para esta atividade, em português.
Responda SOMENTE com um JSON válido com estas chaves (use números, sem unidades):
{{
  "horas_sugeridas": <número estimado de horas a lançar agora, ex: 1.5>,
  "percentual": <novo percentual concluído 0-100>,
  "status": <sugestão de novo status entre: Nova, Em andamento, Backlog, Especificação, Encerrada>,
  "previsao": <nova data prevista no formato AAAA-MM-DD ou null>,
  "comentario": <breve comentário em pt-BR sobre o que foi feito/previsto>
}}
Seja realista e conciso. Não inclua texto fora do JSON."""

PROMPT_SUGESTAO_CURTO = """Analise esta atividade de TI e sugira dados para o lançamento de horas no Redmine.

Assunto: {assunto}
Descrição: {descricao}
Projeto: {projeto}
Status: {status}
Sprint/Versão: {versao}
Horas estimadas: {estimadas}
Horas já gastas: {gastas}
% concluído: {done_ratio}
Data prevista: {previsao}
Hoje: {hoje}

Responda SOMENTE com JSON válido, sem texto extra:
{{
  "horas_sugeridas": <número estimado de horas a lançar agora>,
  "percentual": <novo percentual 0-100>,
  "status": <Nova|Em andamento|Backlog|Especificação|Encerrada>,
  "previsao": <data AAAA-MM-DD ou null>,
  "comentario": "<comentário curto em pt-BR>"
}}"""

RESPOSTA_JSON = (
    '\n\nIMPORTANTE: sua resposta final deve ser APENAS um JSON válido e único, '
    'sem texto antes ou depois.'
)


class OllamaClient:
    """Cliente de LLM genérico/compatível que suporta múltiplos provedores.

    Mantém o nome ``OllamaClient`` e a assinatura ``__init__(base_url, modelo)``
    para retrocompatibilidade, mas também aceita ``provider`` e ``api_key`` para
    usar OpenAI, Claude, Gemini ou Kimi.
    """

    def __init__(
        self,
        base_url: str = OLLAMA_URL,
        modelo: str = MODELO_PADRAO,
        provider: str = "ollama",
        api_key: str = "",
        temperature: float = 0.4,
        max_tokens: int | None = None,
        prompt_system: str = "",
    ):
        self.provider = (provider or "ollama").lower()
        self.base_url = base_url or PROVIDERS.get(self.provider, {}).get("default_url", OLLAMA_URL)
        self.modelo = modelo or PROVIDERS.get(self.provider, {}).get("default_model", MODELO_PADRAO)
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.prompt_system = (prompt_system or "").strip()

    # ============================================================ transporte por provedor
    def _enviar(self, messages: list[dict], timeout: int = 240) -> str:
        provider = self.provider
        if provider == "ollama":
            return self._enviar_ollama(messages, timeout)
        if provider == "claude":
            return self._enviar_claude(messages, timeout)
        if provider == "gemini":
            return self._enviar_gemini(messages, timeout)
        # openai e kimi usam a API compatível com OpenAI
        return self._enviar_openai(messages, timeout)

    def _enviar_ollama(self, messages: list[dict], timeout: int) -> str:
        payload = {
            "model": self.modelo,
            "messages": messages,
            "stream": False,
            "temperature": self.temperature,
        }
        if self.max_tokens:
            payload["num_predict"] = self.max_tokens
        resp = requests.post(self.base_url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")

    def _enviar_openai(self, messages: list[dict], timeout: int) -> str:
        base = self.base_url.rstrip("/")
        if not base.endswith("/chat/completions"):
            base = base + "/chat/completions"
        payload = {
            "model": self.modelo,
            "messages": messages,
            "temperature": self.temperature,
        }
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = requests.post(base, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    def _enviar_claude(self, messages: list[dict], timeout: int) -> str:
        # separa o system dos turnos de conversa
        system_parts = []
        turnos = []
        for m in messages:
            if m.get("role") == "system":
                system_parts.append(m.get("content", ""))
            else:
                turnos.append({"role": m.get("role"), "content": m.get("content", "")})
        payload = {
            "model": self.modelo,
            "messages": turnos,
            "max_tokens": int(self.max_tokens or 4096),
            "temperature": self.temperature,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        resp = requests.post(self.base_url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        # content é uma lista de blocos
        partes = []
        for bloco in data.get("content", []):
            if bloco.get("type") == "text":
                partes.append(bloco.get("text", ""))
        return "\n".join(partes)

    def _enviar_gemini(self, messages: list[dict], timeout: int) -> str:
        # converte mensagens para o formato Gemini: system + user/model
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        contents = []
        for m in messages:
            if m.get("role") == "system":
                continue
            role = "user" if m.get("role") == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})
        if not contents:
            contents = [{"role": "user", "parts": [{"text": ""}]}]
        body = {
            "contents": contents,
            "generationConfig": {"temperature": self.temperature},
        }
        if self.max_tokens:
            body["generationConfig"]["maxOutputTokens"] = self.max_tokens
        if system_parts:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        base = self.base_url.rstrip("/")
        url = f"{base}/{self.modelo}:generateContent?key={self.api_key}"
        resp = requests.post(url, json=body, headers={"Content-Type": "application/json"}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            return ""

    # ============================================================ helpers
    @staticmethod
    def _extrair_json(texto: str) -> dict:
        """Extrai o primeiro objeto JSON de um texto (mesmo com ruído ao redor)."""
        texto = texto.strip()
        m = re.search(r"\{.*\}", texto, re.DOTALL)
        if not m:
            raise ValueError("Nenhum JSON encontrado na resposta.")
        return json.loads(m.group(0))

    def _chat(self, prompt: str, system: str | None = None, timeout: int = 120, usar_padrao: bool = True) -> str:
        """Envia um único prompt com um system opcional.

        Se ``usar_padrao`` for True (padrão), o ``prompt_system`` configurado é
        prefixado ao system informado.
        """
        base = self.prompt_system if usar_padrao else ""
        if system and system.strip():
            base = "\n\n".join(x for x in (base, system.strip()) if x)
        messages = []
        if base:
            messages.append({"role": "system", "content": base})
        messages.append({"role": "user", "content": prompt})
        return self._enviar(messages, timeout=timeout)

    # ============================================================ sugestão de lançamento
    def gerar_sugestao(self, issue: dict, longo: bool = True) -> dict:
        """Gera uma sugestão de lançamento para uma issue. Retorna dict com chaves esperadas."""
        assunto = issue.get("subject", "")
        descricao = issue.get("description", "") or ""
        projeto = (issue.get("project") or {}).get("name", "")
        status = (issue.get("status") or {}).get("name", "")
        versao = (issue.get("fixed_version") or {}).get("name", "") or ""
        prompt = (PROMPT_SUGESTAO if longo else PROMPT_SUGESTAO_CURTO) + RESPOSTA_JSON

        preenchido = prompt.format(
            issue_id=issue.get("id"),
            projeto=projeto,
            tipo=(issue.get("tracker") or {}).get("name", ""),
            status=status,
            prioridade=(issue.get("priority") or {}).get("name", ""),
            versao=versao,
            assunto=assunto,
            descricao=descricao[:2000],
            inicio=issue.get("start_date") or "",
            previsao=issue.get("due_date") or "",
            done_ratio=issue.get("done_ratio", 0),
            estimadas=issue.get("estimated_hours") or "",
            gastas=issue.get("spent_hours", 0),
            hoje=date.today().isoformat(),
        )

        texto = self._chat(preenchido, usar_padrao=False)
        if not texto.strip():
            raise ValueError("O assistente não retornou nenhuma resposta.")
        dados = self._extrair_json(texto)
        dados.setdefault("horas_sugeridas", "")
        dados.setdefault("percentual", issue.get("done_ratio", 0))
        dados.setdefault("status", status)
        dados.setdefault("previsao", None)
        dados.setdefault("comentario", "")
        return dados

    def chat(self, mensagem: str, historico: list[dict] | None = None, system: str | None = None) -> str:
        """Conversa livre de apoio. historico é lista de {role, content}.

        O ``system`` informado é combinado com o ``prompt_system`` configurado
        (o configurado entra primeiro, como diretrizes globais).
        """
        base = self.prompt_system or ""
        if system and system.strip():
            base = "\n\n".join(x for x in (base, system.strip()) if x)
        messages = []
        if base:
            messages.append({"role": "system", "content": base})
        if historico:
            messages.extend(historico)
        messages.append({"role": "user", "content": mensagem})
        return self._enviar(messages, timeout=240)

    # ============================================================ assistente pessoal
    _PROMPT_ASSISTENTE = """Você é o assistente pessoal de trabalho (tipo "gerente ágil") do desenvolvedor,
integrado ao Redmine. Você ajuda a organizar as atividades por prioridade e a lançar as
horas trabalhadas diretamente no Redmine quando solicitado.

Você recebe uma lista JSON das atividades atuais do usuário no campo {lista_issues},
cada uma com id, projeto, assunto, status, prioridade original (p1/p2/p3...), sprint,
% concluído, horas estimadas, horas gastas e data prevista. Também recebe a ordem de
prioridade personalizada já salva pelo usuário (mais importante primeiro), se houver.

FERRAMENTAS DISPONÍVEIS (use SOMENTE estas):
{descricao_ferramentas}

Formato de resposta com ação (no format_actions):

{formatos_acoes}

REGRAS IMPORTANTES:
1. Fale sempre em português (pt-BR), de forma objetiva e prática.
2. Ao responder, você PODE executar ações chamando as ferramentas disponíveis. Use-as
   apenas quando o usuário pedir explicitamente (lançar horas, mudar status, priorizar, etc.)
   ou quando a ação for claramente necessária para atender o pedido.
3. Se o usuário pedir para LANÇAR HORAS em uma atividade, use a ferramenta específica
   informando issue_id, horas, comentario (opcional), data (AAAA-MM-DD). Só use ids que
   existam na lista de atividades.
4. Se o usuário pedir para ORGANIZAR/priorizar as atividades, responda com a ferramenta
   "definir_prioridade" informando a lista de issue_ids na ordem desejada (primeiro = mais
   importante) e uma pequena justificativa em "nota".
5. Se o usuário só quiser uma SUGESTÃO (de prioridade, status etc.) sem aplicar, NÃO use a
   ferramenta; apenas responda em texto.
6. Você pode manter anotações. Sempre que o usuário der contexto novo sobre uma atividade,
   anote com a ferramenta "salvar_nota" (issue_id + nota curta) se ela estiver habilitada.
7. NUNCA invente uma ferramenta: use apenas as descritas acima, no formato exato.

Se não houver ação a executar, deixe format_actions vazio (não inclua o campo) e apenas responda
em texto normal na conversa."""

    def _montar_system_assistente(self, issues: list, prioridades: dict, notas: dict, ferramentas: list[str] | None = None) -> str:
        resumo = [
            {
                "id": i.get("id"),
                "projeto": (i.get("project") or {}).get("name", ""),
                "assunto": i.get("subject", ""),
                "status": (i.get("status") or {}).get("name", ""),
                "prioridade": (i.get("priority") or {}).get("name", ""),
                "sprint": (i.get("fixed_version") or {}).get("name", "") or "",
                "done": i.get("done_ratio", 0),
                "estimadas": i.get("estimated_hours"),
                "gastas": i.get("spent_hours", 0),
                "previsao": i.get("due_date") or "",
            }
            for i in issues[:40]
        ]
        prioridade_ordenada = [
            {"id": pid, "nota": info.get("nota", "")} for pid, info in prioridades.items()
        ]

        from ferramentas import descricao_habilitadas, formatos_habilitados

        base = self._PROMPT_ASSISTENTE.format(
            lista_issues=json.dumps(resumo, ensure_ascii=False),
            notas=json.dumps(notas, ensure_ascii=False),
            descricao_ferramentas=descricao_habilitadas(ferramentas) or "(nenhuma ferramenta habilitada)",
            formatos_acoes=formatos_habilitados(ferramentas),
        )
        base += (
            "\n\nOrdem de prioridade atualmente salva (mais importante primeiro): "
            + json.dumps(prioridade_ordenada, ensure_ascii=False)
        )
        if self.prompt_system:
            base += f"\n\n{self.prompt_system}"
        else:
            base += (
                "\n\nIMPORTANTE: responda com o campo format_actions. Sempre que houver 1+ ações, "
                "comece sua resposta textual explicando brevemente o que fez. Retorne SOMENTE JSON "
                'com as chaves: {"resposta": "<texto em pt-BR>", "format_actions": [<ações...>]}.'
            )
        return base

    def chat_assistente(
        self,
        mensagem: str,
        issues: list[dict],
        prioridades: dict,
        notas: dict,
        historico: list[dict] | None = None,
        ferramentas: list[str] | None = None,
    ) -> dict:
        """Conversa do assistente pessoal.

        Retorna dict: {"resposta": str, "acoes": [{"acao": ..., "dados": {...}}]}.
        `acoes` pode conter as ações das ferramentas habilitadas em ``ferramentas``.
        """
        system = self._montar_system_assistente(issues, prioridades, notas, ferramentas)
        messages = [{"role": "system", "content": system}]
        if historico:
            messages.extend(historico[-20:])
        messages.append({"role": "user", "content": mensagem})

        texto = self._enviar(messages, timeout=240)
        if not texto.strip():
            return {"resposta": "", "acoes": []}

        try:
            dados = self._extrair_json(texto)
        except Exception:
            return {"resposta": texto, "acoes": [], "raw": texto}

        resposta = str(dados.get("resposta") or dados.get("response") or texto)
        acoes = dados.get("format_actions") or dados.get("acoes") or []
        if not isinstance(acoes, list):
            acoes = []
        if ferramentas:
            acoes = [a for a in acoes if isinstance(a, dict) and (a.get("acao") or a.get("tipo")) in ferramentas]
        return {"resposta": resposta, "acoes": acoes, "raw": texto}


def testar_conexao(provider: str, base_url: str, modelo: str, api_key: str) -> str:
    """Testa se o provedor configurado consegue responder. Retorna mensagem de status."""
    cliente = OllamaClient(
        base_url=base_url,
        modelo=modelo,
        provider=provider,
        api_key=api_key,
    )
    try:
        texto = cliente._chat("Responda apenas: ok", timeout=60)
        if texto.strip():
            return f"Conectado via {provider.upper()} ✓"
        return "Conectado, mas resposta vazia."
    except Exception as ex:
        return f"Falha: {type(ex).__name__}: {ex}"
