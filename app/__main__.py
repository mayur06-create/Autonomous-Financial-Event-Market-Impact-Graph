import argparse
import json

from . import pipeline, server
from .kb import KnowledgeBase


def main():
    ap = argparse.ArgumentParser(prog="python -m app")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start dashboard + API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    i = sub.add_parser("ingest", help="fetch + process news into the knowledge base")
    i.add_argument("--mode", choices=["sample", "live"], default="sample")
    i.add_argument("--search")
    i.add_argument("--symbols")
    i.add_argument("--limit", type=int, default=10)
    i.add_argument("--pages", type=int, default=1)
    i.add_argument("--force", action="store_true")
    sub.add_parser("reset", help="empty the knowledge base")
    a = ap.parse_args()
    kb = KnowledgeBase()
    if a.cmd == "serve":
        server.serve(a.host, a.port, kb)
    elif a.cmd == "ingest":
        out = pipeline.run_ingest(kb, mode=a.mode, force=a.force, search=a.search, symbols=a.symbols,
                                  limit=a.limit, pages=a.pages)
        print(json.dumps(out, indent=2))
        print(kb.stats())
    else:
        kb.reset()
        print("knowledge base emptied")


main()
