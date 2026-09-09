# Runbook — Compilação do app para Windows

Objetivo: gerar o executável **`RedmineAssitant.exe`** (portátil, *one-file*, sem
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
- Internet para o `pip` instalar as dependências na 1ª vez.
- O **cliente Flet** (runtime v0.86.5) já vem embutido em
  `flet-runtime\flet-windows.zip` — o `compilar_windows.bat` o coloca no cache
  local automaticamente, **sem baixar nada do GitHub** (evita o erro
  `CERTIFICATE_VERIFY_FAILED` em redes corporativas).
- (Alternativa) Flutter SDK + Visual Studio 2022 (workload C++) apenas se usar
  `flet build windows` — ver Seção 9.

## 2. Preparar a pasta do projeto

Copie o projeto para um local de build, **sem** os artefatos/penduricalhos:

```
robocopy "origem" C:\Apps\RedmineAssitant /E /XD .venv dist build __pycache__
del /Q C:\Apps\RedmineAssitant\config.json
del /Q C:\Apps\RedmineAssitant\assistente_local.db
del /Q C:\Apps\RedmineAssitant\credenciais*.txt
```

> `config.json` e `credenciais*.txt` contêm segredos e **não** devem sair da
> máquina de desenvolvimento.

## 3. Criar o venv e instalar dependências (PowerShell)

O `compilar_windows.bat` já faz isso sozinho. Manualmente:

```powershell
cd C:\Apps\RedmineAssitant
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
.venv\Scripts\flet pack app_flet.py -n RedmineAssitant -i caminho\logo.ico -y
```

- Saída: **`dist\RedmineAssitant.exe`** (≈ 30–60 MB).
- `-i` (ícone) é opcional — exige arquivo `.ico`; sem ele usa o ícone padrão
  do Flet.
- O `flet pack` usa PyInstaller `--onefile --noconsole` (sem console/CMD).
- No 1º `flet pack` o script seeda o runtime embutido
  (`flet-runtime\flet-windows.zip`) em `%USERPROFILE%\.flet\client\`.

## 6. Verificação pós-build (obrigatório)

```powershell
mkdir C:\RedmineAssitant
copy dist\RedmineAssitant.exe C:\RedmineAssitant\
cd C:\RedmineAssitant
.\RedmineAssitant.exe
```

1. Na 1ª execução o app cria `config.json` e `assistente_local.db` **na mesma
   pasta** do executável (comportamento de `paths.py` em modo compilado).
2. Preencha URL/API key do Redmine e o provedor de IA na aba **Configuração**,
   salve e teste a conexão.
3. Feche e reabra — os dados devem persistir (config + banco não somem).

## 7. Distribuição / atualização

- Entregue **somente** `RedmineAssitant.exe` (arquivo único, independe do Python
  instalado no destino).
- Crie um atalho apontando para o `.exe` se quiser iniciar pela área de trabalho.
- Para distribuir a versão a outro usuário: substituir o `.exe` na pasta
  existente **preserva** o `config.json` e o banco local (não apagar a pasta!).

## 8. Solução de problemas

| Sintoma | Ação |
|---|---|
| `No module named 'PyInstaller'` em `flet pack` | instalar `requirements-dev.txt` |
| `[SSL: CERTIFICATE_VERIFY_FAILED]` | proxy/antivírus interceptando HTTPS; o `compilar_windows.bat` já contorna usando o runtime embutido em `flet-runtime\` |
| Aviso "*Python 3.13+ detected*" | normal se só houver Python 3.13/3.14; instalar Python 3.12 e rodar de novo (o script prioriza 3.12) |
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
.venv\Scripts\flet build windows --project RedmineAssitant
```

Detalhes: `.venv\Scripts\flet build windows --help`. Para a maioria dos casos o
**`flet pack` (Seção 5) é o caminho recomendado** (simples, sem Flutter).

## 10. Referências

- `LEIA-ME-WINDOWS.md` — guia rápido de build (ponto de partida).
- `DEVELOP.md` — guia geral de desenvolvimento/compilação (Linux e Windows).
- `requirements.txt` / `requirements-dev.txt` — versões pinadas.
- `paths.py` — resolução de caminhos em modo compilado (dados ao lado do `.exe`).