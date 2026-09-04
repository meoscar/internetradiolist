#!/usr/bin/env python3
"""移除電台清單中的重複項目（以串流網址為準,保留第一次出現的那筆）。

用法:
  python3 dedupe_stations.py music_worldradio.json            預覽,不寫檔
  python3 dedupe_stations.py music_worldradio.json --write    實際寫入（先備份 .bak）
"""
import json, sys, shutil, pathlib


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    write = "--write" in sys.argv
    if not args:
        print(__doc__)
        return 1

    for path in args:
        p = pathlib.Path(path)
        doc = json.loads(p.read_text("utf-8"))

        if isinstance(doc, list):
            items, container, key = doc, None, None
        else:
            key = next(k for k, v in doc.items() if isinstance(v, list) and v and isinstance(v[0], dict))
            items, container = doc[key], doc

        seen, kept, dropped = set(), [], []
        for m in items:
            src = m.get("source") if isinstance(m, dict) else None
            if src and src in seen:
                dropped.append(m.get("title"))
                continue
            if src:
                seen.add(src)
            kept.append(m)

        print(f"{path}: {len(items)} → {len(kept)}  (移除 {len(dropped)} 筆重複)")
        for t in dropped[:5]:
            print(f"    - {t}")
        if len(dropped) > 5:
            print(f"    ... 另有 {len(dropped)-5} 筆")

        if write and dropped:
            shutil.copy2(p, str(p) + ".bak")
            if container is None:
                out = kept
            else:
                container[key] = kept
                out = container
            p.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", "utf-8")
            print(f"    已寫入,原檔備份為 {p}.bak")
        elif dropped:
            print("    （預覽模式,加 --write 才會實際修改）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
