# -*- coding: utf-8 -*-
"""把某个 IP 的访问轨迹按时间摊开，用来判断是真人还是扫描器。"""
import json
from pathlib import Path

IP = "103.158.14.150"
rows = []
for line in Path("logs/visits.jsonl").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("ip") == IP:
        rows.append(d)

print(f"{IP} 共 {len(rows)} 条记录\n")
for d in sorted(rows, key=lambda x: x.get("at", "")):
    print(json.dumps(d, ensure_ascii=False))
