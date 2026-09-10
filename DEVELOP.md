# Desenvolvimento e compilação

Guia de ambiente de desenvolvimento e de **compilação para executáveis** no
Redmine-Assitant, cobrindo **Windows** e **Linux**.

> O app usa o Flet (0.86.5 pinado em `requirements.txt`). A API de controles
> segue o Flet Material 3 — atenção ao usar `ft.DropdownOption(key=, text=)` e
> o evento `on_select` (substituíram `ft.dropdown.Option`/`on_change`).

---

## 1. Ambiente virtual (venv isolado)

Crie o venv **na pasta do projeto** (`.venv`) para não depender do Python
global nem de venvs de outros projetos.

### Linux

```bash
cd "redmineassistant"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
```

### Windows

```bat
cd "redmineassistant"
py -3 -m venv .venv
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt
```

> Requisito: Python 3.10+ (testado com 3.12). O `.venv` não é versionado
> (ver `.gitignore`).

> **Desenvolvimento/testes**: instale também `requirements-dev.txt` (inclui `pytest`):
>
> ```bash
> ./.venv/bin/pip install -r requirements-dev.txt   # pytest; pyinstaller só p/ build Windows
> ```

---

## 1.1 Versionamento do app

A versão tem **fonte única de verdade** em `versao.py` (`APP_VERSAO`) e é exibida:

- na aba **Configuração** do app (rodapé "Sobre");
- via linha de comando: `python app_flet.py --version`;
- nos metadados do executável Windows (`version_info.txt` → propriedade "Detalhes"
  do `.exe`, usada por `RedmineAssistant.spec` quando o build é via PyInstaller).

**Para publicar uma nova versão**:

1. Atualize `APP_VERSAO` em `versao.py` (ex.: `1.1.0`).
2. Atualize `filevers`/`prodvers`/`FileVersion`/`ProductVersion` em
   `version_info.txt` (manter as duas em sincronia).
3. Registre a mudança no `CHANGELOG.md` (assim que criado) e no [`roadmap.md`](../roadmap.md).
4. Crie a tag no repositório (`git tag v1.1.0`).

> O build via `flet pack` usa o nome `RedmineAssitant` (sem acento); o nome de
> produto exibido ao usuário é `APP_NOME` = "Redmine Assistant".

---

## 2. Rodar em desenvolvimento

Sempre com o venv ativado (ou usando o caminho direto do binário).

```bash
# Linux
./.venv/bin/flet run app_flet.py
./.venv/bin/python app_flet.py

# Windows
.venv\Scripts\flet run app_flet.py
.venv\Scripts\python app_flet.py
```

- `flet run` dá *hot reload* (recarrega ao salvar).
- Scripts auxiliares:
  ```bash
  ./.venv/bin/python download_atividades.py        # gera atividades_ativas.xlsx
  ./.venv/bin/python atualizar_redmine.py          # simula alterações da planilha
  ./.venv/bin/python atualizar_redmine.py --aplicar # aplica de fato
  ```

---

## 3. Compilar executável standalone (Windows e Linux)

Usamos o `flet pack` (baseado em **PyInstaller**), que gera um executável
independente do Python. Ele roda **no mesmo SO do build**:

- Windows gera um `.exe`; Linux gera um binário ELF.
- **Não é possível fazer cross-compile** (Windows do Linux ou vice-versa).
  Compile cada plataforma na própria máquina.

> **Windows**: siga o passo a passo completo em
> [`RUNBOOK-WINDOWS.md`](RUNBOOK-WINDOWS.md) (venv, build, verificação e
> troubleshooting).
> Instale antes o PyInstaller: `pip install -r requirements-dev.txt`.

### Linux

```bash
./.venv/bin/flet pack app_flet.py -n RedmineAssitant -i caminho/logo.png -y
```

Gera o executável em `dist/RedmineAssitant`.

### Windows

```bat
.venv\Scripts\flet pack app_flet.py -n RedmineAssitant -i caminho\logo.ico -y
```

Gera `dist\RedmineAssitant.exe`.

### Opções úteis do `flet pack`

```text
-n NAME        nome do executável/arquivo
-i ICON        ícone (.png/.ico)
-y             não perguntar para sobrescrever
-D             modo one-file-debug (console p/ logs)
--hidden-import MODULO   caso o PyInstaller não encontre algo
--add-data ARQ;DESTINO   empacotar arquivos adicionais
```

### O que NÃO deve ser empacotado

`config.json` e `credenciais*.txt` contêm segredos reais de ambiente. Eles
são criados/gerenciados em tempo de execução na pasta do executável pelo app —
**não** devem ser copiados para o installador nem versionados.

No primeiro uso do app compilado, preencha URL/API key do Redmine e provedor de
IA na aba **Configuração** (o `config.json` é criado ao lado do executável).

### Persistência em modo compilado

O binário do PyInstaller é `--onefile`: os módulos são extraídos para um
diretório temporário que é apagado ao fechar o app. Por isso os caminhos de
dados persistentes (`config.json`, `assistente_local.db`, `credenciais.txt`)
usam `paths.executavel_dir()` — que em modo compilado aponta para a pasta do
executável, e em modo dev para a pasta do projeto (`paths.py`).

---

## 4. Alternativa: `flet build` (instalador/bundle)

O `flet build linux` / `flet build windows` gera **pacotes instaláveis**
(com ícone, metadados etc.), porém exige SDKs externos:

- **Linux**: Flutter SDK + dependências de build (GTK), flatpak/dpkg opcional.
- **Windows**: Flutter SDK + Visual Studio C++ toolchain e Git.
- Pré-requisito: `flet build` baixa o template Flutter automaticamente.

> Para a maioria dos casos o `flet pack` (PyInstaller) é mais simples e não
> exige Flutter.

---

## 5. Tarefas de casa (saúde do código)

```bash
# Rodar a suíte de testes (sem Redmine real / sem IA — usa dublês e monkeypatch)
./.venv/bin/python -m pytest -q

# Checa sintaxe de todos os módulos
./.venv/bin/python -m py_compile app_flet.py acoes.py ollama_client.py config_manager.py \
  ferramentas.py redmine_api.py assistente_db.py logger_app.py paths.py debug_log.py \
  download_atividades.py atualizar_redmine.py

# Smoke test de imports e config
./.venv/bin/python -c "import app_flet, config_manager; print(config_manager.carregar_config().get('llm_provider'))"
```

### Testes automatizados (`tests/`)

- Suíte **offline**: não acessa Redmine nem provedor de IA.
- Cobre: `config_manager` (load/save com `tmp_path`), parse de credenciais,
  `normalizar_data`, `get_activity_id_padrao`, SQLite local (`assistente_db`) e a
  execução de ações (`acoes.py`).
- CI: `.github/workflows/tests.yml` roda `pip install -r requirements.txt -r
  requirements-dev.txt` + `pytest` em pushes/PRs.
- `app_flet.py` (UI do Flet) não tem cobertura fim a fim por design — a lógica de
  ações foi extraída para `acoes.py` justamente para permitir teste isolado.
```
