# Redmine-Assitant

Assistente pessoal do Redmine integrado a uma IA local (Ollama). Interface responsiva estilo mobile/Android feita com Flet.

## Funcionalidades

- Listar e filtrar suas atividades (issues) no Redmine (status ativos).
- Paginação de 6 itens por página e busca por ID ou assunto.
- Botão para **lançar horas** (apontamento de tempo) em cada atividade.
- Botão para **revisar com IA** (assistente de gestão de projetos ágil via Ollama).
- Aba **Assistente pessoal**: chat com a IA sobre todas as atividades — ajuda a
  **organizar por prioridade**, apontar riscos, sugerir plano de trabalho e
  **lançar horas diretamente no Redmine** quando você pedir.
- Indicador animado de "digitando" (3 pontos, estilo WhatsApp) enquanto a IA processa a resposta.
- **Armazenamento local (SQLite)** do histórico das conversas, da ordem de
  prioridade das atividades e das anotações.
- Suporte a **vários provedores de IA**: **Ollama** (padrão, local), OpenAI, Claude
  (Anthropic), Gemini (Google) e Kimi (Moonshot). Na tela de configuração você
  escolhe o provedor, informa chave de API/URL/modelo, e ajusta temperatura,
  máximo de tokens e um **prompt system** personalizado.
- **Ferramentas configuráveis do assistente**: escolha na aba Configuração quais
  ações a IA pode executar (lançar horas, alterar status, % concluído, data
  prevista, prioridade no Redmine, adicionar comentário, listar atividades e
  organização/notas locais). Só as habilitadas são oferecidas à IA.
- **Confirmação de ações no Redmine**: ações que **gravam** dado no Redmine (horas,
  status, prioridade, data, comentário) pedem confirmação do usuário antes de
  aplicar, protegendo contra prompt injection em descrições de issues. A opção
  "Executar ações da IA sem confirmação (avançado)" desliga essa etapa (a tela
  de configuração avisa sobre o risco).
- Tela de configuração para credenciais do Redmine e modelo/Ollama.
- Geração e atualização de planilha de atividades (Excel) para apontamento em lote.
- **Log de erros** (`app.log`, com rotação) — falhas silenciosas (ex.: issue
  inexistente na planilha) ficam registradas com traceback para diagnóstico.
- Interface com tema **Material 3 (estilo Android)**, funcional em **Windows e Linux**.

## Estrutura

- `app_flet.py` — aplicação principal (UI Flet) com abas Atividades, Assistente e Configuração.
- `acoes.py` — execução das ações do assistente (lógica pura, sem Flet; testável isoladamente).
- `redmine_api.py` — cliente da REST API do Redmine (inclui helpers compartilhados
  `criar_api_da_config` e `normalizar_data`).
- `ollama_client.py` — cliente multi-provedor de LLM (Ollama, OpenAI, Claude, Gemini, Kimi) com chat, sugestões e assistente pessoal com ações.
- `assistente_db.py` — armazenamento local SQLite (histórico de conversas, prioridades, notas).
- `config_manager.py` — leitura/gravação de config.json.
- `ferramentas.py` — catálogo de ferramentas do assistente (formatos de ação e habilitação).
- `logger_app.py` — logging padronizado em `app.log` (rotação 1MB × 3).
- `download_atividades.py` — gera planilha `atividades_ativas.xlsx`.
- `atualizar_redmine.py` — aplica alterações da planilha no Redmine (simulação ou `--aplicar`).
- `tests/` — testes automatizados (pytest; rodam sem Redmine/IA reais).
- `flet-runtime/flet-windows.zip` — binário grande (≈40MB) mantido **intencionalmente** no
  controle de versão: é o seed do cache offline do cliente desktop do Flet usado pelo
  `compilar_windows.bat` (evita download via GitHub em redes com proxy que intercepta HTTPS).
  Não é um artefato de build esquecido — não remover.
- `credenciais.txt` — (não versionar) credenciais usadas pelos scripts standalone.
- `DEVELOP.md` — guia de desenvolvimento e compilação (Windows e Linux).

## Pré-requisitos

- Python 3.10+ (testado com 3.12)
- Servidor Ollama local (para IA)

## Ambiente virtual (recomendado)

Crie um venv isolado na pasta do projeto e instale as dependências pinadas:

```bash
# Linux
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# Windows
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Dependências (versoes pinadas em requirements.txt)

- flet==0.86.5
- requests==2.34.2
- openpyxl==3.1.5

## Como executar

- App Flet (usando o venv):

```bash
# Linux
./.venv/bin/flet run app_flet.py
# Windows
.venv\Scripts\flet run app_flet.py
# (ou direto: python app_flet.py)
```

- Gerar planilha:

```bash
./.venv/bin/python download_atividades.py
```

- Atualizar Redmine (simulação):

```bash
./.venv/bin/python atualizar_redmine.py
```

- Atualizar Redmine (aplicar de fato):

```bash
./.venv/bin/python atualizar_redmine.py --aplicar
```

## Compilar executável (Windows e Linux)

Usando o `flet pack` (PyInstaller) — compile **na própria plataforma**:

```bash
# Linux -> dist/RedmineAssitant
./.venv/bin/flet pack app_flet.py -n RedmineAssitant -y

# Windows -> dist\RedmineAssitant.exe
.venv\Scripts\flet pack app_flet.py -n RedmineAssitant -y
```

Detalhes, opções e a alternativa `flet build` (installer/bundle) estão em
[`DEVELOP.md`](DEVELOP.md).

## Configuração

- Você pode configurar URL do Redmine, login, senha, API key e o provedor de IA pelo app.
- Na tela de configuração escolha o **provedor de IA** (Ollama por padrão, ou OpenAI, Claude,
  Gemini, Kimi), informe a chave de API, URL e modelo, e opcionalmente ajuste **temperatura**,
  **máximo de tokens** e um **prompt system** personalizado. Tudo é salvo em `config.json`.
- Selecione as **ferramentas** que a IA pode usar (listadas em `ferramentas.py`). Apenas as
  habilitadas entram no prompt do assistente e podem ser executadas.
- Para scripts standalone, preencha `credenciais.txt` (não commite esse arquivo).

## Testes

Os testes rodam **sem** um Redmine real e **sem** provedor de IA (dependências são
isoladas com `monkeypatch`/dublês). Instale o `pytest` (em `requirements-dev.txt`) e:

```bash
./.venv/bin/pip install -r requirements-dev.txt   # inclui pytest
./.venv/bin/python -m pytest -q
```

O CI (`.github/workflows/tests.yml`) executa `pytest` em pushes/PRs. Cobertura: leitura
de config e credenciais, `normalizar_data`, `get_activity_id_padrao`, SQLite local e a
execução de ações (`acoes.py`).

## Segurança

- Não versione `credenciais.txt`, `config.json`, `assistente_local.db` nem `atividades_ativas.xlsx` —
  todos estão protegidos no `.gitignore` da raiz (junto com `.venv/`, `dist/`, `build/`, `.pytest_cache/` e logs).
- Ações da IA que **gravam** no Redmine exigem confirmação do usuário na interface antes
  de aplicar (proteção contra prompt injection). Pode-se desligar essa etapa via opção
  "avançado" na tela de Configuração.
- Erros silenciosos (ex.: issue inexistente em `atualizar_redmine.py`) ficam registrados
  em `app.log` ao lado do app (rotação de 1MB × 3) para diagnóstico sem console.
- O arquivo `assistente_local.db` (SQLite) guarda histórico de conversas e prioridades localmente — não é enviado para a nuvem.
- Recomendação: usar variáveis de ambiente ou cofre de credenciais em produção.
