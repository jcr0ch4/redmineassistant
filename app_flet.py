"""App Flet (estilo mobile/android) — Assistente pessoal do Redmine.

Atividades atribuídas ao usuário com:
  - lista paginada (6 por página) e busca
  - botão para Lançar horas (apontamento) em cada atividade
  - botão para a IA (Ollama) revisar cada atividade, como um gerente de projetos Ágil
  - tela de configuração para informar credenciais/URL do Redmine e modelo do Ollama

Executar:
    flet run app_flet.py
ou:
    python app_flet.py
"""

import asyncio
import platform
from datetime import date

import flet as ft

import assistente_db as adb
from config_manager import carregar_config, salvar_config
from ferramentas import TOOLS, TOOLS_POR_ID, categorias, ferramentas_por_categoria
from ollama_client import PROVIDERS, OllamaClient
from redmine_api import STATUS_ATIVOS, RedmineAPI

STATUS_VALIDOS = ["Nova", "Backlog", "Especificação", "Em andamento", "Validação", "Encerrada", "Cancelada", "Suspensa"]
ITENS_POR_PAGINA = 6

CORES_STATUS = {
    "Nova": ft.Colors.RED_200,
    "Em andamento": ft.Colors.AMBER_200,
    "Especificação": ft.Colors.GREEN_200,
    "Backlog": ft.Colors.BLUE_200,
}


class App:
    def __init__(self, page: ft.Page):
        self.page = page
        self.config = carregar_config()
        self.ollama = self._construir_cliente_llm()

        self.issues = []
        self.filtrados = []
        self.pagina = 0
        self.aba_atual = 0
        self.em_revisao = False
        self.issue_selecionada = None
        self.versoes_projeto = []
        self.hoje = date.today().isoformat()
        self.api = None

        # Indicador de "digitando" (3 pontos animados) do assistente
        self.asst_digitando_col = None
        self.asst_digitando_ativo = False
        self._digitando_task = None

        # Área de conteúdo (troca entre abas)
        self.conteudo = ft.Column(expand=True)
        self.navbar = ft.NavigationBar(
            selected_index=0,
            bgcolor=ft.Colors.SURFACE,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.LIST_ALT, label="Atividades"),
                ft.NavigationBarDestination(icon=ft.Icons.SMART_TOY, label="Assistente"),
                ft.NavigationBarDestination(icon=ft.Icons.SETTINGS, label="Configuração"),
            ],
            on_change=self._trocar_aba,
        )

        self._montar_pagina()
        self.page.run_task(self._inicializar)

    # ============================================================ bootstrap
    def _montar_pagina(self):
        self.page.title = "Assistente Redmine"
        self.page.padding = 0
        self.page.spacing = 0

        # ---- Tema Material 3 (estilo Android) ----
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.theme = ft.Theme(
            color_scheme_seed=ft.Colors.INDIGO,
            visual_density=ft.VisualDensity.COMFORTABLE,
            scaffold_bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            color_scheme=ft.ColorScheme(
                primary=ft.Colors.INDIGO,
                on_primary=ft.Colors.WHITE,
                primary_container=ft.Colors.INDIGO_100,
                on_primary_container=ft.Colors.INDIGO_900,
                secondary=ft.Colors.TEAL,
                secondary_container=ft.Colors.TEAL_100,
                on_secondary_container=ft.Colors.TEAL_900,
                surface=ft.Colors.WHITE,
                surface_container_low=ft.Colors.GREY_100,
                surface_container_highest=ft.Colors.GREY_200,
            ),
        )

        self.navbar.bgcolor = ft.Colors.SURFACE
        self.navbar.indicator_color = ft.Colors.INDIGO_100
        self.page.add(self.conteudo, self.navbar)

    async def _inicializar(self):
        await asyncio.to_thread(self._construir_views)
        self._renderizar_abate(0)
        self._carregar_historico_assistente()
        if self.config.get("api_key"):
            await self._carregar_async()

    def _construir_views(self):
        # ---------- view ATIVIDADES ----------
        self.busca = ft.TextField(
            label="Buscar (ID ou assunto)",
            prefix_icon=ft.Icons.SEARCH,
            on_change=self._filtrar,
            border_radius=12,
        )
        self.lista = ft.Column(spacing=8, expand=True)
        self.lbl_carregando = ft.Text("", size=12, color=ft.Colors.GREY)
        self.lbl_usuario = ft.Text("", size=12, weight=ft.FontWeight.BOLD)
        self.row_paginacao = ft.Row([], alignment=ft.MainAxisAlignment.CENTER, spacing=8)

        self.view_atividades = ft.ListView(
            [
                ft.Container(
                    ft.Column(
                        [
                            ft.Row([self.lbl_usuario, ft.Container(expand=True), self.btn_atualizar()], spacing=8),
                            self.busca,
                            self.lbl_carregando,
                            self.lista,
                            self.row_paginacao,
                        ],
                        spacing=8,
                    ),
                    padding=12,
                )
            ],
            expand=True,
            spacing=8,
        )

        # ---------- view ASSISTENTE ----------
        self.asst_msgs = ft.Column(spacing=12, expand=True, scroll=ft.ScrollMode.AUTO)
        self.asst_prioridades = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        self.asst_input = ft.TextField(
            label="Peça ajuda ao assistente...",
            hint_text="Ex: priorize minhas atividades e lance 2h na #123",
            expand=True,
            multiline=True,
            min_lines=1,
            max_lines=4,
            border_radius=18,
            prefix_icon=ft.Icons.SMART_TOY,
            on_submit=lambda e: self.page.run_task(self._enviar_assistente),
        )
        self.asst_btn_enviar = ft.IconButton(
            icon=ft.Icons.SEND,
            icon_color=ft.Colors.ON_PRIMARY,
            bgcolor=ft.Colors.PRIMARY,
            tooltip="Enviar",
            on_click=lambda e: self.page.run_task(self._enviar_assistente),
        )
        self.asst_historico = []
        self.asst_prompt_sistema = None
        self.asst_lbl_status = ft.Text("", size=11, color=ft.Colors.GREY)

        # Barra superior FIXA (título + ícone + limpar)
        self.asst_appbar = ft.Container(
            ft.Row(
                [
                    ft.Container(
                        ft.Icon(ft.Icons.SMART_TOY, color=ft.Colors.WHITE),
                        bgcolor=ft.Colors.INDIGO,
                        border_radius=12,
                        padding=ft.Padding(8, 8, 8, 8),
                    ),
                    ft.Column(
                        [
                            ft.Text("Assistente pessoal", weight=ft.FontWeight.BOLD, size=16),
                            ft.Text("Organiza por prioridade e lança horas", size=11, color=ft.Colors.GREY),
                        ],
                        spacing=0,
                        expand=True,
                    ),
                    self._btn_limpar_historico(),
                ],
                spacing=8,
            ),
            bgcolor=ft.Colors.SURFACE,
            padding=ft.Padding(12, 10, 8, 10),
            border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
        )

        sugestoes = ft.Row(
            [
                ft.Chip(label=ft.Text("Priorizar atividades"), on_click=lambda e: self.page.run_task(self._pergunta_assistente, "Organize minhas atividades por prioridade, da mais para a menos importante.")),
                ft.Chip(label=ft.Text("O que está em atraso?"), on_click=lambda e: self.page.run_task(self._pergunta_assistente, "Quais atividades estão em risco de atraso e por quê?")),
                ft.Chip(label=ft.Text("Sugira plano de hoje"), on_click=lambda e: self.page.run_task(self._pergunta_assistente, "Sugira um plano de trabalho para hoje baseado nas prioridades.")),
            ],
            spacing=6,
            wrap=True,
        )

        # Área do chat com scroll (preenche o espaço restante)
        self.asst_chat_area = ft.Container(
            self.asst_msgs,
            expand=True,
            padding=ft.Padding(12, 8, 12, 8),
        )

        # Painel de prioridades com altura limitada (rola internamente)
        self.asst_prioridade_painel = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.LOW_PRIORITY, size=16, color=ft.Colors.INDIGO),
                            ft.Text("Minhas atividades por prioridade", weight=ft.FontWeight.BOLD, size=13),
                        ],
                        spacing=6,
                    ),
                    self.asst_prioridades,
                ],
                spacing=6,
            ),
            height=160,
            padding=ft.Padding(12, 0, 12, 0),
        )

        # Rodapé FIXO (sugestões + input)
        self.asst_rodape = ft.Container(
            ft.Column(
                [
                    sugestoes,
                    self.asst_lbl_status,
                    ft.Row([self.asst_input, ft.Container(content=self.asst_btn_enviar)], spacing=8),
                ],
                spacing=6,
            ),
            bgcolor=ft.Colors.SURFACE,
            padding=ft.Padding(12, 6, 12, 10),
            border=ft.Border(top=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
        )

        self.view_assistente = ft.Column(
            [
                self.asst_appbar,
                self.asst_chat_area,
                self.asst_prioridade_painel,
                self.asst_rodape,
            ],
            expand=True,
            spacing=0,
        )

        # ---------- view CONFIG ----------
        self.txt_site = ft.TextField(label="URL do Redmine", hint_text="https://projetos.wheaton.com.br", value=self.config.get("site", ""))
        self.txt_login = ft.TextField(label="Login", value=self.config.get("login", ""))
        self.txt_senha = ft.TextField(label="Senha", password=True, can_reveal_password=True, value=self.config.get("senha", ""))
        self.txt_apikey = ft.TextField(label="API access key", value=self.config.get("api_key", ""), password=True, can_reveal_password=True)

        # LLM
        self.cmb_provider = ft.Dropdown(
            label="Provedor de IA",
            value=self.config.get("llm_provider", "ollama"),
            options=[ft.DropdownOption(key=k, text=v["label"]) for k, v in PROVIDERS.items()],
            on_select=self._mudar_provider,
        )
        self.txt_llm_api_key = ft.TextField(label="Chave de API (provedor)", password=True, can_reveal_password=True, value=self.config.get("llm_api_key", ""))
        self.txt_llm_url = ft.TextField(label="URL da API", value=self.config.get("llm_url", ""), hint_text="Deixe vazio para usar o padrão do provedor")
        self.txt_llm_model = ft.TextField(label="Modelo", value=self.config.get("llm_model", ""))
        self.txt_llm_temp = ft.TextField(label="Temperatura (0.0 a 1.5)", value=str(self.config.get("llm_temperature", 0.4)), keyboard_type=ft.KeyboardType.NUMBER)
        self.txt_llm_max_tokens = ft.TextField(label="Máx. tokens (opcional)", value=str(self.config.get("llm_max_tokens", "")), keyboard_type=ft.KeyboardType.NUMBER, hint_text="ex: 4096")
        self.txt_llm_prompt_system = ft.TextField(
            label="Prompt system personalizado (opcional)",
            value=self.config.get("llm_prompt_system", ""),
            hint_text="Instruções extras para o assistente",
            multiline=True,
            min_lines=3,
            max_lines=6,
        )
        self.lbl_status_config = ft.Text("", size=12, color=ft.Colors.GREY)
        self.btn_salvar = ft.FilledButton("Salvar configurações", icon=ft.Icons.SAVE, on_click=self._salvar_config)
        self.btn_testar = ft.Button("Testar conexão", icon=ft.Icons.CONNECTED_TV, on_click=lambda e: self.page.run_task(self._testar_async))

        # Ferramentas do assistente (ações que a IA pode executar)
        self._chk_ferramentas: dict[str, ft.Checkbox] = {}
        blocos_ferramentas = []
        ferramentas_salvas = set(self.config.get("ferramentas_habilitadas") or [])
        for categoria in categorias():
            ferramentas_cat = [t for t in TOOLS if t["categoria"] == categoria]
            if not ferramentas_cat:
                continue
            col_chks = ft.Column(spacing=2)
            for tool in ferramentas_cat:
                chk = ft.Checkbox(
                    label=tool["nome"],
                    value=tool["id"] in ferramentas_salvas,
                    tooltip=tool["descricao"],
                )
                self._chk_ferramentas[tool["id"]] = chk
                col_chks.controls.append(chk)
            blocos_ferramentas.append(
                ft.Container(
                    ft.Column(
                        [
                            ft.Text(categoria, weight=ft.FontWeight.BOLD, size=13),
                            col_chks,
                        ],
                        spacing=6,
                    ),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                    border_radius=10,
                    padding=10,
                )
            )

        self._atualizar_campos_llm(initial=True)

        self.view_config = ft.ListView(
            [
                ft.Container(
                    ft.Column(
                        [
                            ft.Text("Configurações", size=18, weight=ft.FontWeight.BOLD),
                            ft.Text("Credenciais do Redmine", weight=ft.FontWeight.BOLD, size=13),
                            self.txt_site,
                            self.txt_login,
                            self.txt_senha,
                            self.txt_apikey,
                            ft.Divider(height=8),
                            ft.Text("Provedor de IA (LLM)", weight=ft.FontWeight.BOLD, size=13),
                            self.cmb_provider,
                            self.txt_llm_api_key,
                            self.txt_llm_url,
                            self.txt_llm_model,
                            ft.Row([self.txt_llm_temp, self.txt_llm_max_tokens], spacing=8),
                            self.txt_llm_prompt_system,
                            ft.Divider(height=8),
                            ft.Text("Ferramentas do assistente", weight=ft.FontWeight.BOLD, size=13),
                            ft.Text("Selecione quais ações a IA pode executar no Redmine e localmente.", size=11, color=ft.Colors.GREY),
                            *blocos_ferramentas,
                            ft.Row([self.btn_testar, self.btn_salvar], spacing=10),
                            self.lbl_status_config,
                        ],
                        spacing=10,
                    ),
                    padding=16,
                )
            ],
            expand=True,
            spacing=8,
        )

    def btn_atualizar(self):
        return ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Atualizar lista", on_click=self._carregar_async)

    # ============================================================ abas
    def _trocar_aba(self, e):
        self._renderizar_abate(int(e.control.selected_index))

    def _renderizar_abate(self, indice: int):
        self.aba_atual = indice
        self.conteudo.controls.clear()
        if indice == 0:
            self.conteudo.controls.append(self.view_atividades)
        elif indice == 1:
            self.conteudo.controls.append(self.view_assistente)
        else:
            self.conteudo.controls.append(self.view_config)
        self.page.update()

    def _trocar_para_aba(self, indice: int):
        self.navbar.selected_index = indice
        self._renderizar_abate(indice)

    # ============================================================ atividades
    async def _carregar_async(self, e=None):
        self.lbl_carregando.value = "Carregando atividades..."
        self.lbl_carregando.color = ft.Colors.GREY
        self.page.update()
        try:
            await asyncio.to_thread(self._carregar)
            self.lbl_carregando.value = f"{len(self.issues)} atividades ativas"
        except Exception as ex:
            self.lbl_carregando.value = f"Erro: {type(ex).__name__}: {ex}"
            self.lbl_carregando.color = ft.Colors.RED
        finally:
            self._render_lista()
            self.page.update()

    def _carregar(self):
        if self.api is None:
            creds = {
                "site": self.config.get("site"),
                "api_key": self.config.get("api_key"),
                "login": self.config.get("login"),
                "senha": self.config.get("senha"),
            }
            self.api = RedmineAPI(credenciais=creds if creds.get("site") else None)

        usuario = self.api.get_usuario_atual()
        nome = " ".join(x for x in [usuario.get("firstname"), usuario.get("lastname")] if x)
        self.issues = self.api.get_issues_ativas()
        self.issues.sort(key=lambda i: i.get("id", 0), reverse=True)
        self.lbl_usuario.value = f"{nome or self.api.login} · {len(self.issues)} ativas"
        self.filtrados = list(self.issues)
        self.pagina = 0
        self._render_prioridades()

    def _filtrar(self, e=None):
        termo = self.busca.value.strip().lower()
        self.filtrados = [i for i in self.issues
                          if not termo or termo in str(i.get("id")) or termo in i.get("subject", "").lower()]
        self.pagina = 0
        self._render_lista()
        self.page.update()

    def _render_lista(self):
        self.lista.controls.clear()
        inicio = self.pagina * ITENS_POR_PAGINA
        fim = inicio + ITENS_POR_PAGINA
        itens_pagina = self.filtrados[inicio:fim]

        if not itens_pagina:
            self.lista.controls.append(ft.Text("Nenhuma atividade. Clique no ícone de atualizar para carregar.", color=ft.Colors.GREY))
        else:
            for issue in itens_pagina:
                self.lista.controls.append(self._card_atividade(issue))

        # paginação
        total_paginas = max(1, (len(self.filtrados) + ITENS_POR_PAGINA - 1) // ITENS_POR_PAGINA)
        self.row_paginacao.controls.clear()
        self.row_paginacao.controls.append(
            ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, disabled=self.pagina == 0, on_click=lambda e: self._mudar_pagina(-1))
        )
        self.row_paginacao.controls.append(ft.Text(f"{self.pagina + 1} / {total_paginas}", size=12))
        self.row_paginacao.controls.append(
            ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, disabled=self.pagina >= total_paginas - 1, on_click=lambda e: self._mudar_pagina(1))
        )

    def _mudar_pagina(self, delta):
        total_paginas = max(1, (len(self.filtrados) + ITENS_POR_PAGINA - 1) // ITENS_POR_PAGINA)
        nova = self.pagina + delta
        if 0 <= nova < total_paginas:
            self.pagina = nova
            self._render_lista()
            self.page.update()

    def _card_atividade(self, issue: dict) -> ft.Container:
        status = (issue.get("status") or {}).get("name", "")
        cor = CORES_STATUS.get(status, ft.Colors.GREY_300)
        versao = (issue.get("fixed_version") or {}).get("name", "") or "sem sprint"
        projeto = (issue.get("project") or {}).get("name", "")
        done = issue.get("done_ratio", 0)

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(ft.Text(status, size=10, weight=ft.FontWeight.BOLD), bgcolor=cor, border_radius=6, padding=ft.Padding(4, 8, 4, 8)),
                            ft.Text(f"[{versao}]", size=10, color=ft.Colors.GREY),
                            ft.Container(expand=True),
                            ft.Text(f"{done}%", size=11, color=ft.Colors.GREY),
                        ],
                        spacing=6,
                    ),
                    ft.Text(f"#{issue.get('id')} · {issue.get('subject')}", size=13, weight=ft.FontWeight.W_500, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"{projeto} | {(issue.get('tracker') or {}).get('name','')}", size=10, color=ft.Colors.GREY, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Row(
                        [
                            ft.FilledButton("Lançar horas", icon=ft.Icons.TIMER, expand=True, on_click=lambda e, i=issue: self._abrir_lancamento(i)),
                            ft.OutlinedButton("Revisar IA", icon=ft.Icons.SMART_TOY, expand=True, on_click=lambda e, i=issue: self._abrir_revisao(i)),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=6,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=12,
            padding=10,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        )

    # ============================================================ lançamento
    def _abrir_lancamento(self, issue: dict):
        self.issue_selecionada = issue
        versoes = self.api.get_versions((issue.get("project") or {}).get("id")) if self.api else []
        self.versoes_projeto = [v for v in versoes if v.get("status") != "locked"]

        status = (issue.get("status") or {}).get("name", "")
        done = issue.get("done_ratio", 0)

        self.cmb_status = ft.Dropdown(label="Status", options=[ft.DropdownOption(key=s, text=s) for s in STATUS_VALIDOS], value=status if status in STATUS_VALIDOS else None)
        self.slider_done = ft.Slider(min=0, max=100, divisions=10, value=done, label="{value}%", on_change=self._set_lbl_done)
        self.lbl_done = ft.Text(f"{int(done)}%")
        self.txt_horas = ft.TextField(label="Horas hoje", keyboard_type=ft.KeyboardType.NUMBER, hint_text="ex: 1.5", prefix_icon=ft.Icons.TIMER)
        self.txt_data = ft.TextField(label="Data (AAAA-MM-DD)", value=self.hoje)
        self.cmb_atividade = self._dropdown_atividades()
        self.txt_comentario = ft.TextField(label="Comentário", multiline=True, min_lines=2, max_lines=3)
        self.cmb_sprint = ft.Dropdown(label="Sprint/Versão", options=[ft.DropdownOption(key=str(v["id"]), text=v["name"]) for v in self.versoes_projeto])
        if issue.get("fixed_version"):
            self.cmb_sprint.value = str(issue["fixed_version"].get("id"))
        self.txt_previsao = ft.TextField(label="Nova data prevista (AAAA-MM-DD)", hint_text="opcional")
        if issue.get("due_date"):
            self.txt_previsao.value = issue.get("due_date")
        self.lbl_ia_bs = ft.Text("", size=11, color=ft.Colors.BLUE_GREY)

        conteudo = ft.Container(
            ft.Column(
                [
                    ft.Row([ft.Icon(ft.Icons.TIMER), ft.Text(f"Lançar horas · #{issue.get('id')}", weight=ft.FontWeight.BOLD, size=15)]),
                    ft.Text(issue.get("subject", ""), size=12, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Divider(height=4),
                    ft.Row([self.cmb_status, self.txt_horas], spacing=8),
                    self.slider_done,
                    self.lbl_done,
                    self.txt_comentario,
                    self.txt_data,
                    self.cmb_atividade,
                    self.cmb_sprint,
                    self.txt_previsao,
                    self.lbl_ia_bs,
                    ft.Row(
                        [
                            ft.OutlinedButton("Sugerir IA", icon=ft.Icons.AUTO_AWESOME, on_click=lambda e: self.page.run_task(self._sugerir_async)),
                            ft.Container(expand=True),
                            ft.FilledButton("Lançar", icon=ft.Icons.CHECK, on_click=lambda e: self._confirmar_lancamento_bs()),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=16,
        )

        bs = ft.BottomSheet(content=conteudo, show_drag_handle=True, open=True, on_dismiss=self._fechar_sheet)
        self.page.overlay.append(bs)
        self.page.update()

    def _set_lbl_done(self, e=None):
        self.lbl_done.value = f"{int(self.slider_done.value)}%"
        self.page.update()

    def _dropdown_atividades(self):
        try:
            ativs = self.api.get_time_entry_activities()
            ops = [ft.DropdownOption(key=str(a["id"]), text=a["name"]) for a in ativs]
            value = str(9) if any(str(a["id"]) == "9" for a in ativs) else None
        except Exception:
            ops = [ft.DropdownOption(key="9", text="Desenvolvimento")]
            value = "9"
        return ft.Dropdown(label="Atividade apontamento", options=ops, value=value)

    async def _sugerir_async(self, e=None):
        self.lbl_ia_bs.value = "Gerando sugestão..."
        self.page.update()
        try:
            sugestao = await asyncio.to_thread(self.ollama.gerar_sugestao, self.issue_selecionada, False)
            self._aplicar_sugestao_bs(sugestao)
            self.lbl_ia_bs.value = "Sugestão aplicada. Revise antes de lançar."
            self.lbl_ia_bs.color = ft.Colors.GREEN
        except Exception as ex:
            self.lbl_ia_bs.value = f"Erro: {type(ex).__name__}: {ex}"
            self.lbl_ia_bs.color = ft.Colors.RED
        self.page.update()

    def _aplicar_sugestao_bs(self, s: dict):
        try:
            horas = s.get("horas_sugeridas")
            if horas not in (None, ""):
                self.txt_horas.value = str(float(horas))
        except (TypeError, ValueError):
            pass
        pct = s.get("percentual")
        if isinstance(pct, (int, float)) and 0 <= float(pct) <= 100:
            self.slider_done.value = float(pct)
            self.lbl_done.value = f"{int(pct)}%"
        status = s.get("status")
        if status and status in STATUS_VALIDOS:
            self.cmb_status.value = status
        if s.get("previsao"):
            self.txt_previsao.value = str(s["previsao"])
        if s.get("comentario"):
            self.txt_comentario.value = str(s["comentario"])

    def _confirmar_lancamento_bs(self):
        if not self.issue_selecionada:
            return
        issue = self.issue_selecionada
        issue_id = issue["id"]
        try:
            horas = float(self.txt_horas.value.strip()) if self.txt_horas.value.strip() else 0.0
        except ValueError:
            self.lbl_ia_bs.value = "Horas inválidas."
            self.lbl_ia_bs.color = ft.Colors.RED
            self.page.update()
            return
        if horas <= 0:
            self.lbl_ia_bs.value = "Informe horas > 0."
            self.lbl_ia_bs.color = ft.Colors.RED
            self.page.update()
            return

        sheet = self._sheet_aberta()
        if sheet:
            sheet.open = False
        self.page.update()
        novo_status = self.cmb_status.value
        novo_done = int(self.slider_done.value)
        comentario = self.txt_comentario.value.strip()
        data_ap = self.txt_data.value.strip() or self.hoje
        previsao = self.txt_previsao.value.strip() or None
        sprint_id = self.cmb_sprint.value
        atividade_id = self.cmb_atividade.value

        try:
            payload = {}
            status_ids = self.api.get_status_ids()
            if novo_status:
                if novo_status not in status_ids:
                    raise ValueError(f"Status '{novo_status}' não encontrado no Redmine.")
                atual = (issue.get("status") or {}).get("name")
                if novo_status != atual:
                    payload["status_id"] = status_ids[novo_status]
            payload["done_ratio"] = novo_done
            if previsao:
                payload["due_date"] = previsao
            if sprint_id:
                payload["fixed_version_id"] = int(sprint_id)
            if payload:
                self.api.atualizar_issue(issue_id, **payload)
            self.api.lancar_horas(issue_id, horas, comentario, data_ap, activity_id=int(atividade_id) if atividade_id else None)
            self._notificar(f"Lançado {horas}h em #{issue_id} ✓")
            self._atualizar_dados_locais(issue_id, novo_done, novo_status, previsao, sprint_id)
        except Exception as ex:
            self._notificar(f"Erro ao lançar #{issue_id}: {ex}")

    def _sheet_aberta(self):
        for c in self.page.overlay:
            if isinstance(c, ft.BottomSheet):
                return c
        return None

    def _fechar_sheet(self, e=None):
        for c in list(self.page.overlay):
            if isinstance(c, ft.BottomSheet):
                c.open = False
        self.page.update()

    # ============================================================ revisão IA
    @staticmethod
    def _chip(texto: str, cor_bg, cor_fg) -> ft.Container:
        return ft.Container(
            ft.Text(texto, size=11, weight=ft.FontWeight.BOLD, color=cor_fg),
            bgcolor=cor_bg,
            border_radius=8,
            padding=ft.Padding(8, 4, 8, 4),
        )

    def _chip_sugestao(self, texto: str, icone) -> ft.Container:
        return ft.Container(
            ft.Row(
                [
                    ft.Icon(icone, size=15, color=ft.Colors.INDIGO),
                    ft.Text(texto, size=12, weight=ft.FontWeight.W_500, color=ft.Colors.INDIGO),
                ],
                spacing=5,
            ),
            bgcolor=ft.Colors.INDIGO_50 if hasattr(ft.Colors, "INDIGO_50") else ft.Colors.SURFACE_CONTAINER_HIGH,
            border_radius=16,
            padding=ft.Padding(12, 7, 12, 7),
            border=ft.Border.all(1, ft.Colors.INDIGO_200 if hasattr(ft.Colors, "INDIGO_200") else ft.Colors.OUTLINE_VARIANT),
            on_click=lambda e, t=texto: self.page.run_task(self._perguntar_sugerido, t),
        )

    def _abrir_revisao(self, issue: dict):
        self.issue_selecionada = issue
        self.em_revisao = True

        self.chat_msgs = ft.Column(spacing=12, expand=True, scroll=ft.ScrollMode.AUTO)
        self.chat_input = ft.TextField(
            label="Pergunte ao gerente...",
            hint_text="Digite sua dúvida ou peça orientação",
            expand=True,
            multiline=True,
            min_lines=1,
            max_lines=4,
            border_radius=18,
            prefix_icon=ft.Icons.FORUM,
            on_submit=lambda e: self.page.run_task(self._enviar_chat),
        )
        self.btn_iniciar = ft.FilledButton(
            "Analisar",
            icon=ft.Icons.AUTO_AWESOME,
            on_click=lambda e: self.page.run_task(self._revisar_inicial),
        )
        self.btn_enviar = ft.IconButton(
            icon=ft.Icons.SEND,
            icon_color=ft.Colors.ON_PRIMARY,
            bgcolor=ft.Colors.PRIMARY,
            tooltip="Enviar",
            on_click=lambda e: self.page.run_task(self._enviar_chat),
        )
        self.historico_chat = []
        self.prompt_sistema = None

        # Estado vazio (antes da análise)
        self.sugestoes = ft.Row(
            [
                self._chip_sugestao("Sugerir horas", ft.Icons.TIMER),
                self._chip_sugestao("Riscos", ft.Icons.WARNING_AMBER),
                self._chip_sugestao("Prioridade", ft.Icons.FLAG),
                self._chip_sugestao("Sprint ok?", ft.Icons.LIST_ALT),
            ],
            spacing=6,
            wrap=True,
        )
        self.estado_vazio = ft.Container(
            ft.Column(
                [
                    ft.Icon(ft.Icons.SMART_TOY, size=56, color=ft.Colors.INDIGO_100),
                    ft.Text("Especialista em Projetos", size=17, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE),
                    ft.Text("Ágil · Scrum · PMBOK", size=12, color=ft.Colors.INDIGO, weight=ft.FontWeight.W_500),
                    ft.Text(
                        "Analisando a atividade automaticamente... você pode tocar em uma "
                        "sugestão ou digitar para aprofundar.",
                        size=12,
                        color=ft.Colors.GREY,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            ),
            padding=ft.Padding(20, 12, 20, 12),
        )
        self.chat_msgs.controls.append(self.estado_vazio)

        status = (issue.get("status") or {}).get("name", "")
        cor_status = CORES_STATUS.get(status, ft.Colors.GREY_300)
        done = issue.get("done_ratio", 0)
        versao = (issue.get("fixed_version") or {}).get("name", "")
        projeto = (issue.get("project") or {}).get("name", "")

        # Barra de app (top) estilo Android
        appbar = ft.Container(
            ft.Row(
                [
                    ft.IconButton(icon=ft.Icons.ARROW_BACK, tooltip="Voltar", on_click=self._fechar_revisao),
                    ft.Container(
                        ft.Icon(ft.Icons.SMART_TOY, color=ft.Colors.WHITE),
                        bgcolor=ft.Colors.INDIGO,
                        border_radius=12,
                        padding=ft.Padding(8, 8, 8, 8),
                    ),
                    ft.Column(
                        [
                            ft.Text("Especialista em Projetos", weight=ft.FontWeight.BOLD, size=16, color=ft.Colors.ON_SURFACE),
                            ft.Text(f"#{issue.get('id')} · {projeto}", size=11, color=ft.Colors.GREY, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ],
                        spacing=0,
                        expand=True,
                    ),
                ],
                spacing=8,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            padding=ft.Padding(8, 6, 8, 6),
        )

        assunto = ft.Text(
            issue.get("subject", ""),
            size=14,
            weight=ft.FontWeight.W_600,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
        )

        chips = ft.Row(
            [
                self._chip(status, cor_status, ft.Colors.ON_SURFACE) if status else ft.Container(),
                self._chip(f"{done}% concluído", ft.Colors.SURFACE_CONTAINER_HIGHEST, ft.Colors.ON_SURFACE),
                self._chip(versao if versao else "sem sprint", ft.Colors.SURFACE_CONTAINER_HIGH, ft.Colors.ON_SURFACE),
            ],
            spacing=6,
            wrap=True,
        )

        descricao = ft.ExpansionTile(
            title=ft.Row([ft.Icon(ft.Icons.DESCRIPTION, size=18, color=ft.Colors.GREY), ft.Text("Ver descrição da atividade", size=12, color=ft.Colors.GREY)]),
            controls=[ft.Markdown((issue.get("description") or "Sem descrição."), selectable=True, auto_follow_links=True)],
            shape=ft.RoundedRectangleBorder(radius=10),
            collapsed_shape=ft.RoundedRectangleBorder(radius=10),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            collapsed_bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            expanded_cross_axis_alignment=ft.CrossAxisAlignment.START,
        )

        self.rodape = ft.Row(
            [
                self.chat_input,
                ft.Container(content=self.btn_enviar),
            ],
            spacing=8,
        )

        self.view_revisao = ft.Container(
            ft.Column(
                [
                    appbar,
                    ft.Container(
                        ft.Column(
                            [
                                assunto,
                                chips,
                                self.sugestoes,
                                descricao,
                                ft.Container(ft.Divider(height=1), padding=ft.Padding(0, 6, 0, 6)),
                            ],
                            spacing=8,
                        ),
                        padding=ft.Padding(16, 8, 16, 0),
                    ),
                    self.chat_msgs,
                    ft.Container(self.rodape, padding=ft.Padding(16, 8, 16, 12), bgcolor=ft.Colors.SURFACE),
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
            bgcolor=ft.Colors.SURFACE,
        )

        # Mostra a tela cheia (esconde a navegação inferior)
        self.navbar.visible = False
        self.conteudo.controls.clear()
        self.conteudo.controls.append(self.view_revisao)
        self.page.update()

        # Inicia a análise automaticamente
        self.page.run_task(self._revisar_inicial)

    def _fechar_revisao(self, e=None):
        self.em_revisao = False
        self.navbar.visible = True
        self.navbar.selected_index = self.aba_atual
        self._renderizar_abate(self.aba_atual)
        self.page.update()

    @staticmethod
    def _adicionar_mensagem(coluna: ft.Column, autor: str, texto: str):
        if autor == "você":
            balao = ft.Container(
                ft.Text(texto, size=13, color=ft.Colors.ON_PRIMARY, selectable=True),
                bgcolor=ft.Colors.PRIMARY,
                border_radius=12,
                padding=ft.Padding(10, 8, 10, 8),
            )
            linha = ft.Row([ft.Container(expand=True), balao], spacing=0)
            coluna.controls.append(linha)
        else:
            balao = ft.Container(
                ft.Markdown(
                    texto,
                    selectable=True,
                    auto_follow_links=True,
                    extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                ),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                border_radius=12,
                padding=ft.Padding(10, 8, 10, 8),
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            )
            coluna.controls.append(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.SMART_TOY, size=14, color=ft.Colors.PURPLE_400),
                                ft.Text("Gerente Ágil", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY),
                            ],
                            spacing=4,
                        ),
                        balao,
                    ],
                    spacing=4,
                )
            )

    async def _perguntar_sugerido(self, texto: str):
        """Envia uma pergunta pré-definida ao chat (sugestão)."""
        self.chat_input.value = texto
        await self._enviar_chat()

    async def _revisar_inicial(self):
        self.btn_iniciar.disabled = True
        self.chat_input.disabled = True
        self.btn_enviar.disabled = True
        self._set_loading(True)
        self.page.update()
        self.prompt_sistema = (
            "Você é um Especialista em Gestão de Projetos, com profundo domínio de "
            "Metodologias Ágeis (Scrum) e PMBOK. Atue como Gerente de Projetos Ágil "
            "do desenvolvedor, avaliando a atividade como um especialista. Sempre que "
            "possível, relacione sua orientação a práticas de Scrum (sprint, Definition "
            "of Done, cerimônias, backlog) e/ou áreas do PMBOK (escopo, tempo, risco, "
            "qualidade, comunicação). Dê respostas objetivas e práticas em português, "
            "estruturadas em Markdown, cobrindo: estimativa de horas, análise de risco, "
            "se o status/percentual estão coerentes, se a sprint é adequada e próximos passos."
        )
        mensagem = (
            f"Analise esta atividade como especialista em projetos (Ágil+Scrum+PMBOK):\n"
            f"ID #{self.issue_selecionada.get('id')}\n"
            f"Projeto: {(self.issue_selecionada.get('project') or {}).get('name','')}\n"
            f"Assunto: {self.issue_selecionada.get('subject')}\n"
            f"Descrição: {(self.issue_selecionada.get('description') or '')[:1500]}\n"
            f"Status: {(self.issue_selecionada.get('status') or {}).get('name','')} · %: {self.issue_selecionada.get('done_ratio',0)}\n"
            f"Sprint: {(self.issue_selecionada.get('fixed_version') or {}).get('name','') or '—'}\n"
            f"Estimadas: {self.issue_selecionada.get('estimated_hours') or '—'} · Gastas: {self.issue_selecionada.get('spent_hours',0)}\n\n"
            "Forneça: (1) veredito rápido; (2) sugestão de horas; (3) riscos; "
            "(4) recomendação de status/% e sprint; (5) próximo passo recomendado."
        )
        try:
            resposta = await asyncio.to_thread(self.ollama.chat, mensagem, [], self.prompt_sistema)
            self._add_chat("gerente", resposta)
        except Exception as ex:
            self._add_chat("gerente", f"**Erro ao analisar:** {ex}")
        self._set_loading(False)
        self.chat_input.disabled = False
        self.btn_enviar.disabled = False
        self.page.update()

    async def _enviar_chat(self):
        mensagem = self.chat_input.value.strip()
        if not mensagem:
            return
        self._add_chat("você", mensagem)
        self.chat_input.value = ""
        self.chat_input.disabled = True
        self.btn_enviar.disabled = True
        self._set_loading(True)
        self.page.update()
        try:
            resposta = await asyncio.to_thread(self.ollama.chat, mensagem, self.historico_chat, self.prompt_sistema)
            self._add_chat("gerente", resposta)
        except Exception as ex:
            self._add_chat("gerente", f"**Erro:** {ex}")
        self._set_loading(False)
        self.chat_input.disabled = False
        self.btn_enviar.disabled = False
        self.page.update()

    def _set_loading(self, ativo: bool):
        if ativo:
            self.rodape.controls.pop(1)
            self.rodape.controls.append(
                ft.Row([ft.ProgressRing(width=20, height=20), ft.Text("Gerando...", size=12, color=ft.Colors.GREY)], spacing=8)
            )
        else:
            self.rodape.controls.pop(1)
            self.rodape.controls.append(
                ft.Container(content=self.btn_enviar if self.historico_chat else self.btn_iniciar)
            )

    def _add_chat(self, autor: str, texto: str):
        self.historico_chat.extend(
            [{"role": "user" if autor == "você" else "assistant", "content": texto}]
        )
        # remove o estado vazio e as sugestões após a primeira interação
        if self.estado_vazio in self.chat_msgs.controls:
            self.chat_msgs.controls.remove(self.estado_vazio)
        if self.sugestoes.visible:
            self.sugestoes.visible = False
        self._adicionar_mensagem(self.chat_msgs, autor, texto)
        self.btn_enviar.visible = bool(self.historico_chat)
        self.btn_iniciar.visible = not bool(self.historico_chat)
        self.page.update()
        try:
            import time
            time.sleep(0.05)
            self.chat_msgs.scroll_to(offset=-1, duration=200)
        except Exception:
            pass

    # ============================================================ assistente (chat global)
    def _btn_limpar_historico(self) -> ft.IconButton:
        return ft.IconButton(icon=ft.Icons.DELETE_SWEEP, tooltip="Limpar histórico do assistente", on_click=self._limpar_historico_assistente)

    def _limpar_historico_assistente(self, e=None):
        self._esconder_digitando()
        adb.limpar_historico("geral")
        self.asst_historico = []
        self.asst_msgs.controls.clear()
        self._add_asst_msg("assistente", "Histórico limpo. Como posso ajudar com suas atividades hoje?")
        self.page.update()

    def _add_asst_msg(self, autor: str, texto: str):
        if autor == "você":
            balao = ft.Container(
                ft.Text(texto, size=13, color=ft.Colors.ON_PRIMARY, selectable=True),
                bgcolor=ft.Colors.PRIMARY,
                border_radius=12,
                padding=ft.Padding(10, 8, 10, 8),
            )
            self.asst_msgs.controls.append(ft.Row([ft.Container(expand=True), balao], spacing=0))
        else:
            balao = ft.Container(
                ft.Markdown(
                    texto,
                    selectable=True,
                    auto_follow_links=True,
                    extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                ),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                border_radius=12,
                padding=ft.Padding(10, 8, 10, 8),
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            )
            self.asst_msgs.controls.append(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.SMART_TOY, size=14, color=ft.Colors.PURPLE_400),
                                ft.Text("Assistente", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY),
                            ],
                            spacing=4,
                        ),
                        balao,
                    ],
                    spacing=4,
                )
            )
        try:
            self.asst_msgs.scroll_to(offset=-1, duration=150)
        except Exception:
            pass

    async def _pergunta_assistente(self, texto: str):
        self.asst_input.value = texto
        await self._enviar_assistente()

    def _carregar_historico_assistente(self):
        self.asst_historico = []
        self.asst_msgs.controls.clear()
        try:
            for m in adb.historico("geral"):
                self._add_asst_msg("assistente" if m["autor"] == "assistente" else "você", m["conteudo"])
        except Exception:
            pass
        if not self.asst_msgs.controls:
            self._add_asst_msg(
                "assistente",
                "Olá! Sou seu assistente pessoal de trabalho. Posso organizar suas "
                "atividades por prioridade, apontar as que estão em risco e lançar as "
                "horas trabalhadas direto no Redmine. Como posso ajudar?",
            )
        self._render_prioridades()
        self.page.update()

    def _render_prioridades(self):
        """Ordena as atividades carregadas pela prioridade salva localmente e exibe no painel."""
        self.asst_prioridades.controls.clear()
        pr = adb.prioridades()
        if not pr or not self.issues:
            self.asst_prioridades.controls.append(
                ft.Text("Pergunte ao assistente para organizar suas prioridades.", size=11, color=ft.Colors.GREY)
            )
            return
        ordenados = sorted(self.issues, key=lambda i: pr.get(i.get("id"), 9999))
        for i in ordenados[:15]:
            pid = i.get("id")
            info = pr.get(pid, {})
            nota = info.get("nota", "")
            self.asst_prioridades.controls.append(
                ft.Container(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Container(
                                        ft.Text(f"#{pid}", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                                        bgcolor=ft.Colors.INDIGO,
                                        border_radius=6,
                                        padding=ft.Padding(6, 2, 6, 2),
                                    ),
                                    ft.Text(i.get("subject", ""), size=12, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text(f"{(i.get('status') or {}).get('name','')}", size=10, color=ft.Colors.GREY),
                                ],
                                spacing=6,
                            ),
                            ft.Text(nota, size=10, color=ft.Colors.BLUE_GREY) if nota else ft.Container(),
                        ],
                        spacing=2,
                    ),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    border_radius=10,
                    padding=8,
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                )
            )
        self.page.update()

    def _executar_acoes(self, acoes: list):
        """Executa as ações solicitadas pelo assistente conforme as ferramentas habilitadas."""
        habilitadas = set(self.config.get("ferramentas_habilitadas") or [])
        # ferramentas locais não precisam de API
        locais = {t["id"] for t in TOOLS if not t.get("requer_redmine")}
        precisa_api = any(
            isinstance(a, dict) and (a.get("acao") or a.get("tipo")) in habilitadas - locais
            for a in acoes
        )
        if precisa_api and (self.api is None):
            creds = {
                "site": self.config.get("site"),
                "api_key": self.config.get("api_key"),
                "login": self.config.get("login"),
                "senha": self.config.get("senha"),
            }
            if not (creds.get("site") and creds.get("api_key")):
                return "Não configurado: informe URL e API key do Redmine na aba Configuração."
            self.api = RedmineAPI(credenciais=creds)

        avisos = []
        for item in acoes:
            if not isinstance(item, dict):
                continue
            acao = item.get("acao") or item.get("tipo")
            if acao not in habilitadas:
                avisos.append(f"⚠️ Ferramenta '{acao}' desabilitada — ação ignorada.")
                continue
            dados = item.get("dados") or {}
            try:
                msg = self._processar_acao(acao, dados)
                if msg:
                    avisos.append(msg)
            except Exception as ex:
                avisos.append(f"❌ Ação '{acao}' falhou: {ex}")
        return "\n".join(avisos)

    def _processar_acao(self, acao: str, dados: dict) -> str:
        """Executa uma ação individual e retorna mensagem de resultado (ou '')."""
        if acao in ("definir_prioridade", "salvar_nota"):
            return self._acao_local(acao, dados)
        return self._acao_redmine(acao, dados)

    def _acao_local(self, acao: str, dados: dict) -> str:
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

    def _acao_redmine(self, acao: str, dados: dict) -> str:
        api = self.api
        if acao == "lancar_horas":
            issue_id = int(dados.get("issue_id"))
            horas = float(dados.get("horas"))
            comentario = str(dados.get("comentario") or "")
            data = str(dados.get("data") or self.hoje)
            if horas <= 0:
                return f"⚠️ Horas inválidas (<=0) para #{issue_id}."
            api.lancar_horas(issue_id, horas, comentario, data)
            return f"✅ Lançadas {horas}h em #{issue_id} no Redmine."
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
            data = str(dados.get("data") or "")
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
            lista = api.get_issues_ativas()
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

    # ============================================================ indicador "digitando"
    def _mostrar_digitando(self):
        """Adiciona um balão com 3 pontos animados (estilo WhatsApp) indicando que a IA está trabalhando."""
        if self.asst_digitando_ativo:
            return
        self.asst_digitando_ativo = True

        cor = ft.Colors.PRIMARY
        pontos = []
        for _ in range(3):
            pontos.append(
                ft.Container(
                    width=8,
                    height=8,
                    bgcolor=cor,
                    border_radius=ft.BorderRadius.all(4),
                    animate_opacity=ft.Animation(300, ft.AnimationCurve.EASE_IN_OUT),
                    opacity=0.3,
                )
            )

        balao = ft.Container(
            ft.Row(pontos, spacing=5, alignment=ft.MainAxisAlignment.CENTER),
            width=60,
            height=34,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            border_radius=ft.BorderRadius.all(16),
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        )
        self.asst_digitando_col = ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.SMART_TOY, size=14, color=ft.Colors.PURPLE_400),
                        ft.Text("Assistente", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY),
                    ],
                    spacing=4,
                ),
                balao,
                ft.Text("Digitando...", size=10, color=ft.Colors.GREY),
            ],
            spacing=3,
        )
        self.asst_msgs.controls.append(self.asst_digitando_col)
        self.page.update()
        try:
            self.asst_msgs.scroll_to(offset=-1, duration=150)
        except Exception:
            pass

        async def animar():
            while self.asst_digitando_ativo:
                for indice in range(3):
                    for j, p in enumerate(pontos):
                        alvo = 1.0 if j == indice else 0.3
                        if p.opacity != alvo:
                            p.opacity = alvo
                    self.page.update()
                    try:
                        self.asst_msgs.scroll_to(offset=-1, duration=100)
                    except Exception:
                        pass
                    await asyncio.sleep(0.18)

        self._digitando_task = asyncio.ensure_future(animar())

    def _esconder_digitando(self):
        """Remove o balão de 'digitando' e encerra a animação."""
        self.asst_digitando_ativo = False
        if self._digitando_task is not None:
            self._digitando_task.cancel()
            self._digitando_task = None
        if self.asst_digitando_col is not None:
            try:
                self.asst_digitando_col.controls.clear()
            except Exception:
                pass
            if self.asst_digitando_col in self.asst_msgs.controls:
                self.asst_msgs.controls.remove(self.asst_digitando_col)
            self.asst_digitando_col = None
            self.page.update()

    async def _enviar_assistente(self, e=None):
        mensagem = self.asst_input.value.strip()
        if not mensagem:
            return
        self._add_asst_msg("você", mensagem)
        self.asst_historico.append({"role": "user", "content": mensagem})
        adb.salvar_mensagem("você", mensagem)
        self.asst_input.value = ""
        self.asst_input.disabled = True
        self.asst_btn_enviar.disabled = True
        self.asst_lbl_status.value = ""
        self._mostrar_digitando()
        self.page.update()
        try:
            prioridades = adb.prioridades()
            notas = adb.notas()
            resultado = await asyncio.to_thread(
                self.ollama.chat_assistente,
                mensagem,
                self.issues,
                prioridades,
                notas,
                self.asst_historico,
                self.config.get("ferramentas_habilitadas"),
            )
            resposta = resultado.get("resposta", "")
            acoes = resultado.get("acoes", [])

            linhas = [resposta]
            if acoes:
                relatorio = await asyncio.to_thread(self._executar_acoes, acoes)
                if relatorio:
                    linhas.append(relatorio)
                    if "Lançadas" in relatorio or "Prioridade" in relatorio:
                        self._notificar(relatorio.splitlines()[0])
            texto_final = "\n\n".join(x for x in linhas if x)

            self._esconder_digitando()
            self._add_asst_msg("assistente", texto_final)
            self.asst_historico.append({"role": "assistant", "content": texto_final})
            adb.salvar_mensagem("assistente", texto_final)
            self._render_prioridades()
            self.asst_lbl_status.value = ""
        except Exception as ex:
            self._esconder_digitando()
            self._add_asst_msg("assistente", f"**Erro:** {type(ex).__name__}: {ex}")
            self.asst_lbl_status.value = "Erro ao consultar assistente."
            self.asst_lbl_status.color = ft.Colors.RED
        self.asst_input.disabled = False
        self.asst_btn_enviar.disabled = False
        self.page.update()

    # ============================================================ config
    def _ler_config_llm(self) -> dict:
        """Lê os campos LLM da tela de configuração e devolve um dicionário de config."""
        try:
            temp = float(self.txt_llm_temp.value.strip()) if self.txt_llm_temp.value.strip() else 0.4
        except ValueError:
            temp = 0.4
        if not (0.0 <= temp <= 2.0):
            temp = 0.4
        try:
            max_tokens = int(self.txt_llm_max_tokens.value.strip()) if self.txt_llm_max_tokens.value.strip() else ""
        except ValueError:
            max_tokens = ""
        return {
            "llm_provider": self.cmb_provider.value or "ollama",
            "llm_api_key": self.txt_llm_api_key.value.strip(),
            "llm_url": self.txt_llm_url.value.strip(),
            "llm_model": self.txt_llm_model.value.strip(),
            "llm_temperature": temp,
            "llm_max_tokens": str(max_tokens) if isinstance(max_tokens, int) else "",
            "llm_prompt_system": self.txt_llm_prompt_system.value,
        }

    def _mudar_provider(self, e=None):
        """Atualiza URL/modelo sugeridos ao trocar de provedor."""
        prov = self.cmb_provider.value or "ollama"
        meta = PROVIDERS.get(prov, PROVIDERS["ollama"])
        # Se o campo URL está vazio ou igual ao padrão do provedor anterior, aplica o novo padrão
        self.txt_llm_url.value = self.txt_llm_url.value.strip() or meta["default_url"]
        self.txt_llm_model.value = self.txt_llm_model.value.strip() or meta["default_model"]
        self._atualizar_campos_llm()
        self.page.update()

    def _atualizar_campos_llm(self, initial: bool = False):
        """Habilita/desabilita e preenche campos conforme o provedor selecionado."""
        prov = self.cmb_provider.value or "ollama"
        meta = PROVIDERS.get(prov, PROVIDERS["ollama"])
        if initial:
            # preenche a partir da config salva
            return
        url_atual = self.txt_llm_url.value.strip()
        modelo_atual = self.txt_llm_model.value.strip()
        if not url_atual:
            self.txt_llm_url.value = meta["default_url"]
        if not modelo_atual:
            self.txt_llm_model.value = meta["default_model"]

    def _construir_cliente_llm(self) -> OllamaClient:
        prov = self.config.get("llm_provider", "ollama")
        meta = PROVIDERS.get(prov, PROVIDERS["ollama"])
        url = self.config.get("llm_url") or meta["default_url"]
        modelo = self.config.get("llm_model") or meta["default_model"]
        try:
            temp = float(self.config.get("llm_temperature", 0.4))
        except (TypeError, ValueError):
            temp = 0.4
        try:
            mt = self.config.get("llm_max_tokens") or ""
            max_tokens = int(mt) if str(mt).strip() else None
        except (TypeError, ValueError):
            max_tokens = None
        return OllamaClient(
            base_url=url,
            modelo=modelo,
            provider=prov,
            api_key=self.config.get("llm_api_key", ""),
            temperature=temp,
            max_tokens=max_tokens,
            prompt_system=self.config.get("llm_prompt_system", ""),
        )

    async def _testar_async(self, e=None):
        self.lbl_status_config.value = "Testando conexão..."
        self.lbl_status_config.color = ft.Colors.GREY
        self.page.update()
        # testa o Redmine
        try:
            site = self.txt_site.value.strip()
            api_key = self.txt_apikey.value.strip()
            if site and api_key:
                api = RedmineAPI(credenciais={"site": site, "api_key": api_key, "login": self.txt_login.value, "senha": self.txt_senha.value})
                usuario = await asyncio.to_thread(api.get_usuario_atual)
                nome = f"{usuario.get('firstname','')} {usuario.get('lastname','')}".strip()
                self.lbl_status_config.value = f"Redmine: {nome} ({usuario.get('login')}) ✓"
                self.lbl_status_config.color = ft.Colors.GREEN
            else:
                self.lbl_status_config.value = "Redmine: informe URL e API key (opcional p/ este teste)."
        except Exception as ex:
            self.lbl_status_config.value = f"Redmine: {type(ex).__name__}: {ex}"
            self.lbl_status_config.color = ft.Colors.RED
        self.page.update()
        await asyncio.sleep(0.1)
        # testa o LLM
        self.lbl_status_config.value = self.lbl_status_config.value + " | Testando IA..."
        self.lbl_status_config.color = ft.Colors.GREY
        self.page.update()
        try:
            cfg_llm = self._ler_config_llm()
            cliente = OllamaClient(
                base_url=cfg_llm.get("llm_url") or None,
                modelo=cfg_llm.get("llm_model") or None,
                provider=cfg_llm.get("llm_provider", "ollama"),
                api_key=cfg_llm.get("llm_api_key", ""),
                temperature=cfg_llm.get("llm_temperature", 0.4),
                max_tokens=int(cfg_llm.get("llm_max_tokens")) if str(cfg_llm.get("llm_max_tokens", "")).strip() else None,
            )
            texto = await asyncio.to_thread(cliente._chat, "Responda apenas: ok", timeout=60)
            if texto.strip():
                self.lbl_status_config.value = f"Redmine ✓ | IA ({cfg_llm.get('llm_provider').upper()}): conectado ✓"
                self.lbl_status_config.color = ft.Colors.GREEN
            else:
                self.lbl_status_config.value = "Redmine ✓ | IA conectou, mas retornou resposta vazia."
        except Exception as ex:
            self.lbl_status_config.value = f"Redmine ✓ (se config.) | IA falhou: {type(ex).__name__}: {ex}"
            self.lbl_status_config.color = ft.Colors.RED
        self.page.update()

    def _salvar_config(self, e=None):
        self.config.update({
            "site": self.txt_site.value.strip(),
            "login": self.txt_login.value.strip(),
            "senha": self.txt_senha.value.strip(),
            "api_key": self.txt_apikey.value.strip(),
        })
        self.config.update(self._ler_config_llm())
        self.config["ferramentas_habilitadas"] = [
            t_id for t_id, chk in self._chk_ferramentas.items() if chk.value
        ]
        salvar_config(self.config)
        self.ollama = self._construir_cliente_llm()
        self.api = None
        self.lbl_status_config.value = "Configurações salvas. Clique em Atualizar na aba Atividades."
        self.lbl_status_config.color = ft.Colors.GREEN
        self.page.update()

    # ============================================================ auxiliares
    def _notificar(self, texto: str):
        snack = ft.SnackBar(ft.Text(texto), open=True, duration=3000)
        self.page.overlay.append(snack)
        self.page.update()

    def _atualizar_dados_locais(self, issue_id, novo_done, novo_status, previsao, sprint_id):
        for issue in self.issues:
            if issue.get("id") == issue_id:
                issue["done_ratio"] = novo_done
                if novo_status:
                    issue["status"] = {"name": novo_status}
                if previsao:
                    issue["due_date"] = previsao
                if sprint_id:
                    nova = next((v for v in self.versoes_projeto if str(v.get("id")) == str(sprint_id)), None)
                    if nova:
                        issue["fixed_version"] = {"id": nova["id"], "name": nova["name"]}
                break
        self._render_lista()


def main(page: ft.Page):
    # Tamanho responsivo: usa a janela do desktop (Windows/Linux), com uma largura
    # mínima semelhante a um app mobile para o layout Android ficar consistente.
    try:
        if page.window.width and page.window.width > 0:
            page.window.width = max(page.window.width, 420)
        else:
            page.window.width = 430
        if page.window.height and page.window.height > 0:
            page.window.height = max(page.window.height, 700)
        else:
            page.window.height = 820
    except Exception:
        page.window.width = 430
        page.window.height = 820
    App(page)


if __name__ == "__main__":
    ft.run(main)
