# -*- coding: utf-8 -*-
"""
v6.9 本地通达信板块映射构建器：递归搜索版

运行：
    python concept_builder_tdx_local.py "你的通达信根目录"
"""

from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
CONFIG_DIR.mkdir(exist_ok=True)


def norm_code(x) -> str:
    s = str(x).strip()
    digits = "".join(re.findall(r"\d", s))
    if len(digits) >= 6:
        return digits[-6:]
    return digits.zfill(6)


def read_text_auto(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ["gbk", "gb18030", "utf-8", "utf-16", "latin1"]:
        try:
            return raw.decode(enc, errors="ignore")
        except Exception:
            pass
    return raw.decode("gbk", errors="ignore")


def save_json(obj, name: str) -> None:
    path = CONFIG_DIR / name
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] saved {path} ({len(obj) if hasattr(obj, '__len__') else 'n/a'})")


def find_files(root: Path, names: List[str]) -> Dict[str, List[Path]]:
    wanted = {n.lower() for n in names}
    found = {n.lower(): [] for n in names}
    print(f"[SCAN] recursively searching under: {root}")
    try:
        for p in root.rglob("*"):
            if p.is_file() and p.name.lower() in wanted:
                found[p.name.lower()].append(p)
    except Exception as exc:
        print(f"[WARN] recursive search failed: {exc}")
    return found


def choose_file(paths: List[Path], prefer_keywords: List[str] | None = None) -> Path | None:
    if not paths:
        return None
    prefer_keywords = prefer_keywords or []
    def score(p: Path):
        s = 0
        text = str(p).lower()
        for kw in prefer_keywords:
            if kw.lower() in text:
                s += 10
        try:
            s += min(p.stat().st_size / 1e6, 20)
        except Exception:
            pass
        return s
    return sorted(paths, key=score, reverse=True)[0]


def parse_incon(incon_path: Path | None) -> Dict[str, str]:
    if incon_path is None or not incon_path.exists():
        print("[WARN] incon.dat not found; 行业可能只能显示代码")
        return {}

    print(f"[USE] incon.dat: {incon_path}")
    text = read_text_auto(incon_path)
    code_to_name = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("######"):
            continue
        if "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) >= 2:
            code = parts[0].strip()
            name = parts[1].strip()
            if code and name:
                code_to_name[code] = name
    print(f"[INFO] incon items: {len(code_to_name)}")
    return code_to_name


def parse_tdxhy(tdxhy_path: Path | None, incon_map: Dict[str, str]) -> Dict[str, str]:
    if tdxhy_path is None or not tdxhy_path.exists():
        print("[WARN] tdxhy.cfg not found")
        return {}

    print(f"[USE] tdxhy.cfg: {tdxhy_path}")
    text = read_text_auto(tdxhy_path)
    code_to_industry = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        stock_code = norm_code(parts[1])
        tdx_code = parts[2].strip()
        sw_code = parts[3].strip()
        industry = incon_map.get(tdx_code) or incon_map.get(sw_code) or tdx_code or sw_code
        if stock_code and industry:
            code_to_industry[stock_code] = industry

    print(f"[INFO] industry mapped codes: {len(code_to_industry)}")
    return code_to_industry


def decode_gbk(bs: bytes) -> str:
    return bs.split(b"\x00")[0].decode("gbk", errors="ignore").strip()


def parse_block_dat(path: Path | None) -> Dict[str, List[str]]:
    if path is None or not path.exists():
        return {}

    data = path.read_bytes()
    if len(data) < 386:
        print(f"[WARN] block file too small: {path}")
        return {}

    try:
        count = struct.unpack("<H", data[384:386])[0]
    except Exception:
        print(f"[WARN] cannot read block count: {path}")
        return {}

    print(f"[USE] {path.name}: {path}, block_count={count}, size={len(data)}")

    def try_parse(record_len: int) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        valid_blocks = 0

        for i in range(count):
            off = 386 + i * record_len
            if off + 13 > len(data):
                break

            name = decode_gbk(data[off:off + 9])
            if not name:
                continue

            try:
                stock_count = struct.unpack("<H", data[off + 9:off + 11])[0]
            except Exception:
                continue

            if stock_count <= 0 or stock_count > 500:
                continue

            codes = []
            start = off + 13
            for j in range(min(stock_count, 400)):
                cbs = data[start + j * 7:start + (j + 1) * 7]
                cstr = decode_gbk(cbs)
                code = norm_code(cstr)
                if re.fullmatch(r"\d{6}", code):
                    codes.append(code)

            if codes:
                valid_blocks += 1
                for code in codes:
                    out.setdefault(code, [])
                    if name not in out[code]:
                        out[code].append(name)

        print(f"  record_len={record_len}, valid_blocks={valid_blocks}, mapped_codes={len(out)}")
        return out

    candidates = [2813, 2812, 2816, 2800]
    parsed = [try_parse(x) for x in candidates]
    return max(parsed, key=lambda m: len(m))


def merge_concept_maps(*maps: Dict[str, List[str]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for m in maps:
        for code, arr in m.items():
            out.setdefault(code, [])
            for name in arr:
                if name and name not in out[code]:
                    out[code].append(name)
    for code in list(out):
        out[code] = out[code][:50]
    return out


def main():
    if len(sys.argv) >= 2:
        tdx_root = Path(sys.argv[1])
    else:
        raise SystemExit('请指定通达信根目录，例如：python concept_builder_tdx_local.py "D:\\new_tdx"')

    if not tdx_root.exists():
        raise SystemExit(f"目录不存在：{tdx_root}")

    print("[START] build mapping from local TongDaXin files")
    print(f"[TDX_ROOT] {tdx_root}")

    found = find_files(tdx_root, [
        "tdxhy.cfg", "incon.dat",
        "block_gn.dat", "block_fg.dat", "block.dat",
        "block_zs.dat"
    ])

    for name, paths in found.items():
        print(f"[FOUND] {name}: {len(paths)}")
        for p in paths[:5]:
            print(f"  - {p}")

    tdxhy = choose_file(found.get("tdxhy.cfg", []), ["hq_cache", "T0002"])
    incon = choose_file(found.get("incon.dat", []), ["hq_cache", "T0002"])

    incon_map = parse_incon(incon)
    code_to_industry = parse_tdxhy(tdxhy, incon_map)

    concept_maps = []
    for fname in ["block_gn.dat", "block_fg.dat", "block.dat", "block_zs.dat"]:
        p = choose_file(found.get(fname, []), ["hq_cache", "T0002"])
        m = parse_block_dat(p)
        if m:
            concept_maps.append(m)

    code_to_concepts = merge_concept_maps(*concept_maps)

    industry_pct = {}
    concept_pct = {}

    report = {
        "tdx_root": str(tdx_root),
        "tdxhy": str(tdxhy) if tdxhy else "",
        "incon": str(incon) if incon else "",
        "found": {k: [str(x) for x in v[:20]] for k, v in found.items()},
        "industry_mapped_codes": len(code_to_industry),
        "concept_mapped_codes": len(code_to_concepts),
        "source": "local_tdx_recursive_files",
    }

    save_json(code_to_industry, "code_to_industry.json")
    save_json(code_to_concepts, "code_to_concepts.json")
    save_json(industry_pct, "industry_pct.json")
    save_json(concept_pct, "concept_pct.json")
    save_json(report, "tdx_local_build_report.json")

    print("[DONE]")
    print(f"industry mapped codes: {len(code_to_industry)}")
    print(f"concept mapped codes: {len(code_to_concepts)}")
    if len(code_to_concepts) == 0:
        print("[NOTE] 没找到 block_gn.dat/block_fg.dat/block.dat 或解析失败，所以概念仍为空。")
        print("[NOTE] 但行业映射已可用；Streamlit 可先显示行业联动。")
    print("Now restart streamlit_realtime.py")


if __name__ == "__main__":
    main()
