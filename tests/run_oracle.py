"""Phase-0 test oracle: each demo event must produce the expected signed impacts.
Run from project root:  python -m tests.run_oracle   (fresh graph per event)"""
import json, importlib, pathlib, sys
cases = json.loads((pathlib.Path(__file__).parent / "demo_events.json").read_text())
fails = 0
for c in cases:
    from backend import graph_engine
    importlib.reload(graph_engine)               # fresh graph so cases are independent
    r = graph_engine.analyze(c["news"])
    got = {a["name"]: a["impact"] for a in r.get("affected_assets", [])}
    ok = r.get("start_node") == c["start"]
    print(f"\n== {c['name']}  start={r.get('start_node')} (want {c['start']}) {'OK' if ok else 'FAIL'}")
    for k, want in c["expect"].items():
        g = got.get(k); good = g == want; ok &= good
        print(f"   {'OK  ' if good else 'FAIL'} {k:28s} want {want:+d} got {g}")
    fails += (not ok)
print("\nALL PASSED" if not fails else f"\n{fails} CASE(S) FAILED"); sys.exit(1 if fails else 0)
