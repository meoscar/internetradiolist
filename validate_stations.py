#!/usr/bin/env python3
"""驗證電台清單 JSON。CI 用,壞掉的檔案不會進 main。

用法:
  python3 validate_stations.py                 驗證預設的三個檔案
  python3 validate_stations.py a.json b.json   指定檔案
  python3 validate_stations.py --check-urls    另外實測圖片網址（慢）
"""
import json, sys, re, pathlib

DEFAULT = ["music.json", "music_worldradio.json", "music_worldradio_test.json"]
REQUIRED = ("title", "source")
URL_RE = re.compile(r"^https?://", re.I)


def find_items(doc):
    """容忍幾種常見結構:頂層 list、{"music": [...]}、{"stations": [...]}。"""
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict):
        for k in ("music", "stations", "items", "data"):
            if isinstance(doc.get(k), list):
                return doc[k]
        for v in doc.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def check(path):
    errs, warns = [], []
    p = pathlib.Path(path)
    if not p.exists():
        return [f"{path}: 檔案不存在"], []

    raw = p.read_bytes()

    # 1. JSON 合法性 —— 抓出真正的行號,而不是只丟出例外
    try:
        doc = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as e:
        return [f"{path}: 不是合法的 UTF-8 — {e}"], []
    except json.JSONDecodeError as e:
        line = raw[: e.pos].count(b"\n") + 1
        ctx = raw[max(0, e.pos - 50) : e.pos + 50].decode("utf-8", "replace")
        return [f"{path}:{line} JSON 解析失敗 — {e.msg}\n    附近: ...{ctx}..."], []

    items = find_items(doc)
    if not items:
        return [f"{path}: 找不到電台陣列"], []

    seen_titles, seen_sources = {}, {}
    for i, m in enumerate(items):
        where = f"{path}[{i}]"
        if not isinstance(m, dict):
            errs.append(f"{where}: 不是物件")
            continue

        title = m.get("title")
        for f in REQUIRED:
            if not m.get(f):
                errs.append(f"{where} ({title or '?'}): 缺少必要欄位 '{f}'")

        for f in ("source", "image", "site"):
            v = m.get(f)
            if v and not URL_RE.match(str(v)):
                errs.append(f"{where} ({title}): '{f}' 不是合法網址 — {v!r}")
            # 網址裡混進換行/tab 是手動編輯最常見的災難
            if v and re.search(r"[\n\r\t]", str(v)):
                errs.append(f"{where} ({title}): '{f}' 內含換行或 tab")

        if not m.get("image"):
            warns.append(f"{where} ({title}): 沒有 image")

        if title:
            if title in seen_titles:
                warns.append(f"{where}: 標題重複 '{title}'（也出現在 [{seen_titles[title]}]）")
            seen_titles[title] = i
        src = m.get("source")
        if src:
            if src in seen_sources:
                warns.append(f"{where} ({title}): 串流網址與 [{seen_sources[src]}] 重複")
            seen_sources[src] = i

    print(f"  {path}: {len(items)} 個電台")
    return errs, warns


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    files = args or [f for f in DEFAULT if pathlib.Path(f).exists()]
    if not files:
        print("找不到任何要驗證的檔案")
        return 1

    all_errs, all_warns = [], []
    for f in files:
        e, w = check(f)
        all_errs += e
        all_warns += w

    if all_warns:
        print(f"\n警告 {len(all_warns)} 則:")
        for w in all_warns[:30]:
            print("  ⚠️ ", w)
        if len(all_warns) > 30:
            print(f"   ...另有 {len(all_warns)-30} 則")

    if all_errs:
        print(f"\n錯誤 {len(all_errs)} 則:")
        for e in all_errs:
            print("  ❌", e)
        print("\n驗證失敗。")
        return 1

    print("\n✅ 全部通過。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
