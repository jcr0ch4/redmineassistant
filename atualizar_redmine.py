"""Atualiza o Redmine com os lançamentos feitos na planilha atividades_ativas.xlsx.

Lê a planilha gerada por download_atividades.py e, para cada linha, envia ao Redmine:
  - mudança de status (coluna Status)
  - percentual concluído (coluna % Concluído)
  - nova data prevista (coluna Data Prevista)
  - apontamento de horas (coluna Horas Apontadas) com comentário (coluna Comentário)

Somente envia valores que foram alterados em relação ao estado original do Redmine.
Por segurança, não altera/remove nada além dos campos listados acima.

Uso:
    python atualizar_redmine.py                 # simula (não envia nada)
    python atualizar_redmine.py --aplicar       # envia de fato as alterações
"""

import argparse
from pathlib import Path

from openpyxl import load_workbook

from logger_app import get_logger
from config_manager import carregar_config
from redmine_api import criar_api_da_config, normalizar_data

BASE_DIR = Path(__file__).resolve().parent
ARQUIVO_PLANILHA = BASE_DIR / "atividades_ativas.xlsx"

COLUNA = {
    "ID": 1,
    "Status": 4,
    "Data Prevista": 8,
    "Porcentagem": 9,
    "Horas Apontadas": 12,
    "Comentario": 13,
}


def ler_planilha(caminho: Path) -> list[dict]:
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Planilha não encontrada: {caminho}. Rode antes o download_atividades.py")
    wb = load_workbook(caminho, data_only=True)
    ws = wb["Ativos"]
    linhas = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        issue_id = row[COLUNA["ID"] - 1]
        if issue_id is None:
            continue
        linhas.append({
            "issue_id": int(issue_id),
            "status": (row[COLUNA["Status"] - 1] or "").strip(),
            "due_date": row[COLUNA["Data Prevista"] - 1],
            "done_ratio": row[COLUNA["Porcentagem"] - 1],
            "horas": row[COLUNA["Horas Apontadas"] - 1],
            "comentario": row[COLUNA["Comentario"] - 1],
        })
    return linhas


def _valor_celula(valor):
    """Converte o valor da célula para o tipo adequado (vazio -> None)."""
    if valor in (None, ""):
        return None
    return valor


def main(aplicar: bool, planilha: Path = ARQUIVO_PLANILHA):
    api = criar_api_da_config()
    status_ids = api.get_status_ids()
    status_validos = set(status_ids)
    linhas = ler_planilha(planilha)
    # % concluído: só é enviado se habilitado nas Configurações do app
    permitir_pct = bool(carregar_config().get("atualizar_percentual", False))

    print(f"{'APLICANDO' if aplicar else 'SIMULAÇÃO'} - {len(linhas)} atividades na planilha")
    print("-" * 70)

    alteracoes = 0
    apontamentos = 0

    for item in linhas:
        issue_id = item["issue_id"]
        try:
            issue = api.get_issue(issue_id)
        except Exception:
            continue

        status_atual = (issue.get("status") or {}).get("name")
        done_atual = issue.get("done_ratio") or 0

        novo_status = item["status"]
        novo_done = item["done_ratio"]
        novo_due = normalizar_data(_valor_celula(item["due_date"]))
        horas = item["horas"]
        comentario = (item["comentario"] or "").strip()

        # --- validações ---
        if novo_status and novo_status not in status_validos:
            lista_opcoes = ", ".join(sorted(status_validos)) or "nenhum"
            print(f"  #{issue_id}: status inválido '{novo_status}' — ignorado (use um dos status do Redmine: {lista_opcoes}).")
            continue
        if novo_done is not None:
            try:
                novo_done = int(novo_done)
                if not 0 <= novo_done <= 100:
                    print(f"  #{issue_id}: % fora do intervalo 0-100 — ignorado.")
                    continue
            except (TypeError, ValueError):
                print(f"  #{issue_id}: % inválido — ignorado.")
                continue

        payload = {}
        if novo_status and novo_status != status_atual:
            payload["status_id"] = api.get_status_ids().get(novo_status)
            print(f"  #{issue_id}: status {status_atual} -> {novo_status}")
        # % concluído: só envia se permitido nas Configurações E junto com mudança de status
        if (
            novo_done is not None
            and novo_done != int(done_atual)
            and permitir_pct
            and "status_id" in payload
        ):
            payload["done_ratio"] = novo_done
            print(f"  #{issue_id}: % {done_atual} -> {novo_done}")

        due_atual = issue.get("due_date")
        if novo_due and novo_due != due_atual:
            payload["due_date"] = novo_due
            print(f"  #{issue_id}: data prevista {due_atual} -> {novo_due}")

        if payload and aplicar:
            api.atualizar_issue(issue_id, **payload)
            alteracoes += 1
        elif payload:
            alteracoes += 1

        # --- apontamento de horas ---
        if horas:
            try:
                horas = float(horas)
                if horas <= 0:
                    print(f"  #{issue_id}: horas inválidas ({horas}) — ignorado.")
                    continue
            except (TypeError, ValueError):
                print(f"  #{issue_id}: horas inválidas ({horas}) — ignorado.")
                continue

            print(f"  #{issue_id}: apontar {horas}h ({comentario or 'sem comentário'})")
            if aplicar:
                api.lancar_horas(issue_id, horas, comentario)
            apontamentos += 1

    print("-" * 70)
    if aplicar:
        print(f"Concluído. {alteracoes} issue(s) alteradas, {apontamentos} apontamentos de horas.")
    else:
        print(f"[SIMULAÇÃO] Seriam {alteracoes} issue(s) alteradas, {apontamentos} apontamentos de horas.")
        print("Rode com --aplicar para enviar as alterações ao Redmine.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Atualiza o Redmine a partir da planilha de atividades.")
    parser.add_argument("--aplicar", action="store_true", help="Envia as alterações ao Redmine (sem isso, apenas simula).")
    args = parser.parse_args()
    main(args.aplicar)
