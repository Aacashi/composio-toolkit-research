import json
from pathlib import Path

gt = {r["app_name"]: r for r in json.loads(Path("ground_truth.json").read_text(encoding="utf-8"))["rows"]}
run = {r["app_name"]: r for r in json.loads(Path("data/run_v10.json").read_text(encoding="utf-8"))}
fields = ["access_tier", "auth_primary", "api_type", "mcp_exists"]
apps = json.loads(Path("data/apps_10.json").read_text(encoding="utf-8"))
names = [a["app_name"] for a in apps]

tot = den = 0
print(f"{'app':12} {'tier':22} {'auth':12} {'api':8} {'mcp':16} score")
for name in names:
    r = run.get(name, {})
    g = gt.get(name)
    if not g:
        print(name, "NO GT")
        continue
    hits = 0
    cells = []
    for f in fields:
        rv, gv = r.get(f), g.get(f)
        ok = rv == gv
        hits += int(ok)
        den += 1
        tot += int(ok)
        cells.append(("OK" if ok else f"{rv}")[:20])
    print(
        f"{name:12} {cells[0]:22} {cells[1]:12} {cells[2]:8} {cells[3]:16} {hits}/4"
    )
    if r.get("flags"):
        print(f"  flags={r.get('flags')[:5]} notes={(r.get('notes') or '')[:80]}")
print(f"TOTAL {tot}/{den} = {100 * tot / den:.1f}%")
