"""Interface de linha de comando.

    python -m rmbh_scraper crawl [--data-dir data] [--images] [--workers 4] [--no-view]
    python -m rmbh_scraper view [--data-dir data] [--port 8000]
    python -m rmbh_scraper get 3240 --purpose venda
    python -m rmbh_scraper search --purpose venda --type 2 [--bedrooms 3] [--neighborhood 44]
    python -m rmbh_scraper types --purpose aluguel
    python -m rmbh_scraper neighborhoods --purpose venda --type 2
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import __version__
from .client import RENT, SALE, RMBHClient
from .crawler import Crawler

PURPOSE_ARG = {"rent": RENT, "aluguel": RENT, "1": RENT, "sale": SALE, "venda": SALE, "2": SALE}

# argparse's built-in messages ("usage:", "show this help message", errors) in pt-BR.
_ARGPARSE_PT = {
    "usage: ": "uso: ",
    "positional arguments": "argumentos posicionais",
    "options": "opções",
    "show this help message and exit": "mostra esta ajuda e sai",
    "the following arguments are required: %s": "os seguintes argumentos são obrigatórios: %s",
    "%(prog)s: error: %(message)s\n": "%(prog)s: erro: %(message)s\n",
    "invalid choice: %(value)r (choose from %(choices)s)": "opção inválida: %(value)r (escolha entre %(choices)s)",
    "unrecognized arguments: %s": "argumentos não reconhecidos: %s",
    "invalid %(type)s value: %(value)r": "valor %(type)s inválido: %(value)r",
    "expected one argument": "esperado um argumento",
    "argument %(argument_name)s: %(message)s": "argumento %(argument_name)s: %(message)s",
}
argparse._ = lambda s: _ARGPARSE_PT.get(s, s)  # type: ignore[attr-defined]


def _purpose(v: str) -> int:
    try:
        return PURPOSE_ARG[v.lower()]
    except KeyError:
        raise argparse.ArgumentTypeError("a finalidade deve ser aluguel ou venda") from None


def _dump(obj) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _summary(report: dict) -> dict:
    c = report.get("counts", {})
    out = {
        "início": report.get("started_at"),
        "fim": report.get("finished_at"),
        "novos": len(report.get("added", [])),
        "alterados": len(report.get("changed", [])),
        "removidos": len(report.get("removed", [])),
        "fora_da_busca": len(report.get("unlisted", [])),
        "ativos": c.get("active"),
        "ativos_aluguel": c.get("active_rent"),
        "ativos_venda": c.get("active_sale"),
        "total_de_registros": c.get("total_records"),
    }
    if "images_downloaded" in report:
        out["imagens_baixadas"] = report["images_downloaded"]
        out["imagens_com_falha"] = report["images_failed"]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rmbh_scraper", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true", help="mostra mensagens detalhadas")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}", help="mostra a versão e sai")
    ap.add_argument("--delay", type=float, default=0.25, help="intervalo mínimo em segundos entre requisições (padrão 0,25)")
    sub = ap.add_subparsers(dest="cmd", required=True, title="comandos", metavar="COMANDO")

    c = sub.add_parser("crawl", help="coleta completa + atualização incremental da base JSON")
    c.add_argument("--data-dir", default="data", help="pasta dos dados (padrão: data)")
    c.add_argument("--images", action="store_true", help="baixa as fotos dos imóveis (somente as novas)")
    c.add_argument("--workers", type=int, default=4, help="requisições em paralelo (padrão 4)")
    c.add_argument("--purpose", type=_purpose, action="append", help="limita a aluguel ou venda (pode repetir)")
    c.add_argument("--force", action="store_true", help="aceita uma coleta que encontrou bem menos imóveis que a anterior")
    c.add_argument("--no-view", action="store_true", help="não abre a apresentação ao final da coleta")
    c.add_argument("--port", type=int, default=8000, help="porta da apresentação (padrão 8000)")
    c.add_argument("--no-browser", action="store_true", help="inicia o servidor da apresentação sem abrir o navegador")

    v = sub.add_parser("view", help="abre a apresentação com os dados atuais")
    v.add_argument("--data-dir", default="data", help="pasta dos dados (padrão: data)")
    v.add_argument("--port", type=int, default=8000, help="porta (padrão 8000)")
    v.add_argument("--host", default="127.0.0.1", help="endereço do servidor (padrão 127.0.0.1)")
    v.add_argument("--no-browser", action="store_true", help="inicia o servidor sem abrir o navegador")

    g = sub.add_parser("get", help="busca os detalhes de um imóvel")
    g.add_argument("code", type=int, help="código do imóvel")
    g.add_argument("--purpose", type=_purpose, required=True, help="aluguel ou venda")

    s = sub.add_parser("search", help="faz uma busca e mostra os resultados")
    s.add_argument("--purpose", type=_purpose, required=True, help="aluguel ou venda")
    s.add_argument("--type", type=int, default=0, help="id do tipo de imóvel (veja `types`); 0 = todos")
    s.add_argument("--bedrooms", type=int, help="número mínimo de quartos")
    s.add_argument("--neighborhood", type=int, action="append", help="id do bairro (pode repetir)")

    t = sub.add_parser("types", help="lista os tipos de imóvel de uma finalidade")
    t.add_argument("--purpose", type=_purpose, required=True, help="aluguel ou venda")

    n = sub.add_parser("neighborhoods", help="lista os bairros de uma finalidade + tipo")
    n.add_argument("--purpose", type=_purpose, required=True, help="aluguel ou venda")
    n.add_argument("--type", type=int, required=True, help="id do tipo de imóvel")

    a = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    client = RMBHClient(min_interval=a.delay)

    if a.cmd == "crawl":
        crawler = Crawler(
            client,
            data_dir=a.data_dir,
            workers=a.workers,
            download_images=a.images,
            purposes=tuple(a.purpose) if a.purpose else (RENT, SALE),
        )
        report = crawler.run(force=a.force)
        _dump(_summary(report))
        if a.no_view:
            return 0
        if not sys.stdin.isatty():
            # scheduled/unattended run (cron, CI): don't block on a web server
            logging.getLogger(__name__).info(
                "execução sem terminal: apresentação não aberta (use o comando `view` para abri-la)"
            )
            return 0
        from .viewer import serve

        serve(a.data_dir, port=a.port, open_browser=not a.no_browser)
    elif a.cmd == "view":
        from .viewer import serve

        serve(a.data_dir, host=a.host, port=a.port, open_browser=not a.no_browser)
    elif a.cmd == "get":
        d = client.get_listing(a.code, a.purpose)
        if d is None:
            print(f"imóvel {a.code} não encontrado", file=sys.stderr)
            return 1
        _dump(d)
    elif a.cmd == "search":
        _dump(client.search(a.purpose, a.type, bedrooms=a.bedrooms, neighborhoods=a.neighborhood))
    elif a.cmd == "types":
        _dump(client.get_property_types(a.purpose))
    elif a.cmd == "neighborhoods":
        _dump(client.get_neighborhoods(a.purpose, a.type))
    return 0
