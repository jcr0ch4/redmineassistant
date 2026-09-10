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
import sys
from collections import Counter
from datetime import date

import flet as ft

import assistente_db as adb
import debug_log
from acoes import ExecutorDeAcoes
from config_manager import DEFAULT_KANBAN_COLUNAS, carregar_config, salvar_config
from ferramentas import TOOLS, TOOLS_POR_ID, categorias, ferramentas_por_categoria, requer_confirmacao
from logger_app import get_logger
from ollama_client import PROVIDERS, OllamaClient
from redmine_api import STATUS_ATIVOS, RedmineAPI, criar_api
from versao import APP_NOME, APP_VERSAO, APP_VERSAO_DISPLAY

LOGGER = get_logger("app")

STATUS_VALIDOS = ["Nova", "Backlog", "Especificação", "Em andamento", "Validação", "Encerrada", "Cancelada", "Suspensa"]
ITENS_POR_PAGINA = 6

# Cor de destaque principal do app (mesma do cesta-wbv)
COR_PRINCIPAL = ft.Colors.INDIGO_700

CORES_STATUS = {
    "Nova": ft.Colors.RED_200,
    "Em andamento": ft.Colors.AMBER_200,
    "Especificação": ft.Colors.GREEN_200,
    "Backlog": ft.Colors.BLUE_200,
}


class _EditorColuna:
    """Widget do editor de uma coluna do quadro kanban (tela de Configurações)."""

    def __init__(self, titulo: str | None, statuses: list | None, concluida: bool):
        self.txt_titulo = ft.TextField(value=titulo or "", hint_text="Nome da coluna", dense=True, expand=True)
        self.lbl_status = ft.Text("Status incluídos nesta coluna:", size=11, color=ft.Colors.GREY)
        self._status_selecionados = set(statuses or [])
        self.chips: list[ft.Chip] = []
        for st in STATUS_VALIDOS:
            chip = ft.Chip(
                label=ft.Text(st, size=11),
                selected=st in self._status_selecionados,
                selected_color=ft.Colors.INDIGO_100,
                on_select=lambda e, s=st: self._alternar_status(s, e),
            )
            self.chips.append(chip)
        self.wrap_status = ft.Row(self.chips, wrap=True, spacing=4, run_spacing=4)
        self.chk_concluida = ft.Checkbox(
            label="Coluna de concluídas (atividades da sprint)",
            tooltip="Lista as atividades já fechadas na sprint selecionada no quadro. Marque os status fechados (ex.: Encerrada, Cancelada).",
            value=bool(concluida),
        )

    def _alternar_status(self, status: str, e):
        if e.control.selected:
            self._status_selecionados.add(status)
        else:
            self._status_selecionados.discard(status)

    def to_dict(self) -> dict:
        return {
            "titulo": self.txt_titulo.value.strip() or ", ".join(sorted(self._status_selecionados)) or "Coluna",
            "status": sorted(self._status_selecionados),
            "concluida": bool(self.chk_concluida.value),
        }


class App:
    def __init__(self, page: ft.Page):
        self.page = page
        self.config = carregar_config()
        debug_log.habilitar(self.config.get("debug", False))
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
        self.conv_atual = None
        self.issues_concluidas = []
        self.sprint_atual_id = None

        # Indicador de "digitando" (3 pontos animados) do assistente
        self.asst_digitando_col = None
        self.asst_digitando_ativo = False
        self._digitando_task = None

        # Área de conteúdo (troca entre abas)
        self.conteudo = ft.Column(expand=True)
        self.navbar = ft.NavigationBar(
            selected_index=0,
            bgcolor=ft.Colors.SURFACE,
            height=56,
            label_behavior=ft.NavigationBarLabelBehavior.ALWAYS_SHOW,
            label_padding=ft.Padding(0, 2, 0, 4),
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

        # ---- Tema Material 3 (estilo Android) — mesmo tema/estilo do app cesta-wbv:
        # seed INDI_700, modo claro, fundo padrão, densidade confortável. ----
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.theme = ft.Theme(
            color_scheme_seed=COR_PRINCIPAL,
            visual_density=ft.VisualDensity.COMFORTABLE,
            navigation_bar_theme=ft.NavigationBarTheme(
                label_text_style=ft.TextStyle(
                    color=ft.Colors.GREY_800,
                    weight=ft.FontWeight.W_500,
                ),
                indicator_color=ft.Colors.INDIGO_100,
            ),
        )

        self.navbar.bgcolor = ft.Colors.SURFACE
        self.navbar.indicator_color = ft.Colors.INDIGO_100
        self.page.on_resize = self._on_resize
        self.page.add(self.conteudo, self.navbar)

    async def _inicializar(self):
        await asyncio.to_thread(self._construir_views)
        self._renderizar_abate(0)
        self._inicializar_conversa()
        self._render_conversas()
        self._carregar_historico_assistente()
        if self.config.get("api_key"):
            await self._carregar_async()

    def _construir_views(self):
        # ---------- view ATIVIDADES ----------
        self.busca = ft.TextField(
            label="Buscar (ID ou assunto)",
            prefix_icon=ft.Icons.SEARCH,
            on_change=self._filtrar,
            border_radius=10,
            bgcolor=ft.Colors.SURFACE,
            height=40,
            expand=True,
        )
        self.lista = ft.Column(spacing=8, expand=True, scroll=ft.ScrollMode.AUTO)
        self.lbl_carregando = ft.Text("", size=12, color=ft.Colors.GREY)
        self.lbl_usuario = ft.Text("", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
        self.row_paginacao = ft.Row([], alignment=ft.MainAxisAlignment.CENTER, spacing=8)

        # ---- toggle Lista / Kanban ----
        self.seg_visualizacao = ft.SegmentedButton(
            show_selected_icon=False,
            allow_empty_selection=False,
            allow_multiple_selection=False,
            selected=[self.config.get("visualizacao") if self.config.get("visualizacao") in ("lista", "kanban") else "lista"],
            style=ft.ButtonStyle(
                color={
                    ft.ControlState.SELECTED: ft.Colors.WHITE,
                    ft.ControlState.DEFAULT: ft.Colors.GREY_800,
                },
                bgcolor={
                    ft.ControlState.SELECTED: ft.Colors.GREEN_600,
                    ft.ControlState.DEFAULT: ft.Colors.SURFACE,
                },
            ),
            segments=[
                ft.Segment(value="lista", label=ft.Text("Lista")),
                ft.Segment(value="kanban", label=ft.Text("Kanban")),
            ],
            on_change=self._trocar_visualizacao,
        )

        # ---- conteúdo kanban ----
        self.kanban_sprint = ft.Dropdown(label="Sprint", width=190, height=40, on_select=self._kanban_sprint_alterada)
        self.kanban_lbl_status = ft.Text("", size=11, color=ft.Colors.GREY)
        self.encaixe_kanban_sprint = ft.Container(
            self.kanban_sprint,
            bgcolor=ft.Colors.SURFACE,
            border_radius=12,
            visible=("kanban" in (self.seg_visualizacao.selected or [])),
        )
        self.kanban_colunas = ft.Row(spacing=10, scroll=ft.ScrollMode.AUTO, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.corpo_kanban = ft.Column(
            [
                ft.Row([self.kanban_lbl_status], spacing=8),
                self.kanban_colunas,
            ],
            spacing=8,
            expand=True,
        )

        # ---- atividades: cabeçalho fixo + conteúdo alternável (lista/kanban) ----
        self.corpo_lista = ft.Column([self.lista, self.row_paginacao], spacing=8, expand=True)
        self.corpo_conteudo_atividades = ft.Column(expand=True, spacing=8)
        corpo_inicial = self.corpo_kanban if "kanban" in (self.seg_visualizacao.selected or []) else self.corpo_lista
        self.corpo_conteudo_atividades.controls.append(corpo_inicial)

        # ---- appbar superior (estilo cesta-wbv), uma linha:
        # usuário -> filtro de sprint -> busca -> Lista/Kanban -> atualizar ----
        self.barra_superior = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.ACCOUNT_CIRCLE_OUTLINED, size=20, color=ft.Colors.WHITE),
                    self.lbl_usuario,
                    self.encaixe_kanban_sprint,
                    self.busca,
                    self.seg_visualizacao,
                    self.btn_atualizar(),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=COR_PRINCIPAL,
            padding=ft.Padding(12, 6, 12, 6),
        )

        self.view_atividades = ft.Container(
            content=ft.Column(
                [
                    self.barra_superior,
                    ft.Container(
                        ft.Column(
                            [
                                self.lbl_carregando,
                                self.corpo_conteudo_atividades,
                            ],
                            spacing=6,
                            expand=True,
                        ),
                        padding=12,
                        expand=True,
                    ),
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
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
            shift_enter=True,
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

        # Sidebar de conversas (estilo ChatGPT)
        self.conversas_lista = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, expand=True)
        self.asst_sidebar = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Conversas", weight=ft.FontWeight.BOLD, size=13),
                            ft.Container(expand=True),
                            ft.IconButton(
                                icon=ft.Icons.ADD_COMMENT,
                                tooltip="Nova conversa",
                                icon_color=ft.Colors.ON_PRIMARY,
                                bgcolor=ft.Colors.PRIMARY,
                                on_click=self._nova_conversa,
                            ),
                        ],
                        spacing=6,
                    ),
                    ft.Divider(height=1),
                    self.conversas_lista,
                ],
                spacing=8,
            ),
            width=230,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            border=ft.Border(right=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
            padding=ft.Padding(8, 10, 8, 10),
        )

        # Barra superior FIXA (título + ícone + limpar)
        self.asst_appbar = ft.Container(
            ft.Row(
                [
                    ft.Container(
                        ft.Icon(ft.Icons.SMART_TOY, color=ft.Colors.WHITE),
                        bgcolor=ft.Colors.INDIGO_700,
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
                            ft.Icon(ft.Icons.LOW_PRIORITY, size=16, color=COR_PRINCIPAL),
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
                ft.Row(
                    [
                        self.asst_sidebar,
                        ft.Container(
                            ft.Column(
                                [
                                    self.asst_chat_area,
                                    self.asst_prioridade_painel,
                                    self.asst_rodape,
                                ],
                                spacing=0,
                                expand=True,
                            ),
                            expand=True,
                            padding=ft.Padding(0, 8, 0, 0),
                        ),
                    ],
                    expand=True,
                    spacing=0,
                ),
            ],
            expand=True,
            spacing=0,
        )

        # ---------- view CONFIG ----------
        self.txt_site = ft.TextField(label="URL do Redmine", hint_text="https://projetos.wheaton.com.br", value=self.config.get("site", ""))
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
        self.chk_debug = ft.Checkbox(
            label="Modo debug — registrar interações Redmine × IA",
            tooltip="Gera o arquivo debug.log ao lado do aplicativo com as requisições enviadas à IA e ao Redmine.",
            value=bool(self.config.get("debug", False)),
        )
        self.chk_atualizar_pct = ft.Checkbox(
            label="Permitir atualizar % concluído no Redmine",
            tooltip="O servidor pode ter regras que bloqueiam o ajuste manual do % concluído. Desligado, o app nunca envia o % concluído e o lançamento de horas não depende dele (o % só muda por regras do servidor / mudança de status).",
            value=bool(self.config.get("atualizar_percentual", False)),
        )
        self.chk_auto_executar = ft.Checkbox(
            label="Executar ações da IA sem confirmação (avançado)",
            tooltip="Desligado (padrão): toda ação que grava dado no Redmine (horas, status, prioridade, comentário) é exibida para você confirmar antes de aplicar. Ligar remove essa etapa — cuidado com descrições de issues criadas por outras pessoas (risco de prompt injection).",
            value=bool(self.config.get("assistente_auto_executar", False)),
        )

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
                    border_radius=12,
                    padding=10,
                )
            )

        # Editor do quadro kanban (colunas persistidas na configuração)
        self._editores_colunas = [
            _EditorColuna(c.get("titulo"), c.get("status"), c.get("concluida", False))
            for c in self._kanban_colunas_config()
        ]
        self.colunas_kanban_list = ft.Column(spacing=10)
        for ed in self._editores_colunas:
            self.colunas_kanban_list.controls.append(self._card_editor_coluna(ed))
        self.btn_kb_adicionar = ft.OutlinedButton("Adicionar coluna", icon=ft.Icons.ADD, on_click=self._kb_adicionar)

        self._atualizar_campos_llm(initial=True)

        def _secao(titulo: str, controles: list, dica: str | None = None) -> ft.Container:
            itens = [ft.Text(titulo, weight=ft.FontWeight.BOLD, size=13)]
            if dica:
                itens.append(ft.Text(dica, size=11, color=ft.Colors.GREY))
            itens.extend(controles)
            return ft.Container(
                ft.Column(itens, spacing=8),
                padding=12,
                border_radius=12,
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            )

        self.view_config = ft.ListView(
            [
                ft.Container(
                    ft.Column(
                        [
                            ft.Text("Configurações", size=18, weight=ft.FontWeight.BOLD),
                            _secao(
                                "Redmine",
                                [self.txt_site, self.txt_apikey],
                                dica="Somente a API access key é usada (associada ao seu usuário no Redmine).",
                            ),
                            _secao(
                                "Provedor de IA (LLM)",
                                [
                                    self.cmb_provider,
                                    self.txt_llm_api_key,
                                    self.txt_llm_url,
                                    self.txt_llm_model,
                                    ft.ResponsiveRow(
                                        [
                                            ft.Container(self.txt_llm_temp, col={"sm": 12, "md": 6}),
                                            ft.Container(self.txt_llm_max_tokens, col={"sm": 12, "md": 6}),
                                        ],
                                        spacing=8,
                                    ),
                                    self.txt_llm_prompt_system,
                                ],
                            ),
                            _secao(
                                "Ferramentas do assistente",
                                blocos_ferramentas,
                                dica="Selecione quais ações a IA pode executar no Redmine e localmente.",
                            ),
                            _secao(
                                "Assistente de IA",
                                [self.chk_auto_executar],
                                dica="Recomendado manter desmarcado: ações que gravam no Redmine passam por sua confirmação.",
                            ),
                            _secao(
                                "Regras de atualização",
                                [
                                    self.chk_atualizar_pct,
                                    ft.Text("Desligado, o % concluído não é alterado pelo app (lançamento de horas funciona normalmente).", size=11, color=ft.Colors.GREY),
                                ],
                            ),
                            _secao(
                                "Quadro Kanban",
                                [
                                    ft.Text("Monte o quadro como preferir: crie, reordene e remova colunas. Toque nas etiquetas para incluir/excluir cada status. Coluna de \"concluídas\" lista as atividades fechadas da sprint selecionada.", size=11, color=ft.Colors.GREY),
                                    self.colunas_kanban_list,
                                    self.btn_kb_adicionar,
                                ],
                            ),
                            _secao("Depuração", [self.chk_debug]),
                            ft.Row([self.btn_testar, self.btn_salvar], spacing=10, wrap=True),
                            self.lbl_status_config,
                            ft.Divider(height=6),
                            ft.Text(
                                APP_VERSAO_DISPLAY,
                                size=11,
                                italic=True,
                                color=ft.Colors.GREY,
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                        spacing=12,
                    ),
                    padding=16,
                )
            ],
            expand=True,
            spacing=8,
        )

    def btn_atualizar(self):
        return ft.IconButton(
            icon=ft.Icons.REFRESH,
            icon_color=ft.Colors.WHITE,
            tooltip="Atualizar lista",
            on_click=self._carregar_async,
        )

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
            if "kanban" in (self.seg_visualizacao.selected or []):
                self.page.run_task(self._preparar_kanban)
            self.page.update()

    def _carregar(self):
        if self.api is None:
            self.api = criar_api(self.config)
        if self.api is None:
            self.api = RedmineAPI()  # fallback: credenciais.txt
        self._status_disp = None

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
        if "kanban" in (self.seg_visualizacao.selected or []):
            self._render_kanban()
        self.page.update()

    # ============================================================ visualização kanban
    def _persistir_config(self):
        try:
            salvar_config(self.config)
        except Exception:
            LOGGER.exception("Falha ao persistir configuração")

    def _trocar_visualizacao(self, e=None):
        kanban = "kanban" in (self.seg_visualizacao.selected or [])
        self.config["visualizacao"] = "kanban" if kanban else "lista"
        self._persistir_config()
        self.encaixe_kanban_sprint.visible = kanban
        self.corpo_conteudo_atividades.controls.clear()
        self.corpo_conteudo_atividades.controls.append(self.corpo_kanban if kanban else self.corpo_lista)
        self.page.update()
        if kanban:
            self.page.run_task(self._preparar_kanban)

    def _on_resize(self, e=None):
        seg = getattr(self, "seg_visualizacao", None)
        if seg and "kanban" in (seg.selected or []):
            largura = float(getattr(e, "width", 0)) if getattr(e, "width", None) else None
            self._render_kanban(largura)
            self.page.update()

    async def _preparar_kanban(self):
        if self.api is None:
            return
        self.kanban_lbl_status.value = "Carregando sprints..."
        self.kanban_lbl_status.color = ft.Colors.GREY
        self.page.update()
        try:
            await asyncio.to_thread(self._montar_opcoes_sprint)
            if self.kanban_sprint.options and (
                self.kanban_sprint.value not in {o.key for o in self.kanban_sprint.options}
            ):
                self.kanban_sprint.value = self.sprint_atual_id
            await self._carregar_concluidas_kanban()
        except Exception as ex:
            self.kanban_lbl_status.value = f"Erro: {type(ex).__name__}: {ex}"
            self.kanban_lbl_status.color = ft.Colors.RED
            self.page.update()

    def _montar_opcoes_sprint(self):
        """Popula o dropdown com as versões dos projetos das issues e autoseleciona a sprint atual."""
        projetos = {}
        for issue in self.issues:
            pj = issue.get("project") or {}
            if pj.get("id") is not None:
                projetos[pj["id"]] = pj.get("name", "")

        versoes = []
        for pid in projetos:
            try:
                versoes.extend(self.api.get_versions(pid))
            except Exception:
                LOGGER.exception("Falha ao listar versões do projeto %s", pid)
                continue

        hoje = str(self.hoje)
        abertas = [v for v in versoes if str(v.get("status")) == "open"]

        def _chave(v):
            d = str(v.get("due_date") or "")
            dentro = 0 if (d and d >= hoje) else 1
            return (dentro, d)

        abertas.sort(key=_chave)
        self.sprint_atual_id = None
        if abertas:
            dentro_daqui = [v for v in abertas if str(v.get("due_date") or "") >= hoje]
            escolhida = dentro_daqui[0] if dentro_daqui else abertas[0]
            self.sprint_atual_id = str(escolhida.get("id"))

        cont = Counter(str((i.get("fixed_version") or {}).get("id")) for i in self.issues if i.get("fixed_version"))
        dominante = cont.most_common(1)[0][0] if cont else None

        opcoes = []
        vistos = set()
        for v in abertas:
            vid = str(v.get("id"))
            if vid in vistos:
                continue
            vistos.add(vid)
            texto = str(v.get("name") or "")
            if v.get("due_date"):
                texto += f" · {v.get('due_date')}"
            opcoes.append(ft.DropdownOption(key=vid, text=texto))
        if dominante and dominante not in vistos:
            vd = next((v for v in versoes if str(v.get("id")) == dominante), None)
            if vd:
                texto = str(vd.get("name") or "")
                if str(vd.get("status")) != "open":
                    texto += " · (fechada)"
                opcoes.append(ft.DropdownOption(key=dominante, text=texto))
                if self.sprint_atual_id is None:
                    self.sprint_atual_id = dominante

        self.kanban_sprint.options = opcoes
        if opcoes:
            salvo = str(self.config.get("kanban_sprint_id") or "")
            if salvo and salvo in {o.key for o in opcoes}:
                self.kanban_sprint.value = salvo
            else:
                if self.sprint_atual_id and self.sprint_atual_id not in {o.key for o in opcoes}:
                    self.sprint_atual_id = opcoes[0].key
                self.kanban_sprint.value = self.sprint_atual_id or opcoes[0].key

    def _kanban_sprint_alterada(self, e=None):
        if self.kanban_sprint.value:
            self.config["kanban_sprint_id"] = str(self.kanban_sprint.value)
            self._persistir_config()
        self.page.run_task(self._carregar_concluidas_kanban)

    async def _carregar_concluidas_kanban(self, e=None):
        vid = self.kanban_sprint.value
        if not vid or self.api is None:
            self.issues_concluidas = []
            self._render_kanban()
            self.page.update()
            return
        self.kanban_lbl_status.value = "Carregando concluídas..."
        self.kanban_lbl_status.color = ft.Colors.GREY
        self.page.update()
        try:
            self.issues_concluidas = await asyncio.to_thread(self.api.get_issues_concluidas, int(vid))
        except Exception as ex:
            self.issues_concluidas = []
            self.kanban_lbl_status.value = f"Erro: {type(ex).__name__}: {ex}"
            self.kanban_lbl_status.color = ft.Colors.RED
            self.page.update()
            return
        statuses_concluida = self._statuses_colunas_concluida()
        total = [i for i in self.issues_concluidas if (i.get("status") or {}).get("name") in statuses_concluida]
        self.kanban_lbl_status.value = f"{len(total)} concluídas nessa sprint" if total else "Sem atividades concluídas nessa sprint"
        self.kanban_lbl_status.color = ft.Colors.GREY
        self._render_kanban()
        self.page.update()

    def _kanban_colunas_config(self) -> list:
        colunas = self.config.get("kanban_colunas")
        if not isinstance(colunas, list) or not colunas:
            return [dict(c) for c in DEFAULT_KANBAN_COLUNAS]
        return colunas

    def _statuses_colunas_concluida(self) -> set:
        return {
            s for col in self._kanban_colunas_config() if col.get("concluida")
            for s in (col.get("status") or [])
        }

    def _render_kanban(self, largura_livre: float | None = None):
        # Responsivo: usa a largura do resize event (largura real do conteúdo,
        # sem chrome da janela). As colunas são distribuídas descontando o
        # espaçamento da Row e uma margem simétrica nos cantos, para que todas
        # apareçam completas (a última nunca fica cortada). Se não couberem no
        # mínimo, ativa rolagem horizontal.
        MIN_COL = 210
        MAX_COL = 520
        ESPACO = 10
        MARGEM = 4
        self.kanban_colunas.controls.clear()
        colunas = self._kanban_colunas_config()
        n_colunas = max(1, len(colunas))
        if largura_livre:
            largura_util = largura_livre
        else:
            largura_util = self.page.width or self.page.window.width or 430
        largura_util = max(220, largura_util - 24 - 2 * MARGEM)
        espaco_total = (n_colunas - 1) * ESPACO
        if n_colunas * MIN_COL + espaco_total <= largura_util:
            largura_col = min((largura_util - espaco_total) / n_colunas, MAX_COL)
            self.kanban_colunas.scroll = ft.ScrollMode.HIDDEN
        else:
            largura_col = MIN_COL
            self.kanban_colunas.scroll = ft.ScrollMode.AUTO
        for col in colunas:
            statuses = set(col.get("status") or [])
            concluida = bool(col.get("concluida", False))
            titulo = str(col.get("titulo") or "—").strip() or "—"
            if concluida:
                itens = [i for i in self.issues_concluidas if (i.get("status") or {}).get("name") in statuses]
            else:
                itens = [i for i in self.filtrados if (i.get("status") or {}).get("name") in statuses]
            prim = next(iter(statuses), "") if statuses else ""
            cor = ft.Colors.GREEN_200 if concluida else CORES_STATUS.get(prim, ft.Colors.GREY_300)
            self.kanban_colunas.controls.append(
                self._coluna_kanban(titulo, itens, destaque=concluida, cor=cor, largura=largura_col)
            )

    def _coluna_kanban(self, status: str, itens: list, destaque: bool = False, cor=None, largura: float = 250):
        cor = cor or (ft.Colors.GREEN_200 if destaque else CORES_STATUS.get(status, ft.Colors.GREY_300))
        cards = [self._card_kanban(i) for i in itens]
        if not cards:
            cards = [ft.Text("—", size=11, color=ft.Colors.GREY)]
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(ft.Text(status, size=11, weight=ft.FontWeight.BOLD), bgcolor=cor, border_radius=6, padding=ft.Padding(4, 8, 4, 8)),
                            ft.Container(expand=True),
                            ft.Text(str(len(itens)), size=11, color=ft.Colors.GREY),
                        ],
                        spacing=6,
                    ),
                    ft.Column(cards, spacing=6, scroll=ft.ScrollMode.AUTO, expand=True),
                ],
                spacing=8,
                expand=True,
            ),
            width=largura,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            border_radius=12,
            padding=8,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        )

    def _card_kanban(self, issue: dict) -> ft.Container:
        versao = (issue.get("fixed_version") or {}).get("name", "") or "sem sprint"
        done = issue.get("done_ratio", 0)
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(f"#{issue.get('id')}", size=10, weight=ft.FontWeight.BOLD, color=COR_PRINCIPAL),
                    ft.Text(issue.get("subject", ""), size=12, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Row(
                        [
                            ft.Text(versao, size=10, color=ft.Colors.GREY, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(f"{done}%", size=10, color=ft.Colors.GREY),
                        ],
                        spacing=4,
                    ),
                    ft.Row(
                        [
                            ft.IconButton(icon=ft.Icons.TIMER, icon_size=16, tooltip="Lançar horas", on_click=lambda e, i=issue: self._abrir_lancamento(i)),
                            ft.IconButton(icon=ft.Icons.SMART_TOY, icon_size=16, tooltip="Análise da atividade (IA)", on_click=lambda e, i=issue: self._abrir_revisao(i)),
                            ft.IconButton(icon=ft.Icons.SWAP_HORIZ, icon_size=16, tooltip="Mover para outro status", on_click=lambda e, i=issue: self._abrir_mover_status(i)),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=2,
                    ),
                ],
                spacing=4,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=12,
            padding=8,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        )

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
    def _status_disponiveis(self):
        """Lista dos status do Redmine (dinâmico via API, com fallback fixo)."""
        if getattr(self, "_status_disp", None) is not None:
            return self._status_disp
        lista = list(STATUS_VALIDOS)
        if self.api is not None:
            try:
                lista = self.api.get_todos_status() or lista
            except Exception:
                LOGGER.exception("Falha ao obter status dinâmicos — usando lista fixa de fallback")
        self._status_disp = lista
        return lista

    def _abrir_lancamento(self, issue: dict):
        self.issue_selecionada = issue
        versoes = self.api.get_versions((issue.get("project") or {}).get("id")) if self.api else []
        self.versoes_projeto = [v for v in versoes if v.get("status") != "locked"]

        status = (issue.get("status") or {}).get("name", "")
        done = issue.get("done_ratio", 0)

        statuses = self._status_disponiveis()
        self.cmb_status = ft.Dropdown(label="Status", options=[ft.DropdownOption(key=s, text=s) for s in statuses], value=status if status in statuses else None)
        self.pct_permitido = bool(self.config.get("atualizar_percentual", False))
        self.slider_done = ft.Slider(min=0, max=100, divisions=10, value=done, label="{value}%", on_change=self._set_lbl_done) if self.pct_permitido else None
        self.lbl_done = ft.Text(f"{int(done)}%")
        self.pct_info = ft.Text(
            "Atualização do % concluído desativada (regras do servidor). Para alterar, habilite em Configurações.",
            size=10, color=ft.Colors.GREY,
        )
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
                    *( [self.slider_done, self.lbl_done] if self.pct_permitido else [self.pct_info] ),
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
            LOGGER.exception("Falha ao listar atividades de apontamento — usando fallback fixo")
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
        if self.pct_permitido and self.slider_done is not None:
            pct = s.get("percentual")
            if isinstance(pct, (int, float)) and 0 <= float(pct) <= 100:
                self.slider_done.value = float(pct)
                self.lbl_done.value = f"{int(pct)}%"
        status = s.get("status")
        if status and status in self._status_disponiveis():
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
        novo_done = int(self.slider_done.value) if (self.pct_permitido and self.slider_done is not None) else None
        comentario = self.txt_comentario.value.strip()
        data_ap = self.txt_data.value.strip() or self.hoje
        previsao = self.txt_previsao.value.strip() or None
        sprint_id = self.cmb_sprint.value
        atividade_id = self.cmb_atividade.value

        try:
            payload = {}
            status_mudou = False
            status_ids = self.api.get_status_ids()
            if novo_status:
                if novo_status not in status_ids:
                    raise ValueError(f"Status '{novo_status}' não encontrado no Redmine.")
                atual = (issue.get("status") or {}).get("name")
                if novo_status != atual:
                    payload["status_id"] = status_ids[novo_status]
                    status_mudou = True
            # % concluído: só envia se permitido nas Configurações E junto com mudança de status
            if self.pct_permitido and novo_done is not None and status_mudou:
                payload["done_ratio"] = novo_done
            if previsao:
                payload["due_date"] = previsao
            if sprint_id:
                payload["fixed_version_id"] = int(sprint_id)
            if payload:
                self.api.atualizar_issue(issue_id, **payload)
            self.api.lancar_horas(issue_id, horas, comentario, data_ap, activity_id=int(atividade_id) if atividade_id else None)
            done_final = novo_done if (novo_done is not None and "done_ratio" in payload) else int(issue.get("done_ratio", 0))
            self._notificar(f"Lançado {horas}h em #{issue_id} ✓")
            self._atualizar_dados_locais(issue_id, done_final, novo_status, previsao, sprint_id)
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
                    ft.Icon(icone, size=15, color=COR_PRINCIPAL),
                    ft.Text(texto, size=12, weight=ft.FontWeight.W_500, color=COR_PRINCIPAL),
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
            shift_enter=True,
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
                    ft.Text("Ágil · Scrum · PMBOK", size=12, color=ft.Colors.INDIGO_700, weight=ft.FontWeight.W_500),
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
                        bgcolor=ft.Colors.INDIGO_700,
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
        self.page.run_task(self._scroll_chat)

    async def _scroll_chat(self):
        try:
            await asyncio.sleep(0.05)
            await self.chat_msgs.scroll_to(offset=-1, duration=200)
        except Exception:
            pass

    # ============================================================ assistente (chat global)
    def _btn_limpar_historico(self) -> ft.IconButton:
        return ft.IconButton(icon=ft.Icons.DELETE_SWEEP, tooltip="Limpar histórico desta conversa", on_click=self._limpar_historico_assistente)

    def _limpar_historico_assistente(self, e=None):
        if not self.conv_atual:
            return
        self._esconder_digitando()
        adb.limpar_historico(self.conv_atual)
        self.asst_historico = []
        self.asst_msgs.controls.clear()
        self._add_asst_msg("assistente", "Histórico limpo. Como posso ajudar com suas atividades hoje?")
        self._render_conversas()
        self.page.update()

    # ------------------------------------------------------------ conversas (sidebar)
    def _inicializar_conversa(self):
        conversas = adb.listar_conversas()
        self.conv_atual = conversas[0]["contexto"] if conversas else adb.criar_conversa()

    def _render_conversas(self):
        self.conversas_lista.controls.clear()
        itens = []
        for conv in adb.listar_conversas():
            ativa = conv["contexto"] == self.conv_atual
            caixa = ft.Container(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.CHAT if not ativa else ft.Icons.FORUM,
                                size=16,
                                color=COR_PRINCIPAL if ativa else ft.Colors.GREY),
                        ft.Text(
                            conv["titulo"] or "Nova conversa",
                            size=12,
                            weight=ft.FontWeight.BOLD if ativa else ft.FontWeight.NORMAL,
                            color=ft.Colors.INDIGO_900 if ativa else ft.Colors.ON_SURFACE_VARIANT,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            expand=True,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE,
                            icon_size=14,
                            icon_color=ft.Colors.GREY,
                            tooltip="Excluir conversa",
                            on_click=lambda e, c=conv["contexto"]: self._excluir_conversa(c),
                        ),
                    ],
                    spacing=6,
                ),
                bgcolor=ft.Colors.PRIMARY_CONTAINER if ativa else ft.Colors.TRANSPARENT,
                border_radius=10,
                padding=ft.Padding(8, 4, 2, 4),
                on_click=lambda e, c=conv["contexto"]: self._trocar_conversa(c),
            )
            itens.append(caixa)
        self.conversas_lista.controls = itens
        self.page.update()

    def _nova_conversa(self, e=None):
        contexto = adb.criar_conversa()
        self._trocar_conversa(contexto)

    def _trocar_conversa(self, contexto: str, e=None):
        self._esconder_digitando()
        self.conv_atual = contexto
        self._carregar_historico_assistente()
        self._render_conversas()
        self.page.update()

    def _excluir_conversa(self, contexto: str, e=None):
        if contexto == self.conv_atual:
            adb.excluir_conversa(contexto)
            conversas = adb.listar_conversas()
            self.conv_atual = conversas[0]["contexto"] if conversas else adb.criar_conversa()
            self._carregar_historico_assistente()
        else:
            adb.excluir_conversa(contexto)
        self._render_conversas()
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
        self.page.run_task(self._scroll_msgs)

    async def _scroll_msgs(self):
        try:
            await self.asst_msgs.scroll_to(offset=-1, duration=150)
        except Exception:
            pass

    async def _pergunta_assistente(self, texto: str):
        self.asst_input.value = texto
        await self._enviar_assistente()

    def _carregar_historico_assistente(self):
        self.asst_historico = []
        self.asst_msgs.controls.clear()
        try:
            for m in adb.historico(self.conv_atual):
                self._add_asst_msg("assistente" if m["autor"] == "assistente" else "você", m["conteudo"])
        except Exception:
            LOGGER.exception("Falha ao carregar histórico de conversa %s", self.conv_atual)
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
        # prioridade = ordem na lista salva (primeiro da lista = mais importante)
        def _chave_prioridade(i):
            info = pr.get(i.get("id"))
            if isinstance(info, dict):
                return info.get("prioridade", 9999)
            return 9999

        ordenados = sorted(self.issues, key=_chave_prioridade)
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
                                        bgcolor=ft.Colors.INDIGO_700,
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

    def _executar_acoes(self, acoes: list) -> str:
        """Executa as ações do assistente via ExecutorDeAcoes (lógica em acoes.py)."""
        executor = ExecutorDeAcoes(self.config, self.api, self.issues)
        relatorio = executor.executar(acoes)
        if executor.api is not None and self.api is None:
            self.api = executor.api
        return relatorio

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
        self.page.run_task(self._scroll_msgs)

        async def animar():
            while self.asst_digitando_ativo:
                for indice in range(3):
                    for j, p in enumerate(pontos):
                        alvo = 1.0 if j == indice else 0.3
                        if p.opacity != alvo:
                            p.opacity = alvo
                    self.page.update()
                    try:
                        await self.asst_msgs.scroll_to(offset=-1, duration=100)
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

    def _resumir_acao(self, item: dict) -> str:
        """Resumo legível de uma ação proposta pela IA (para o diálogo de confirmação)."""
        acao = item.get("acao") or item.get("tipo") or "?"
        dados = item.get("dados") or {}
        issue_id = dados.get("issue_id")
        if acao == "lancar_horas":
            texto = f"Lançar {dados.get('horas')}h na #{issue_id}"
            if dados.get("comentario"):
                texto += f" — '{dados.get('comentario')}'"
            return texto
        if acao == "atualizar_status":
            return f"Mudar status da #{issue_id} para '{dados.get('status')}'"
        if acao == "atualizar_percentual":
            return f"Definir % concluído da #{issue_id} para {dados.get('percentual')}%"
        if acao == "atualizar_previsao":
            return f"Alterar data prevista da #{issue_id} para {dados.get('data')}"
        if acao == "atualizar_prioridade":
            return f"Alterar prioridade da #{issue_id} para '{dados.get('prioridade')}'"
        if acao == "adicionar_comentario":
            return f"Adicionar comentário na #{issue_id}"
        return f"Executar ação '{acao}'"

    def _confirmar_acoes_ia(self, acoes: list) -> "asyncio.Future[bool]":
        """Exibe um diálogo pedindo confirmação das ações da IA no Redmine.

        Retorna um Future resolvido com True (Confirmar) ou False (Cancelar)
        quando o usuário decidir. Não aplica nada por conta própria.
        """
        loop = asyncio.get_running_loop()
        done: "asyncio.Future[bool]" = loop.create_future()
        linhas = [self._resumir_acao(a) for a in acoes if isinstance(a, dict)]

        def _fechar(confirmado: bool, ev=None):
            if not done.done():
                done.set_result(confirmado)
            dialogo.open = False
            self.page.update()

        dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirmar ações no Redmine", size=16, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                ft.Column(
                    [
                        ft.Text(
                            "A IA deseja executar as alterações a seguir no Redmine. "
                            "Revise antes de confirmar:",
                            size=12,
                        ),
                        *[ft.Text(f"• {linha}", size=12) for linha in linhas],
                    ],
                    spacing=8,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=340,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: _fechar(False)),
                ft.FilledButton(
                    "Confirmar e aplicar",
                    bgcolor=ft.Colors.GREEN_600,
                    color=ft.Colors.WHITE,
                    on_click=lambda e: _fechar(True),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.show_dialog(dialogo)
        return done

    async def _enviar_assistente(self, e=None):
        mensagem = self.asst_input.value.strip()
        if not mensagem:
            return
        self._add_asst_msg("você", mensagem)
        self.asst_historico.append({"role": "user", "content": mensagem})
        adb.salvar_mensagem("você", mensagem, self.conv_atual)
        self.asst_input.value = ""
        self.asst_input.disabled = True
        self.asst_btn_enviar.disabled = True
        self.asst_lbl_status.value = ""
        self._mostrar_digitando()
        self.page.update()
        try:
            prioridades = adb.prioridades()
            notas = adb.notas()
            ferramentas = list(self.config.get("ferramentas_habilitadas") or [])
            if not self.config.get("atualizar_percentual", False):
                ferramentas = [t for t in ferramentas if t != "atualizar_percentual"]
            resultado = await asyncio.to_thread(
                self.ollama.chat_assistente,
                mensagem,
                self.issues,
                prioridades,
                notas,
                self.asst_historico,
                ferramentas,
            )
            resposta = resultado.get("resposta", "")
            acoes = resultado.get("acoes", [])

            linhas = [resposta]
            if acoes:
                auto = bool(self.config.get("assistente_auto_executar", False))
                confirma = [
                    a for a in acoes
                    if isinstance(a, dict) and requer_confirmacao(a.get("acao") or a.get("tipo"))
                ]
                diretas = [a for a in acoes if a not in confirma]
                if confirma and not auto:
                    ok = await self._confirmar_acoes_ia(confirma)
                    if ok:
                        diretas.extend(confirma)
                    else:
                        linhas.append("✋ Ações propostas pela IA foram descartadas — nenhuma alteração foi aplicada.")
                relatorio = await asyncio.to_thread(self._executar_acoes, diretas)
                if relatorio:
                    linhas.append(relatorio)
                    if "Lançadas" in relatorio or "Prioridade" in relatorio:
                        self._notificar(relatorio.splitlines()[0])
            texto_final = "\n\n".join(x for x in linhas if x)

            self._esconder_digitando()
            self._add_asst_msg("assistente", texto_final)
            self.asst_historico.append({"role": "assistant", "content": texto_final})
            adb.salvar_mensagem("assistente", texto_final, self.conv_atual)
            self._render_prioridades()
            self._render_conversas()
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
                api = RedmineAPI(credenciais={"site": site, "api_key": api_key})
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
            "api_key": self.txt_apikey.value.strip(),
        })
        self.config.update(self._ler_config_llm())
        self.config["ferramentas_habilitadas"] = [
            t_id for t_id, chk in self._chk_ferramentas.items() if chk.value
        ]
        self.config["debug"] = bool(self.chk_debug.value)
        self.config["atualizar_percentual"] = bool(self.chk_atualizar_pct.value)
        self.config["assistente_auto_executar"] = bool(self.chk_auto_executar.value)
        self.config["kanban_colunas"] = [ed.to_dict() for ed in self._editores_colunas]
        salvar_config(self.config)
        debug_log.habilitar(self.config.get("debug", False))
        self.ollama = self._construir_cliente_llm()
        self.api = None
        self._status_disp = None
        self.lbl_status_config.value = "Configurações salvas. Clique em Atualizar na aba Atividades."
        self.lbl_status_config.color = ft.Colors.GREEN
        self.page.update()

    # ============================================================ editor do quadro kanban
    def _card_editor_coluna(self, ed: _EditorColuna) -> ft.Container:
        indice = self._editores_colunas.index(ed)
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ed.txt_titulo,
                            ft.IconButton(icon=ft.Icons.ARROW_UPWARD, icon_size=18, tooltip="Mover para cima", disabled=indice == 0, on_click=lambda e, i=indice: self._kb_mover(i, -1)),
                            ft.IconButton(icon=ft.Icons.ARROW_DOWNWARD, icon_size=18, tooltip="Mover para baixo", disabled=indice == len(self._editores_colunas) - 1, on_click=lambda e, i=indice: self._kb_mover(i, 1)),
                            ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_size=18, tooltip="Remover coluna", on_click=lambda e, i=indice: self._kb_remover(i)),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=2,
                    ),
                    ed.lbl_status,
                    ed.wrap_status,
                    ed.chk_concluida,
                ],
                spacing=6,
            ),
            padding=10,
            border_radius=12,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        )

    def _render_secao_kanban(self):
        self.colunas_kanban_list.controls.clear()
        for ed in self._editores_colunas:
            self.colunas_kanban_list.controls.append(self._card_editor_coluna(ed))
        self.page.update()

    def _kb_adicionar(self, e=None):
        self._editores_colunas.append(_EditorColuna("Nova coluna", [], False))
        self._render_secao_kanban()
        self._notificar("Coluna adicionada. Ajuste o nome e os status e salve.")

    def _kb_mover(self, indice: int, delta: int):
        novo = indice + delta
        if 0 <= novo < len(self._editores_colunas):
            self._editores_colunas[indice], self._editores_colunas[novo] = (
                self._editores_colunas[novo], self._editores_colunas[indice],
            )
            self._render_secao_kanban()

    def _kb_remover(self, indice: int):
        del self._editores_colunas[indice]
        if not self._editores_colunas:
            self._editores_colunas.append(_EditorColuna("Nova", ["Nova"], False))
        self._render_secao_kanban()

    # ============================================================ mover status
    def _abrir_mover_status(self, issue: dict):
        self.issue_selecionada = issue
        atual = (issue.get("status") or {}).get("name", "")
        opcoes = [ft.DropdownOption(key=s, text=s) for s in self._status_disponiveis() if s != atual]
        self.cmb_mover_status = ft.Dropdown(label="Novo status", options=opcoes, value=opcoes[0].key if opcoes else None)
        self.txt_mover_comentario = ft.TextField(
            label="Comentário (adicional como nota)",
            hint_text="O que motivou essa mudança?",
            multiline=True,
            min_lines=2,
            max_lines=4,
        )
        self.lbl_mover = ft.Text("", size=11, color=ft.Colors.GREY)

        conteudo = ft.Container(
            ft.Column(
                [
                    ft.Row([ft.Icon(ft.Icons.SWAP_HORIZ), ft.Text(f"Mover status · #{issue.get('id')}", weight=ft.FontWeight.BOLD, size=15)]),
                    ft.Text(issue.get("subject", ""), size=12, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"Status atual: {atual}", size=11, color=ft.Colors.GREY),
                    ft.Divider(height=4),
                    self.cmb_mover_status,
                    self.txt_mover_comentario,
                    ft.Text("Esta movimentação lança 1 minuto como tempo de atividade na issue.", size=11, color=ft.Colors.GREY),
                    self.lbl_mover,
                    ft.Row(
                        [
                            ft.OutlinedButton("Cancelar", icon=ft.Icons.CLOSE, on_click=self._fechar_sheet),
                            ft.Container(expand=True),
                            ft.FilledButton("Confirmar", icon=ft.Icons.CHECK, on_click=lambda e: self.page.run_task(self._mover_status_async)),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=10,
            ),
            padding=16,
        )

        bs = ft.BottomSheet(content=conteudo, show_drag_handle=True, open=True, on_dismiss=self._fechar_sheet)
        self.page.overlay.append(bs)
        self.page.update()

    async def _mover_status_async(self, e=None):
        issue = self.issue_selecionada
        if not issue:
            return
        novo_status = self.cmb_mover_status.value
        if not novo_status:
            self.lbl_mover.value = "Selecione um status."
            self.lbl_mover.color = ft.Colors.RED
            self.page.update()
            return
        comentario = self.txt_mover_comentario.value.strip()
        self.lbl_mover.value = f"Movendo #{issue['id']} para '{novo_status}'..."
        self.lbl_mover.color = ft.Colors.GREY
        self.page.update()
        try:
            await asyncio.to_thread(self._executar_mover_status, issue, novo_status, comentario)
        except Exception as ex:
            self.lbl_mover.value = f"Erro ao mover #{issue['id']}: {ex}"
            self.lbl_mover.color = ft.Colors.RED
            self.page.update()
            return
        self._atualizar_status_local(issue["id"], novo_status)
        sheet = self._sheet_aberta()
        if sheet:
            sheet.open = False
        self.page.update()
        self._notificar(f"#{issue['id']} movida para '{novo_status}' ✓ (+1 min apontado)")

    def _executar_mover_status(self, issue: dict, novo_status: str, comentario: str):
        issue_id = issue["id"]
        status_ids = self.api.get_status_ids()
        status_id = status_ids.get(novo_status)
        if status_id is None:
            raise ValueError(f"Status '{novo_status}' não encontrado no Redmine.")
        payload = {"status_id": status_id}
        if comentario:
            payload["notes"] = comentario
        self.api.atualizar_issue(issue_id, **payload)
        self.api.lancar_horas(
            issue_id,
            1 / 60.0,
            "Movimentação de status",
            self.hoje,
            activity_id=self._atividade_padrao_mover(),
        )

    def _atividade_padrao_mover(self):
        try:
            ativs = self.api.get_time_entry_activities()
        except Exception:
            LOGGER.exception("Falha ao listar atividades de apontamento — usando fallback fixo")
            return 9
        for a in ativs:
            if str(a.get("id")) == "9":
                return 9
        return ativs[0]["id"] if ativs else 9

    def _atualizar_status_local(self, issue_id: int, novo_status: str):
        card = next(
            (i for i in self.issues_concluidas if i.get("id") == issue_id),
            next((i for i in self.issues if i.get("id") == issue_id), None),
        )
        if card is None:
            return
        card["status"] = {"name": novo_status}
        concluido = novo_status in self._statuses_colunas_concluida()
        self.issues = [i for i in self.issues if i.get("id") != issue_id]
        self.issues_concluidas = [i for i in self.issues_concluidas if i.get("id") != issue_id]
        if concluido:
            self.issues_concluidas.append(card)
        else:
            self.issues.append(card)
        self.issues.sort(key=lambda i: i.get("id", 0), reverse=True)
        self._filtrar()

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
    if "--version" in sys.argv:
        print(f"{APP_NOME} {APP_VERSAO}")
        sys.exit(0)
    ft.run(main)
