# Runbook — Compilação do app para Windows

Objetivo: gerar o executável **`RedmineWheaton.exe`** (portátil, *one-file*, sem
janela de console) a partir do `app_flet.py`.

Ferramenta: `flet pack` (Flet CLI + **PyInstaller**, modo `--onefile --noconsole`).

> ⚠️ **Sem cross-compile**: o build precisa ser feito **dentro do Windows**.
> Executar o `flet pack` no Linux produz um binário Linux.

---

## 1. Pré-requisitos (máquina Windows)

- Windows 10/11 **64 bits**.
- Python 3.10–3.12 **64 bits** instalado do site oficial (marque
  *"Add python.exe to PATH"*). Recomendado: `py -3.12`.
- Git (opcional — necessário apenas para a alternativa `flet build`).
- Internet na primeira execução do CLI (o Flet baixa `flet-cli`/`flet-desktop`
  automaticamente na primeira chamada).
- (Alternativa) Flutter SDK + Visual Studio 2022 (workload C++) apenas se usar
  `flet build windows` — ver Seção 9.

## 2. Preparar a pasta do projeto

Copie o projeto para um local de build, **sem** os artefatos/penduricalhos:

```
robocopy "origem" C:\Apps\RedmineWheaton /E /XD .venv dist build __pycache__ openwebui
del /Q C:\Apps\RedmineWheaton\config.json
del /Q C:\Apps\RedmineWheaton\assistente_local.db
del /Q C:\Apps\RedmineWheaton\credenciais*.txt
del /Q C:\Apps\RedmineWheaton\erro.txt
```

> `config.json` e `credenciais*.txt` contêm segredos e **não** devem sair da
> máquina de desenvolvimento.

## 3. Criar o venv e instalar dependências (PowerShell)

```powershell
cd C:\Apps\RedmineWheaton
py -3 -m venv .venv
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -r requirements-dev.txt   # pyinstaller (só p/ build)
```

## 4. Sanidade antes do build

```powershell
.venv\Scripts\python -m py_compile app_flet.py ollama_client.py config_manager.py `
  ferramentas.py redmine_api.py assistente_db.py paths.py
.venv\Scripts\flet run app_flet.py
```

Confirme que o app abre e que a aba **Configuração** funciona (dropdown de
provedor, checkboxes de ferramentas).

## 5. Compilar o executável

```powershell
.venv\Scripts\flet pack app_flet.py -n RedmineWheaton -i caminho\logo.ico -y
```

- Saída: **`dist\RedmineWheaton.exe`** (≈ 30–60 MB).
- `-i` (ícone) é opcional — exige arquivo `.ico`; sem ele usa o ícone padrão
  do Flet.
- O `flet pack` usa PyInstaller `--onefile --noconsole` (sem console/CMD).

## 6. Verificação pós-build (obrigatório)

```powershell
mkdir C:\RedmineWheaton
copy dist\RedmineWheaton.exe C:\RedmineWheaton\
cd C:\RedmineWheaton
.\RedmineWheaton.exe
```

1. Na 1ª execução o app cria `config.json` e `assistente_local.db` **na mesma
   pasta** do executável (comportamento de `paths.py` em modo compilado).
2. Preencha URL/API key do Redmine e o provedor de IA na aba **Configuração**,
   salve e teste a conexão.
3. Feche e reabra — os dados devem persistir (config + banco não somem).

## 7. Distribuição / atualização

- Entregue **somente** `RedmineWheaton.exe` (arquivo único, independe do Python
  instalado no destino).
- Crie um atalho apontando para o `.exe` se quiser iniciar pela área de trabalho.
- Para distribuir a versão a outro usuário: substituir o `.exe` na pasta
  existente **preserva** o `config.json` e o banco local (não apagar a pasta!).

## 8. Solução de problemas

| Sintoma | Ação |
|---|---|
| `No module named 'PyInstaller'` em `flet pack` | instalar `requirements-dev.txt` |
| Flet CLI pede download na 1ª vez | normal; exige internet (flet-cli/flet-desktop) |
| Acusa falso positivo (Defender/antivírus) | one-file do PyInstaller é alvo comum; adicionar exceção ou assinar com certificado |
| SmartScreen "Protegido pelo Windows" | opção "Mais informações → Executar assim mesmo" (exe sem assinatura) |
| 1ª abertura demora / disco aumentando | esperado: extrai para `%TEMP%\_MEI*` e usa cache; one-file |
| Quer ver o log/erro do app | rebuild com `-D` (abre console de debug) ou teste em dev com `flet run` |
| `Missing module X` no build | adicionar `--hidden-import X` (ou `--pyinstaller-build-args`) |
| Executável com tamanho grande | normal para Flet (Flutter engine embutido) |

## 9. (Opcional) `flet build windows` — instalador/bundle

Alternativa que gera **instalador** com metadados/ícone, porém exige:

- Flutter SDK configurado no `PATH`;
- Visual Studio 2022 com workload **Desktop development with C++**.

```powershell
.venv\Scripts\flet build windows --project RedmineWheaton
```

Detalhes: `.venv\Scripts\flet build windows --help`. Para a maioria dos casos o
**`flet pack` (Seção 5) é o caminho recomendado** (simples, sem Flutter).

## 10. Referências

- `DEVELOP.md` — guia geral de desenvolvimento/compilação (Linux e Windows).
- `MEMORY.md` — estado técnico do projeto.
- `requirements.txt` / `requirements-dev.txt` — versões pinadas.
- `paths.py` — resolução de caminhos em modo compilado (dados ao lado do `.exe`).