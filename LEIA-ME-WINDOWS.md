# Build do RedmineAssitant para Windows (guia rápido)

Este pacote contém o código-fonte completo do assistente (Flet) e tudo o que é
necessário para gerar o executável **`RedmineAssitant.exe`** em uma máquina
Windows. Nenhum segredo/credencial está incluído (config.json e credenciais
são criados pelo app na pasta do executável, na primeira execução).

## Conteúdo do pacote

```
RedmineAssitant-build-windows/
├── compilar_windows.bat   <-- SCRIPT DE BUILD (roda tudo sozinho)
├── LEIA-ME-WINDOWS.md     <-- este guia
├── RUNBOOK-WINDOWS.md     <-- passo a passo detalhado + troubleshooting
├── DEVELOP.md             <-- guia de desenvolvimento geral
├── README.md              <-- sobre o app
├── RedmineAssitant.spec    <-- spec PyInstaller (referência)
├── app_flet.py            <-- entrada do app (UI Flet)
├── redmine_api.py         <-- cliente REST do Redmine
├── ollama_client.py       <-- cliente multi-provedor de IA
├── ferramentas.py         <-- catálogo de ferramentas/ações
├── config_manager.py      <-- config.json (criado em runtime)
├── paths.py               <-- resolução de caminhos (dev vs compilado)
├── assistente_db.py       <-- banco local de conversas/notas
├── download_atividades.py / atualizar_redmine.py  <-- utilitários
└── requirements.txt / requirements-dev.txt        <-- versões pinadas
```

## Requisitos mínimos na máquina de build

- Windows 10/11 **64 bits**
- Python 3.10–3.12 **64 bits** (site oficial, com *"Add python.exe to PATH"*);
  o launcher `py` padrão do Windows é o método recomendado
- Internet na primeira execução (o Flet CLI baixa `flet-cli`/`flet-desktop`)
- ⚠️ **Sem cross-compile:** o build precisa rodar em Windows. Compilar no Linux
  gera binário Linux.

## Como compilar

1. Extraia o zip em uma pasta local (ex.: `C:\Apps\RedmineAssitant`).
2. Dê dois cliques em **`compilar_windows.bat`** (ou execute pelo Prompt/CMD):

   ```bat
   compilar_windows.bat                REM ícone padrão
   compilar_windows.bat meu.ico        REM com ícone próprio (.ico)
   compilar_windows.bat meu.ico debug  REM build com console para logs
   ```

   O script:
   1. cria o `.venv` (Python 3.12, com fallback para 3.x);
   2. instala `requirements.txt` + `requirements-dev.txt`;
   3. roda `py_compile` como sanity check;
   4. gera o executável com `flet pack` (PyInstaller `--onefile --noconsole`);
   5. entrega em **`dist\RedmineAssitant.exe`**.

## Testando o executável

```bat
mkdir C:\RedmineAssitant
copy dist\RedmineAssitant.exe C:\RedmineAssitant\
cd C:\RedmineAssitant
RedmineAssitant.exe
```

1. Na 1ª execução ele cria `config.json` e `assistente_local.db` **na mesma
   pasta do exe**.
2. Preencha URL/API key do Redmine e o provedor de IA em **Configuração**,
   salve e teste.
3. Feche e reabra — dados persistem.

## Distribuição/atualização

- Entregue **somente** o `RedmineAssitant.exe`.
- Para atualizar em uma máquina que já usa o app: substitua o `.exe` na pasta
  existente (não apague a pasta — preserva `config.json` e o banco local).

## Dúvidas / problemas

Veja a seção "Solução de problemas" do `RUNBOOK-WINDOWS.md` (falso positivo do
antivírus, SmartScreen, 1ª abertura lenta, ícone, etc.).
## Nota de encoding (importante)

`compilar_windows.bat` é **ASCII puro com fim de linha CRLF (sem BOM)** — é o
único formato que o `cmd.exe` lê corretamente. **Não** edite o `.bat` com
editores que salvem em UTF-8/BOM ou LF, senão o build quebra com erros tipo
`'cal' não é reconhecido...` / `'65001' não é...` (sintomas do arquivo lido na
code page errada). Se precisar alterar, salve como ANSI/ASCII com CRLF.

## Troubleshooting

### SSL: CERTIFICATE_VERIFY_FAILED (erro do GitHub)
Se o build parar com `[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local
issuer certificate`, é o download do cliente Flet sendo bloqueado por proxy
corporativo/antivirus que intercepta HTTPS. O `compilar_windows.bat` já evita
isso: o cliente Flet v0.86.5 vem embutido em `flet-runtime\flet-windows.zip`
e é colocado no cache local sem precisar baixar nada do GitHub.
Basta rodar o script normalmente.

### "Python 3.13+ detected ... [WARN]"
O aviso é normal se o Windows só tiver Python 3.13/3.14 instalado. Flet 0.86.5
e PyInstaller 6.22.2 são testados com **Python 3.10-3.12**. Se o build falhar
depois desse aviso, instale o Python 3.12 (em "Add to PATH") e rode de novo
(o script usa 3.12 preferencialmente).

### O script não "enxerga" o Python
Instale o Python 3.10-3.12 marcando **"Add python.exe to PATH"** e reinstale o
"py launcher" se necessário (`py --version` para testar).
