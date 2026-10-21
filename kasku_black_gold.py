#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kasku – Keuangan & Jadwal  (edisi Black & Gold)
================================================
Aplikasi desktop (Python + tkinter, tanpa library tambahan) untuk:
  * mencatat keuangan harian / bulanan / tahunan + grafik arus kas
  * membagi penghasilan dengan persen (jatah harian, mingguan, bulanan)
  * membuat jadwal harian / mingguan / bulanan (bisa berulang)

Jalankan:   python kasku_black_gold.py
Uji logika: python kasku_black_gold.py --selftest

Data disimpan di  ~/.kasku_data.json  (kompatibel dengan versi lama).
"""
from __future__ import annotations

import calendar
import csv
import json
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

# =============================================================================
#  KONSTANTA & PALET WARNA  (hitam – emas – putih)
# =============================================================================
APP_NAME = "Kasku"
DATA_FILE = Path.home() / ".kasku_data.json"

BLACK = "#0B0B0D"
INK = "#17171B"
EDGE_DK = "#2A2A31"
GOLD = "#C9A24B"
GOLD_D = "#A8812F"
GOLD_L = "#E6CF8B"
CHAMP = "#F7F1DF"
WHITE = "#FFFFFF"
IVORY = "#F6F4EE"
LINE = "#E9E3D3"
TEXT = "#1A1A1D"
MUTED = "#8C877A"
SOFT_DK = "#A9A598"
DANGER = "#B5472F"
DONUT_COLORS = [GOLD, WHITE, GOLD_D, GOLD_L, "#7D7767", "#D9D2C0", "#5A5648", "#F0E6C4"]

SIDEBAR_W = 232
FONT = "Segoe UI"

REPEATS = {"none": "Sekali", "day": "Tiap hari", "week": "Tiap minggu", "month": "Tiap bulan"}
INCOME_PER = {"day": "Hari", "week": "Minggu", "month": "Bulan"}
SAVING_HINT = re.compile(r"tabung|invest|saving", re.I)
NO_BUCKET = "(Tanpa pos)"

DAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
DAYS_SHORT = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
          "September", "Oktober", "November", "Desember"]
MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


# =============================================================================
#  FUNGSI MURNI  (tanpa GUI – mudah diuji)
# =============================================================================
def to_float(value, default=0.0):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def rupiah(value) -> str:
    v = to_float(value)
    sign = "-" if round(v) < 0 else ""
    return f"{sign}Rp {abs(round(v)):,}".replace(",", ".")


_SUFFIX = {"k": 1e3, "rb": 1e3, "ribu": 1e3, "jt": 1e6, "juta": 1e6}


def parse_money(text) -> float:
    """Baca angka rupiah yang diketik orang Indonesia.
    '50.000' -> 50000 | '1.500.000' -> 1500000 | '1,5jt' -> 1500000 | 'Rp 75rb' -> 75000
    Melempar ValueError bila tidak valid (termasuk nan/inf/negatif)."""
    s = str(text).strip().lower().replace("rp", "").replace(" ", "")
    s = re.sub(r"[,.]-$", "", s)
    m = re.fullmatch(r"([\d.,]+)(k|rb|ribu|jt|juta)?", s)
    if not m:
        raise ValueError("format angka tidak dikenal")
    num, suffix = m.groups()
    dots, commas = num.count("."), num.count(",")
    if dots and commas:
        dec = "." if num.rfind(".") > num.rfind(",") else ","
        thou = "," if dec == "." else "."
        num = num.replace(thou, "").replace(dec, ".")
    elif dots or commas:
        sep = "." if dots else ","
        parts = num.split(sep)
        grouped = len(parts[0]) in (1, 2, 3) and parts[0] != "0" and all(len(p) == 3 for p in parts[1:])
        if grouped:
            num = "".join(parts)
        elif len(parts) == 2 and parts[0] != "" and parts[1] != "":
            num = parts[0] + "." + parts[1]
        else:
            raise ValueError("format angka tidak dikenal")
    value = float(num) * (_SUFFIX[suffix] if suffix else 1)
    if not math.isfinite(value) or value < 0 or value > 1e13:
        raise ValueError("angka di luar batas")
    return value


def parse_percent(text) -> float:
    s = str(text).strip().replace("%", "").replace(",", ".")
    v = float(s)
    if not math.isfinite(v) or v < 0 or v > 100:
        raise ValueError("persen harus 0-100")
    return round(v, 2)


def fmt_num(x) -> str:
    x = to_float(x)
    return str(int(round(x))) if abs(x - round(x)) < 1e-9 else f"{x:.2f}".rstrip("0").rstrip(".")


def _trim(x):
    return f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def short_rp(v) -> str:
    if v >= 1e9:
        return _trim(v / 1e9) + "M"
    if v >= 1e6:
        return _trim(v / 1e6) + "jt"
    if v >= 1e3:
        return _trim(v / 1e3) + "rb"
    return str(int(v))


def nice_ceil(v) -> float:
    if v <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * exp >= v - 1e-9:
            return m * exp
    return 10 * exp


def shorten(s, n):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def parse_iso(s):
    try:
        return date.fromisoformat(str(s))
    except ValueError:
        return None


def norm_time(s):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(s))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def days_in_month(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def shift_ref(period: str, d: date, n: int) -> date:
    try:
        if period in ("Harian",):
            return d + timedelta(days=n)
        if period == "Mingguan":
            return d + timedelta(days=7 * n)
        if period == "Bulanan":
            return add_months(d, n)
        return add_months(d, 12 * n)
    except (ValueError, OverflowError):
        return d


def fmt_date(d: date, style="long") -> str:
    if style == "long":
        return f"{DAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year}"
    if style == "short":
        return f"{DAYS_SHORT[d.weekday()]}, {d.day} {MONTHS_SHORT[d.month - 1]} {d.year}"
    return f"{d.day} {MONTHS_SHORT[d.month - 1]} {d.year}"


def period_label(period: str, ref: date) -> str:
    if period == "Harian":
        return fmt_date(ref, "long")
    if period == "Mingguan":
        a = monday_of(ref)
        b = a + timedelta(days=6)
        return f"{a.day} {MONTHS_SHORT[a.month - 1]} – {b.day} {MONTHS_SHORT[b.month - 1]} {b.year}"
    if period == "Bulanan":
        return f"{MONTHS[ref.month - 1]} {ref.year}"
    return str(ref.year)


def occurs(item: dict, day: date) -> bool:
    """Apakah jadwal `item` muncul pada tanggal `day`? (tanggal 31 -> hari terakhir bulan pendek)"""
    start = parse_iso(item["d"])
    if start is None or day < start:
        return False
    r = item["r"]
    if r == "none":
        return day == start
    if r == "day":
        return True
    if r == "week":
        return day.weekday() == start.weekday()
    return day.day == min(start.day, days_in_month(day))


def split_income(inc: float, per: str, ref: date):
    """-> (harian, mingguan, bulanan). Bila diterima per bulan, total bulanan = persis penghasilan."""
    dim = days_in_month(ref)
    daily = inc if per == "day" else inc / 7 if per == "week" else inc / dim
    monthly = inc if per == "month" else daily * dim
    return daily, daily * 7, monthly


def pct_change_text(now, before, label):
    if now == 0 and before == 0:
        return "Belum ada data"
    if before == 0:
        return f"Baru ada di periode ini"
    p = (now - before) / before * 100
    if abs(p) < 0.5:
        return f"Sama seperti {label}"
    return f"{'Naik' if p > 0 else 'Turun'} {abs(p):.0f}% dari {label}"


# =============================================================================
#  DATA  (muat, bersihkan, simpan dengan aman)
# =============================================================================
def default_buckets():
    return [{"n": "Kebutuhan", "p": 50.0, "sv": False},
            {"n": "Keinginan", "p": 30.0, "sv": False},
            {"n": "Tabungan", "p": 20.0, "sv": True}]


def empty_data():
    return {"name": "Kamu", "inc": 0.0, "per": "month", "bk": default_buckets(), "tx": [], "sc": []}


def default_data():
    t = date.today().isoformat()
    d = empty_data()
    d["inc"] = 5000000.0
    d["tx"] = [{"id": 1, "t": "in", "a": 5000000.0, "b": "", "n": "Gaji", "d": t},
               {"id": 2, "t": "out", "a": 35000.0, "b": "Kebutuhan", "n": "Makan siang", "d": t}]
    d["sc"] = [{"id": 1, "ti": "Rapat mingguan", "d": t, "h": "09:00", "r": "week", "dn": {}},
               {"id": 2, "ti": "Catat keuangan hari ini", "d": t, "h": "20:00", "r": "day", "dn": {}}]
    return d


def _assign_ids(records):
    used = {r["id"] for r in records if r.get("id") is not None}
    nxt = max(used, default=0) + 1
    for r in records:
        if r.get("id") is None:
            r["id"] = nxt
            nxt += 1
    return records


def sanitize(raw):
    """Bersihkan data dari file (rusak/format lama). Tidak pernah melempar error.
    -> (data, catatan)"""
    notes = []
    if not isinstance(raw, dict):
        return empty_data(), ["Format file data tidak dikenali, memulai dengan data kosong."]
    out = empty_data()
    out["name"] = (str(raw.get("name") or "Kamu").strip()[:24]) or "Kamu"
    out["inc"] = max(0.0, to_float(raw.get("inc")))
    out["per"] = raw.get("per") if raw.get("per") in INCOME_PER else "month"

    if isinstance(raw.get("bk"), list):
        out["bk"], seen, skipped = [], set(), 0
        for b in raw["bk"]:
            if not isinstance(b, dict):
                skipped += 1
                continue
            n = str(b.get("n", "")).strip()
            if not n or n.lower() in seen:
                skipped += 1
                continue
            seen.add(n.lower())
            p = round(min(100.0, max(0.0, to_float(b.get("p")))), 2)
            sv = bool(b["sv"]) if "sv" in b else bool(SAVING_HINT.search(n))
            out["bk"].append({"n": n, "p": p, "sv": sv})
        if skipped:
            notes.append(f"{skipped} pos alokasi tidak valid dilewati.")

    txs, skipped, used = [], 0, set()
    for t in raw.get("tx", []) if isinstance(raw.get("tx"), list) else []:
        if not isinstance(t, dict):
            skipped += 1
            continue
        d, a, kind = parse_iso(t.get("d")), to_float(t.get("a")), t.get("t")
        if d is None or a <= 0 or kind not in ("in", "out"):
            skipped += 1
            continue
        tid = t.get("id")
        if not isinstance(tid, int) or isinstance(tid, bool) or tid in used:
            tid = None
        else:
            used.add(tid)
        txs.append({"id": tid, "t": kind, "a": a, "b": str(t.get("b") or "") if kind == "out" else "",
                    "n": str(t.get("n") or "").strip(), "d": d.isoformat()})
    out["tx"] = _assign_ids(txs)
    if skipped:
        notes.append(f"{skipped} transaksi tidak valid dilewati.")

    scs, skipped, used = [], 0, set()
    for s in raw.get("sc", []) if isinstance(raw.get("sc"), list) else []:
        if not isinstance(s, dict):
            skipped += 1
            continue
        d, title = parse_iso(s.get("d")), str(s.get("ti") or "").strip()
        if d is None or not title:
            skipped += 1
            continue
        sid = s.get("id")
        if not isinstance(sid, int) or isinstance(sid, bool) or sid in used:
            sid = None
        else:
            used.add(sid)
        dn = s.get("dn") if isinstance(s.get("dn"), dict) else {}
        scs.append({"id": sid, "ti": title, "d": d.isoformat(), "h": norm_time(s.get("h")) or "09:00",
                    "r": s.get("r") if s.get("r") in REPEATS else "none",
                    "dn": {k: True for k, v in dn.items() if v and parse_iso(k)}})
    out["sc"] = _assign_ids(scs)
    if skipped:
        notes.append(f"{skipped} jadwal tidak valid dilewati.")
    return out, notes


class Store:
    def __init__(self, path=None):
        self.path = Path(path or DATA_FILE)
        self.notes = []
        self.data = self._load()

    # ------------------------------------------------------------- berkas
    def _load(self):
        if not self.path.exists():
            return default_data()
        for candidate in (self.path, self.path.with_suffix(".bak")):
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            data, self.notes = sanitize(raw)
            return data
        try:
            shutil.copy2(self.path, self.path.with_suffix(".corrupt"))
        except OSError:
            pass
        self.notes = ["File data rusak dan tidak bisa dibaca. Salinannya disimpan sebagai .corrupt."]
        return empty_data()

    def save(self):
        """Simpan atomik (tulis file sementara lalu ganti). -> None bila sukses, atau pesan error."""
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            if self.path.exists():
                shutil.copy2(self.path, self.path.with_suffix(".bak"))
            os.replace(tmp, self.path)
        except OSError as exc:
            return str(exc)
        return None

    def reset(self):
        name = self.data["name"]
        self.data = empty_data()
        self.data["name"] = name

    def next_id(self, key):
        return max((r["id"] for r in self.data[key]), default=0) + 1

    # ---------------------------------------------------------- transaksi
    def add_tx(self, kind, amount, bucket, note, day):
        rec = {"id": self.next_id("tx"), "t": kind, "a": float(amount),
               "b": bucket if kind == "out" else "", "n": note.strip(), "d": day.isoformat()}
        self.data["tx"].append(rec)
        return rec

    def update_tx(self, rec, kind, amount, bucket, note, day):
        rec.update({"t": kind, "a": float(amount), "b": bucket if kind == "out" else "",
                    "n": note.strip(), "d": day.isoformat()})

    def delete_tx(self, tid):
        self.data["tx"] = [t for t in self.data["tx"] if t["id"] != tid]

    def total(self, kind, txs=None):
        txs = self.data["tx"] if txs is None else txs
        return sum(t["a"] for t in txs if t["t"] == kind)

    def in_period(self, period, ref):
        if period == "Harian":
            key = ref.isoformat()
        elif period == "Bulanan":
            key = f"{ref.year}-{ref.month:02d}-"
        else:
            key = f"{ref.year}-"
        out = [t for t in self.data["tx"] if t["d"].startswith(key)]
        return sorted(out, key=lambda t: (t["d"], t["id"]), reverse=True)

    def chart_series(self, period, ref):
        by_day = {}
        for t in self.data["tx"]:
            s = by_day.setdefault(t["d"], [0.0, 0.0])
            s[0 if t["t"] == "in" else 1] += t["a"]
        if period == "Tahunan":
            res = []
            for m in range(1, 13):
                pre = f"{ref.year}-{m:02d}-"
                vals = [v for k, v in by_day.items() if k.startswith(pre)]
                res.append((MONTHS_SHORT[m - 1], sum(v[0] for v in vals), sum(v[1] for v in vals)))
            return res
        if period == "Bulanan":
            days = [date(ref.year, ref.month, d) for d in range(1, days_in_month(ref) + 1)]
            return [(str(d.day), *by_day.get(d.isoformat(), [0.0, 0.0])) for d in days]
        days = [ref - timedelta(days=6 - i) for i in range(7)]
        return [(DAYS_SHORT[d.weekday()], *by_day.get(d.isoformat(), [0.0, 0.0])) for d in days]

    # ------------------------------------------------------------- jadwal
    def add_item(self, title, day, hour, repeat):
        rec = {"id": self.next_id("sc"), "ti": title.strip(), "d": day.isoformat(), "h": hour, "r": repeat, "dn": {}}
        self.data["sc"].append(rec)
        return rec

    def update_item(self, rec, title, day, hour, repeat):
        rec.update({"ti": title.strip(), "d": day.isoformat(), "h": hour, "r": repeat})

    def delete_item(self, sid):
        self.data["sc"] = [s for s in self.data["sc"] if s["id"] != sid]

    def items_on(self, day):
        return sorted((i for i in self.data["sc"] if occurs(i, day)), key=lambda i: (i["h"], i["ti"].lower()))

    @staticmethod
    def is_done(item, day):
        return bool(item["dn"].get(day.isoformat()))

    def toggle_done(self, item, day):
        key = day.isoformat()
        if item["dn"].get(key):
            item["dn"].pop(key, None)
        else:
            item["dn"][key] = True

    # ------------------------------------------------------------ alokasi
    def income_split(self, ref):
        return split_income(self.data["inc"], self.data["per"], ref)

    def spent_by_bucket(self, ref):
        key = f"{ref.year}-{ref.month:02d}-"
        out = {}
        for t in self.data["tx"]:
            if t["t"] == "out" and t["d"].startswith(key):
                out[t["b"]] = out.get(t["b"], 0.0) + t["a"]
        return out

    def alloc_rows(self, ref):
        daily, weekly, monthly = self.income_split(ref)
        spent = self.spent_by_bucket(ref)
        rows = []
        for b in self.data["bk"]:
            f = b["p"] / 100
            rows.append({"name": b["n"], "pct": b["p"], "saving": b["sv"], "daily": daily * f,
                         "weekly": weekly * f, "monthly": monthly * f, "spent": spent.get(b["n"], 0.0)})
        names = {b["n"] for b in self.data["bk"]}
        others = sum(v for k, v in spent.items() if k not in names)
        return rows, others

    def allowance(self, day):
        daily = self.income_split(day)[0]
        bks = self.data["bk"]
        saving = {b["n"] for b in bks if b["sv"]}
        allow = sum(daily * b["p"] / 100 for b in bks if not b["sv"])
        key = day.isoformat()
        spent = sum(t["a"] for t in self.data["tx"] if t["t"] == "out" and t["d"] == key and t["b"] not in saving)
        return {"allow": allow, "spent": spent, "left": allow - spent}

    def set_allocation(self, inc, per, rows):
        """rows: [{'orig': nama lama atau None, 'n':..., 'p':..., 'sv':...}]"""
        mapping = {r["orig"]: r["n"] for r in rows if r["orig"] and r["orig"] != r["n"]}
        if mapping:
            for t in self.data["tx"]:
                if t["b"] in mapping:
                    t["b"] = mapping[t["b"]]
        self.data["inc"], self.data["per"] = float(inc), per
        self.data["bk"] = [{"n": r["n"], "p": r["p"], "sv": bool(r["sv"])} for r in rows]

    def reminders(self, day):
        out = []
        for i in self.items_on(day):
            if not self.is_done(i, day):
                out.append(("Jadwal", f"{i['h']} · {i['ti']}"))
        rows, _ = self.alloc_rows(day)
        for r in rows:
            if r["monthly"] > 0 and not r["saving"]:
                ratio = r["spent"] / r["monthly"]
                if ratio >= 1:
                    out.append(("Anggaran", f"Pos {r['name']} sudah melewati batas bulan ini"))
                elif ratio >= 0.9:
                    out.append(("Anggaran", f"Pos {r['name']} sudah terpakai {ratio * 100:.0f}%"))
        a = self.allowance(day)
        if a["allow"] > 0 and a["left"] < 0:
            out.append(("Jatah harian", f"Pengeluaran hari ini melewati jatah sebesar {rupiah(-a['left'])}"))
        return out

    def export_csv(self, path):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Tanggal", "Jenis", "Jumlah", "Pos", "Catatan"])
            for t in sorted(self.data["tx"], key=lambda t: (t["d"], t["id"])):
                w.writerow([t["d"], "Pemasukan" if t["t"] == "in" else "Pengeluaran", int(round(t["a"])), t["b"], t["n"]])


def draft_snapshot(d):
    def num(fn, x):
        try:
            return round(fn(x), 2)
        except ValueError:
            return None
    return (num(parse_money, d["inc"]), d["per"],
            tuple((b["n"].strip(), num(parse_percent, b["p"]), bool(b["sv"])) for b in d["bk"]))


def store_snapshot(data):
    return (round(data["inc"], 2), data["per"], tuple((b["n"], round(b["p"], 2), b["sv"]) for b in data["bk"]))


# =============================================================================
#  TOOLKIT UI  (kartu bulat, tombol pil, grafik – semua digambar di Canvas)
# =============================================================================
def F(size=10, bold=False):
    return (FONT, size, "bold" if bold else "normal")


def pick_font(root):
    global FONT
    try:
        fams = set(tkfont.families(root))
    except tk.TclError:
        return
    for name in ("Segoe UI", "SF Pro Display", "Inter", "Helvetica Neue", "Ubuntu", "Noto Sans", "DejaVu Sans", "Arial"):
        if name in fams:
            FONT = name
            return
    FONT = "Helvetica"


def rr(x1, y1, x2, y2, r):
    """Titik poligon persegi bulat (pakai smooth=True)."""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    return [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y1 + r, x2, y2 - r,
            x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2, x1 + r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
            x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1]


def lbl(parent, text="", size=10, bold=False, fg=TEXT, **kw):
    kw.setdefault("bg", parent["bg"])
    return tk.Label(parent, text=text, font=F(size, bold), fg=fg, **kw)


def sep(parent, color=LINE):
    f = tk.Frame(parent, bg=color, height=1)
    f.pack(fill="x")
    return f


def entry(parent, var, width=24, **kw):
    return tk.Entry(parent, textvariable=var, width=width, relief="flat", bd=0, bg=WHITE, fg=TEXT,
                    insertbackground=TEXT, font=F(10), highlightthickness=1,
                    highlightbackground=LINE, highlightcolor=GOLD, **kw)


def combo(parent, var, values, width=18, state="readonly"):
    return ttk.Combobox(parent, textvariable=var, values=values, width=width, state=state,
                        style="K.TCombobox", font=F(10))


def draw_icon(c, name, cx, cy, color):
    if name == "dash":
        for dx in (-8, 1):
            for dy in (-8, 1):
                c.create_polygon(rr(cx + dx, cy + dy, cx + dx + 7, cy + dy + 7, 2), smooth=True, fill=color, outline=color)
    elif name == "fin":
        c.create_polygon(rr(cx - 9, cy - 6, cx + 9, cy + 8, 3), smooth=True, fill="", outline=color, width=2)
        c.create_line(cx - 9, cy - 2, cx + 9, cy - 2, fill=color, width=2)
        c.create_oval(cx + 3, cy + 2, cx + 6, cy + 5, fill=color, outline=color)
    elif name == "pie":
        c.create_oval(cx - 9, cy - 9, cx + 9, cy + 9, outline=color, width=2)
        c.create_arc(cx - 9, cy - 9, cx + 9, cy + 9, start=0, extent=90, fill=color, outline=color)
    elif name == "cal":
        c.create_polygon(rr(cx - 9, cy - 7, cx + 9, cy + 9, 3), smooth=True, fill="", outline=color, width=2)
        c.create_line(cx - 9, cy - 2, cx + 9, cy - 2, fill=color, width=2)
        c.create_line(cx - 4, cy - 10, cx - 4, cy - 5, fill=color, width=2)
        c.create_line(cx + 4, cy - 10, cx + 4, cy - 5, fill=color, width=2)
    elif name == "gear":
        c.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, outline=color, width=2)
        for k in range(8):
            a = math.radians(k * 45)
            c.create_line(cx + 7 * math.cos(a), cy + 7 * math.sin(a), cx + 10 * math.cos(a), cy + 10 * math.sin(a),
                          fill=color, width=2)
    elif name == "bell":
        c.create_polygon(cx - 7, cy + 5, cx - 5, cy + 2, cx - 5, cy - 3, cx - 3, cy - 7, cx + 3, cy - 7,
                         cx + 5, cy - 3, cx + 5, cy + 2, cx + 7, cy + 5, smooth=True, fill=color, outline=color)
        c.create_oval(cx - 2, cy + 6, cx + 2, cy + 9, fill=color, outline=color)


class Card(tk.Frame):
    """Kartu dengan sudut membulat. Isi widget ke `card.body`."""

    def __init__(self, parent, bg=WHITE, radius=18, pad=16, border=LINE):
        super().__init__(parent, bg=parent["bg"])
        self._fillc, self._rad, self._edge = bg, radius, border
        self._cv = tk.Canvas(self, bg=parent["bg"], highlightthickness=0, bd=0)
        self._cv.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)
        self.bind("<Configure>", self._draw)

    def _draw(self, e):
        if e.width < 6 or e.height < 6:
            return
        self._cv.delete("all")
        self._cv.create_polygon(rr(1, 1, e.width - 1, e.height - 1, self._rad), smooth=True,
                                fill=self._fillc, outline=self._edge)


class Pill(tk.Canvas):
    STYLES = {
        "gold": dict(bg=GOLD, hover=GOLD_D, fg=BLACK, hfg=BLACK, edge=None),
        "black": dict(bg=BLACK, hover="#26262B", fg=GOLD_L, hfg=GOLD_L, edge=None),
        "white": dict(bg=WHITE, hover=CHAMP, fg=TEXT, hfg=TEXT, edge=LINE),
        "ghost": dict(bg=None, hover=CHAMP, fg=MUTED, hfg=TEXT, edge=None),
        "danger": dict(bg=None, hover="#F7E7E2", fg=MUTED, hfg=DANGER, edge=None),
        "darkghost": dict(bg=None, hover="#2A2A30", fg=GOLD_L, hfg=GOLD_L, edge=None),
    }

    def __init__(self, parent, text, command=None, style="gold", size=10, bold=True, padx=18, pady=8, min_w=0):
        self._font = tkfont.Font(family=FONT, size=size, weight="bold" if bold else "normal")
        w = max(min_w, self._font.measure(text) + 2 * padx)
        h = self._font.metrics("linespace") + 2 * pady
        super().__init__(parent, width=w, height=h, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2")
        self._text, self._cmd, self._sty = text, command, style
        self._wd, self._ht, self._hover = w, h, False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", self._resize)
        self.draw()

    def _set_hover(self, v):
        self._hover = v
        self.draw()

    def _resize(self, e):
        self._wd, self._ht = e.width, e.height
        self.draw()

    def _release(self, e):
        if self._cmd and 0 <= e.x <= self._wd and 0 <= e.y <= self._ht:
            self._cmd()

    def set_style(self, style):
        self._sty = style
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = self._wd, self._ht
        if w < 4 or h < 4:
            return
        st = self.STYLES[self._sty]
        fill = st["hover"] if self._hover else st["bg"]
        if fill:
            self.create_polygon(rr(1, 1, w - 1, h - 1, h / 2), smooth=True, fill=fill, outline=st["edge"] or fill)
        self.create_text(w / 2, h / 2, text=self._text, font=self._font, fill=st["hfg"] if self._hover else st["fg"])


class NavItem(tk.Canvas):
    def __init__(self, parent, label, icon, command, width=196, height=44):
        super().__init__(parent, width=width, height=height, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2")
        self._label, self._icon, self._cmd = label, icon, command
        self._wd, self._ht, self._on, self._hover = width, height, False, False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", lambda e: self._cmd())
        self.draw()

    def _set_hover(self, v):
        self._hover = v
        self.draw()

    def set_active(self, v):
        self._on = v
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = self._wd, self._ht
        if self._on:
            self.create_polygon(rr(0, 0, w, h, 14), smooth=True, fill=GOLD, outline=GOLD)
        elif self._hover:
            self.create_polygon(rr(0, 0, w, h, 14), smooth=True, fill="#1C1C21", outline="#1C1C21")
        fg = BLACK if self._on else (WHITE if self._hover else "#B9B4A5")
        draw_icon(self, self._icon, 28, h / 2, fg)
        self.create_text(52, h / 2, text=self._label, anchor="w", font=F(11, self._on), fill=fg)


class CheckDot(tk.Canvas):
    def __init__(self, parent, checked=False, command=None, size=24):
        super().__init__(parent, width=size, height=size, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2")
        self._on, self._sz, self._cmd = checked, size, command
        self.bind("<Button-1>", self._click)
        self.draw()

    def _click(self, e):
        if self._cmd:
            self._cmd()

    def set(self, value):
        self._on = bool(value)
        self.draw()

    def draw(self):
        self.delete("all")
        s = self._sz
        if self._on:
            self.create_oval(2, 2, s - 2, s - 2, fill=GOLD, outline=GOLD)
            self.create_line(s * .30, s * .52, s * .44, s * .66, s * .72, s * .36, fill=BLACK, width=2,
                             capstyle="round", joinstyle="round")
        else:
            self.create_oval(2, 2, s - 2, s - 2, fill="", outline="#CFC8B4", width=2)


class Bar(tk.Canvas):
    def __init__(self, parent, ratio=0.0, height=8, fill=GOLD, track=LINE):
        super().__init__(parent, height=height, bg=parent["bg"], highlightthickness=0, bd=0)
        self._ratio, self._ht, self._fillc, self._track = ratio, height, fill, track
        self.bind("<Configure>", lambda e: self.draw())

    def update_ratio(self, ratio):
        self._ratio = ratio
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self._ht
        if w < 4:
            return
        self.create_polygon(rr(0, 0, w, h, h / 2), smooth=True, fill=self._track, outline=self._track)
        if self._ratio > 0:
            fw = max(h, min(1.0, self._ratio) * w)
            col = DANGER if self._ratio > 1.0 else self._fillc
            self.create_polygon(rr(0, 0, fw, h, h / 2), smooth=True, fill=col, outline=col)


class BarChart(tk.Canvas):
    """Grafik batang pemasukan (emas) vs pengeluaran (hitam)."""

    def __init__(self, parent, data, height=220):
        super().__init__(parent, height=height, bg=parent["bg"], highlightthickness=0, bd=0)
        self._data = data
        self.bind("<Configure>", lambda e: self.draw())

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 80 or h < 60:
            return
        left, right, top_pad, bottom = 54, 6, 10, 26
        pw, ph = w - left - right, h - top_pad - bottom
        peak = max((max(i, e) for _, i, e in self._data), default=0)
        if peak <= 0:
            self.create_text(w / 2, h / 2, text="Belum ada data untuk periode ini", font=F(10), fill=MUTED)
            return
        top = nice_ceil(peak)
        for k in range(5):
            y = top_pad + ph - ph * k / 4
            self.create_line(left, y, w - right, y, fill=LINE if k else "#D8D0BC")
            self.create_text(left - 8, y, text=short_rp(top * k / 4), anchor="e", font=F(8), fill=MUTED)
        n = len(self._data)
        slot = pw / n
        bw = max(3, min(16, slot * 0.32))
        every = max(1, math.ceil(n / 12))
        for idx, (label, inc, exp) in enumerate(self._data):
            cx = left + slot * (idx + 0.5)
            for off, val, color in ((-bw / 2 - 1, inc, GOLD), (bw / 2 + 1, exp, BLACK)):
                if val <= 0:
                    continue
                bh = max(3, ph * val / top)
                x1, x2 = cx + off - bw / 2, cx + off + bw / 2
                self.create_polygon(rr(x1, top_pad + ph - bh, x2, top_pad + ph, min(4, bw / 2)), smooth=True,
                                    fill=color, outline=color)
            if idx % every == 0:
                self.create_text(cx, h - bottom + 13, text=label, font=F(8), fill=MUTED)


class Donut(tk.Canvas):
    def __init__(self, parent, size=170, thick=22, bg=None):
        super().__init__(parent, width=size, height=size, bg=bg or parent["bg"], highlightthickness=0, bd=0)
        self._sz, self._th, self._parts, self._center = size, thick, [], "0%"
        self.draw()

    def update_parts(self, parts, center):
        self._parts, self._center = parts, center
        self.draw()

    def draw(self):
        self.delete("all")
        s, t = self._sz, self._th
        box = (t / 2 + 4, t / 2 + 4, s - t / 2 - 4, s - t / 2 - 4)
        self.create_oval(*box, outline="#26262C", width=t)
        total = sum(v for v, _ in self._parts)
        scale = 360 / max(total, 100)
        acc = 0.0
        for value, color in self._parts:
            ext = value * scale
            if ext <= 0.2:
                continue
            draw_ext = min(359.9, max(0.5, ext - (1.5 if ext > 4 else 0)))
            self.create_arc(*box, start=90 - acc, extent=-draw_ext, style="arc", outline=color, width=t)
            acc += ext
        self.create_text(s / 2, s / 2 - 8, text=self._center, font=F(20, True), fill=GOLD)
        self.create_text(s / 2, s / 2 + 16, text="dialokasikan", font=F(9), fill=SOFT_DK)


class ScrollFrame(tk.Frame):
    def __init__(self, parent, bg=IVORY):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=24)
        self.vsb = ttk.Scrollbar(self, orient="vertical", style="Slim.Vertical.TScrollbar", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))

    def scroll(self, step):
        bb = self.canvas.bbox("all")
        if bb and bb[3] - bb[1] > self.canvas.winfo_height():
            self.canvas.yview_scroll(step * 2, "units")


# =============================================================================
#  DIALOG
# =============================================================================
class Dialog(tk.Toplevel):
    def __init__(self, app, title, width=470):
        super().__init__(app)
        self.app = app
        self.title(title)
        self.configure(bg=WHITE)
        self.resizable(False, False)
        self.transient(app)
        self.body = tk.Frame(self, bg=WHITE)
        self.body.pack(fill="both", expand=True, padx=30, pady=26)
        tk.Frame(self.body, bg=WHITE, width=width, height=1).pack()
        self.bind("<Escape>", lambda e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.err = None

    def heading(self, title, subtitle):
        lbl(self.body, title, 17, True).pack(anchor="w")
        lbl(self.body, subtitle, 10, False, MUTED).pack(anchor="w", pady=(0, 16))

    def field(self, text):
        wrap = tk.Frame(self.body, bg=WHITE)
        lbl(wrap, text, 9, True, MUTED).pack(anchor="w", pady=(0, 4))
        return wrap

    def footer(self, ok_text, ok_cmd):
        self.err = lbl(self.body, "", 9, False, DANGER, wraplength=400, justify="left")
        self.err.pack(anchor="w", pady=(10, 0))
        row = tk.Frame(self.body, bg=WHITE)
        row.pack(fill="x", pady=(10, 0))
        Pill(row, ok_text, ok_cmd, "gold", padx=22).pack(side="right")
        Pill(row, "Batal", self.close, "white", padx=20).pack(side="right", padx=8)

    def show_error(self, msg):
        if self.err is not None:
            self.err.configure(text=msg)

    def present(self):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = self.app.winfo_rootx() + max(0, (self.app.winfo_width() - w) // 2)
        y = self.app.winfo_rooty() + max(0, (self.app.winfo_height() - h) // 3)
        self.geometry(f"+{x}+{y}")
        self.after(40, self._grab)
        self.lift()
        self.focus_set()

    def _grab(self):
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def close(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


class CalendarPopup(tk.Toplevel):
    def __init__(self, anchor, current, on_pick):
        owner = anchor.winfo_toplevel()
        super().__init__(owner)
        self._owner, self._on_pick, self._cur = owner, on_pick, current
        self._view = current.replace(day=1)
        self.title("Pilih tanggal")
        self.configure(bg=WHITE)
        self.resizable(False, False)
        self.transient(owner)
        head = tk.Frame(self, bg=WHITE)
        head.pack(fill="x", padx=14, pady=(14, 6))
        Pill(head, "«", lambda: self._go(-12), "ghost", padx=10, pady=4).pack(side="left")
        Pill(head, "‹", lambda: self._go(-1), "ghost", padx=12, pady=4).pack(side="left")
        Pill(head, "»", lambda: self._go(12), "ghost", padx=10, pady=4).pack(side="right")
        Pill(head, "›", lambda: self._go(1), "ghost", padx=12, pady=4).pack(side="right")
        self._title = lbl(head, "", 11, True)
        self._title.pack(expand=True)
        self._grid = tk.Frame(self, bg=WHITE)
        self._grid.pack(padx=14, pady=(0, 14))
        self._build()
        self.geometry(f"+{anchor.winfo_rootx()}+{anchor.winfo_rooty() + anchor.winfo_height() + 4}")
        self.bind("<Escape>", lambda e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(40, self._grab)

    def _grab(self):
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _go(self, n):
        try:
            self._view = add_months(self._view, n)
        except ValueError:
            return
        self._build()

    def _build(self):
        for w in self._grid.winfo_children():
            w.destroy()
        self._title.configure(text=f"{MONTHS[self._view.month - 1]} {self._view.year}")
        for c, name in enumerate(DAYS_SHORT):
            lbl(self._grid, name, 9, True, MUTED, width=4).grid(row=0, column=c, pady=(0, 4))
        today = date.today()
        weeks = calendar.Calendar(0).monthdatescalendar(self._view.year, self._view.month)
        for r, week in enumerate(weeks, start=1):
            for c, d in enumerate(week):
                inside = d.month == self._view.month
                if d == self._cur:
                    bg, fg, bold = BLACK, GOLD_L, True
                elif d == today:
                    bg, fg, bold = CHAMP, GOLD_D, True
                else:
                    bg, fg, bold = WHITE, (TEXT if inside else "#C4BEAD"), False
                cell = tk.Label(self._grid, text=str(d.day), width=4, font=F(10, bold), bg=bg, fg=fg, cursor="hand2", pady=4)
                cell.grid(row=r, column=c, padx=1, pady=1)
                cell.bind("<Button-1>", lambda e, d=d: self._pick(d))

    def _pick(self, d):
        cb = self._on_pick
        self._close()
        cb(d)

    def _close(self):
        owner = self._owner
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        if isinstance(owner, Dialog):
            try:
                owner.grab_set()
            except tk.TclError:
                pass


class DateField(tk.Frame):
    def __init__(self, parent, value):
        super().__init__(parent, bg=parent["bg"])
        self._val = value
        self._var = tk.StringVar(value=self._text())
        self._lab = tk.Label(self, textvariable=self._var, font=F(10), bg=WHITE, fg=TEXT, anchor="w", padx=10, pady=7,
                             highlightthickness=1, highlightbackground=LINE, cursor="hand2")
        self._lab.pack(fill="x")
        self._lab.bind("<Button-1>", lambda e: CalendarPopup(self._lab, self._val, self.set))

    def _text(self):
        return fmt_date(self._val, "short") + "   ▾"

    def get(self):
        return self._val

    def set(self, value):
        self._val = value
        self._var.set(self._text())


class TimeField(tk.Frame):
    def __init__(self, parent, value="09:00"):
        super().__init__(parent, bg=parent["bg"])
        h, m = (norm_time(value) or "09:00").split(":")
        self._hv, self._mv = tk.StringVar(value=h), tk.StringVar(value=m)
        combo(self, self._hv, [f"{i:02d}" for i in range(24)], 4, "normal").pack(side="left")
        lbl(self, ":", 11, True).pack(side="left", padx=4)
        combo(self, self._mv, [f"{i:02d}" for i in range(0, 60, 5)], 4, "normal").pack(side="left")

    def get(self):
        try:
            h, m = int(self._hv.get()), int(self._mv.get())
        except ValueError:
            raise ValueError("Jam dan menit harus berupa angka.")
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError("Jam harus 00–23 dan menit 00–59.")
        return f"{h:02d}:{m:02d}"


class TxDialog(Dialog):
    def __init__(self, app, tx=None):
        super().__init__(app, "Ubah transaksi" if tx else "Transaksi baru")
        self.tx = tx
        st = app.store
        self.heading("Ubah transaksi" if tx else "Transaksi baru", "Catat pemasukan atau pengeluaranmu")
        self.kind = tk.StringVar(value=tx["t"] if tx else "out")

        seg = Card(self.body, bg=IVORY, radius=20, pad=3)
        seg.pack(fill="x", pady=(0, 14))
        self._kbtn = {}
        for key, text in (("in", "Pemasukan"), ("out", "Pengeluaran")):
            p = Pill(seg.body, text, lambda k=key: self._set_kind(k), "ghost", min_w=190)
            p.pack(side="left", expand=True, fill="x", padx=2)
            self._kbtn[key] = p

        f = self.field("Jumlah (Rp)")
        f.pack(fill="x", pady=(0, 12))
        self.amt = tk.StringVar(value=fmt_num(tx["a"]) if tx else "")
        self._amt_entry = entry(f, self.amt)
        self._amt_entry.pack(fill="x", ipady=7)
        self._prev = lbl(f, "", 9)
        self._prev.pack(anchor="w", pady=(4, 0))
        self.amt.trace_add("write", lambda *a: self._preview())
        self._preview()

        names = [b["n"] for b in st.data["bk"]]
        options = [NO_BUCKET] + names
        cur = (tx["b"] if tx and tx["b"] else (names[0] if names else NO_BUCKET))
        if cur not in options:
            options.append(cur)
        f = self.field("Pos alokasi (untuk pengeluaran)")
        f.pack(fill="x", pady=(0, 12))
        self.bucket = tk.StringVar(value=cur)
        self._bucket_box = combo(f, self.bucket, options, 30)
        self._bucket_box.pack(fill="x", ipady=3)

        row = tk.Frame(self.body, bg=WHITE)
        row.pack(fill="x", pady=(0, 12))
        f1 = self.field("Tanggal")
        f1.pack(in_=row, side="left", fill="x", expand=True, padx=(0, 10))
        self.date = DateField(f1, parse_iso(tx["d"]) if tx else date.today())
        self.date.pack(fill="x")
        f2 = self.field("Catatan (opsional)")
        f2.pack(in_=row, side="left", fill="x", expand=True)
        self.note = tk.StringVar(value=tx["n"] if tx else "")
        entry(f2, self.note, 16).pack(fill="x", ipady=7)

        self.footer("Simpan perubahan" if tx else "Simpan transaksi", self.submit)
        self._set_kind(self.kind.get())
        self.bind("<Return>", lambda e: self.submit())
        self.present()
        self._amt_entry.focus_set()

    def _set_kind(self, k):
        self.kind.set(k)
        for key, p in self._kbtn.items():
            p.set_style("black" if key == k else "ghost")
        self._bucket_box.configure(state="readonly" if k == "out" else "disabled")

    def _preview(self):
        raw = self.amt.get().strip()
        try:
            self._prev.configure(text=rupiah(parse_money(raw)), fg=GOLD_D)
        except ValueError:
            if raw:
                self._prev.configure(text="Angka belum valid. Contoh: 50000, 50.000, 1,5jt", fg=DANGER)
            else:
                self._prev.configure(text="Contoh: 50000 · 50.000 · 75rb · 1,5jt", fg=MUTED)

    def submit(self):
        try:
            amount = parse_money(self.amt.get())
        except ValueError:
            return self.show_error("Jumlah belum valid. Contoh: 50000, 50.000, 75rb, atau 1,5jt.")
        if amount <= 0:
            return self.show_error("Jumlah harus lebih dari 0.")
        kind = self.kind.get()
        bucket = "" if self.bucket.get() == NO_BUCKET else self.bucket.get()
        day, note = self.date.get(), self.note.get()
        if self.tx:
            self.app.store.update_tx(self.tx, kind, amount, bucket, note, day)
        else:
            self.app.store.add_tx(kind, amount, bucket, note, day)
        if self.app.page_key == "Keuangan" and not self.app.store.in_period_has(self.app.fin_period, self.app.fin_ref, day):
            self.app.fin_ref = day
        self.close()
        self.app.commit("Transaksi tersimpan")


# Store helper dipakai dialog: apakah tanggal `day` termasuk periode yang sedang dilihat
def _in_view(period, ref, day):
    if period == "Harian":
        return day == ref
    if period == "Bulanan":
        return (day.year, day.month) == (ref.year, ref.month)
    return day.year == ref.year


Store.in_period_has = staticmethod(_in_view)


class ScheduleDialog(Dialog):
    def __init__(self, app, item=None, day=None):
        super().__init__(app, "Ubah jadwal" if item else "Jadwal baru")
        self.item = item
        self.heading("Ubah jadwal" if item else "Jadwal baru", "Atur kegiatan, jam, dan pengulangannya")
        f = self.field("Kegiatan")
        f.pack(fill="x", pady=(0, 12))
        self.title_var = tk.StringVar(value=item["ti"] if item else "")
        self._title_entry = entry(f, self.title_var)
        self._title_entry.pack(fill="x", ipady=7)

        row = tk.Frame(self.body, bg=WHITE)
        row.pack(fill="x", pady=(0, 12))
        f1 = self.field("Tanggal mulai")
        f1.pack(in_=row, side="left", fill="x", expand=True, padx=(0, 10))
        self.date = DateField(f1, parse_iso(item["d"]) if item else (day or date.today()))
        self.date.pack(fill="x")
        f2 = self.field("Jam")
        f2.pack(in_=row, side="left")
        self.time = TimeField(f2, item["h"] if item else "09:00")
        self.time.pack()

        f = self.field("Ulangi")
        f.pack(fill="x", pady=(0, 4))
        self.repeat = tk.StringVar(value=REPEATS[item["r"]] if item else REPEATS["none"])
        combo(f, self.repeat, list(REPEATS.values()), 30).pack(fill="x", ipady=3)
        if item and item["r"] != "none":
            lbl(self.body, "Perubahan berlaku untuk seluruh pengulangan jadwal ini.", 9, False, MUTED).pack(anchor="w", pady=(6, 0))

        self.footer("Simpan perubahan" if item else "Simpan jadwal", self.submit)
        self.bind("<Return>", lambda e: self.submit())
        self.present()
        self._title_entry.focus_set()

    def submit(self):
        title = self.title_var.get().strip()
        if not title:
            return self.show_error("Nama kegiatan wajib diisi.")
        try:
            hour = self.time.get()
        except ValueError as exc:
            return self.show_error(str(exc))
        rep = {v: k for k, v in REPEATS.items()}[self.repeat.get()]
        day = self.date.get()
        if self.item:
            self.app.store.update_item(self.item, title, day, hour, rep)
        else:
            self.app.store.add_item(title, day, hour, rep)
        self.close()
        self.app.commit("Jadwal tersimpan")


class RemindersDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, "Pengingat")
        self.heading("Pengingat", fmt_date(date.today()))
        items = app.store.reminders(date.today())
        if not items:
            lbl(self.body, "Semua beres. Tidak ada pengingat hari ini.", 10, False, MUTED).pack(anchor="w", pady=10)
        for kind, text in items:
            row = tk.Frame(self.body, bg=WHITE)
            row.pack(fill="x", pady=6)
            dot = tk.Canvas(row, width=10, height=10, bg=WHITE, highlightthickness=0, bd=0)
            dot.create_oval(1, 1, 9, 9, fill=GOLD, outline=GOLD)
            dot.pack(side="left", padx=(0, 10))
            col = tk.Frame(row, bg=WHITE)
            col.pack(side="left", fill="x", expand=True)
            lbl(col, kind, 9, True, GOLD_D).pack(anchor="w")
            lbl(col, text, 10, False, TEXT, wraplength=380, justify="left").pack(anchor="w")
        row = tk.Frame(self.body, bg=WHITE)
        row.pack(fill="x", pady=(16, 0))
        Pill(row, "Tutup", self.close, "black", padx=22).pack(side="right")
        self.present()


class ProfileDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, "Pengaturan")
        self.heading("Pengaturan", "Profil dan pengelolaan data")
        f = self.field("Nama panggilan")
        f.pack(fill="x", pady=(0, 14))
        self.name = tk.StringVar(value=app.store.data["name"])
        entry(f, self.name).pack(fill="x", ipady=7)
        lbl(self.body, "Data", 9, True, MUTED).pack(anchor="w", pady=(0, 6))
        row = tk.Frame(self.body, bg=WHITE)
        row.pack(fill="x")
        Pill(row, "Ekspor transaksi (CSV)", self.export, "white").pack(side="left")
        Pill(row, "Hapus semua data", self.wipe, "danger").pack(side="left", padx=8)
        lbl(self.body, f"Lokasi data: {app.store.path}", 8, False, MUTED, wraplength=400, justify="left").pack(anchor="w", pady=(12, 0))
        self.footer("Simpan", self.submit)
        self.present()

    def submit(self):
        self.app.store.data["name"] = self.name.get().strip()[:24] or "Kamu"
        self.close()
        self.app.commit("Pengaturan tersimpan")

    def export(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="kasku_transaksi.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            self.app.store.export_csv(path)
        except OSError as exc:
            messagebox.showerror("Gagal mengekspor", str(exc), parent=self)
            return
        self.app.toast("Ekspor selesai")

    def wipe(self):
        if messagebox.askyesno("Hapus semua data", "Semua transaksi, jadwal, dan alokasi akan dihapus permanen. Lanjutkan?",
                               parent=self):
            self.app.store.reset()
            self.app.draft = None
            self.close()
            self.app.commit("Semua data dihapus")


# =============================================================================
#  APLIKASI UTAMA
# =============================================================================
class KaskuApp(tk.Tk):
    def __init__(self):
        super().__init__()
        pick_font(self)
        self.title(f"{APP_NAME} – Keuangan & Jadwal")
        self.geometry("1260x800")
        self.minsize(1020, 660)
        self.configure(bg=IVORY)
        self.setup_styles()
        self.store = Store()
        self.page_key = "Dashboard"
        self.fin_period, self.fin_ref, self.fin_kind, self.fin_limit = "Bulanan", date.today(), "all", 40
        self.fin_query = tk.StringVar()
        self.sch_view, self.sch_ref = "Harian", date.today()
        self.draft, self.alloc_rows, self.tx_box = None, [], None
        self._today, self._debounce, self._toast = date.today(), None, None
        self.build_shell()
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.bind_all("<Button-4>", self._on_wheel)
        self.bind_all("<Button-5>", self._on_wheel)
        self.navigate("Dashboard", force=True)
        self.after(60000, self._tick)
        if self.store.notes:
            self.after(500, lambda: messagebox.showinfo("Data dibersihkan", "\n".join(self.store.notes), parent=self))

    # ----------------------------------------------------------------- gaya
    def setup_styles(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Slim.Vertical.TScrollbar", troughcolor=IVORY, background="#D8D1BD", bordercolor=IVORY,
                     lightcolor=IVORY, darkcolor=IVORY, arrowsize=0, gripcount=0, relief="flat", width=8)
        st.layout("Slim.Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        st.map("Slim.Vertical.TScrollbar", background=[("active", GOLD)])
        st.configure("K.TCombobox", fieldbackground=WHITE, background=WHITE, foreground=TEXT, bordercolor=LINE,
                     lightcolor=LINE, darkcolor=LINE, arrowcolor=GOLD_D, padding=6, relief="flat")
        st.map("K.TCombobox", fieldbackground=[("readonly", WHITE), ("disabled", IVORY)],
               foreground=[("disabled", MUTED)], bordercolor=[("focus", GOLD)], lightcolor=[("focus", GOLD)],
               darkcolor=[("focus", GOLD)], selectbackground=[("readonly", WHITE)],
               selectforeground=[("readonly", TEXT)])
        self.option_add("*TCombobox*Listbox.background", WHITE)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", GOLD)
        self.option_add("*TCombobox*Listbox.selectForeground", BLACK)
        self.option_add("*TCombobox*Listbox.font", "{%s} 10" % FONT)

    # ----------------------------------------------------------- kerangka
    def build_shell(self):
        self.sidebar = tk.Frame(self, bg=BLACK, width=SIDEBAR_W)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo = tk.Frame(self.sidebar, bg=BLACK)
        logo.pack(fill="x", padx=22, pady=(28, 26))
        mark = tk.Canvas(logo, width=38, height=38, bg=BLACK, highlightthickness=0, bd=0)
        mark.create_oval(1, 1, 37, 37, fill=GOLD, outline=GOLD)
        mark.create_text(19, 19, text="K", font=F(15, True), fill=BLACK)
        mark.pack(side="left")
        lbl(logo, APP_NAME, 17, True, WHITE).pack(side="left", padx=10)

        self.nav_items = {}
        for key, icon in (("Dashboard", "dash"), ("Keuangan", "fin"), ("Alokasi", "pie"), ("Jadwal", "cal")):
            item = NavItem(self.sidebar, key, icon, lambda k=key: self.navigate(k))
            item.pack(padx=18, pady=3)
            self.nav_items[key] = item

        bottom = tk.Frame(self.sidebar, bg=BLACK)
        bottom.pack(side="bottom", fill="x", padx=18, pady=22)
        self.tip = Card(bottom, bg=INK, radius=18, pad=16, border=EDGE_DK)
        self.tip.pack(fill="x", pady=(0, 14))
        NavItem(bottom, "Pengaturan", "gear", lambda: ProfileDialog(self)).pack()

        self.main = tk.Frame(self, bg=IVORY)
        self.main.pack(side="left", fill="both", expand=True)
        self.build_topbar()
        self.scroll = ScrollFrame(self.main, IVORY)
        self.scroll.pack(fill="both", expand=True, padx=(26, 4))

    def build_topbar(self):
        bar = tk.Frame(self.main, bg=IVORY, height=84)
        bar.pack(fill="x", padx=(32, 30))
        bar.pack_propagate(False)
        left = tk.Frame(bar, bg=IVORY)
        left.pack(side="left", fill="y")
        self.greet_var, self.date_var = tk.StringVar(), tk.StringVar()
        tk.Label(left, textvariable=self.greet_var, font=F(14, True), bg=IVORY, fg=TEXT).pack(anchor="w", pady=(22, 0))
        tk.Label(left, textvariable=self.date_var, font=F(10), bg=IVORY, fg=MUTED).pack(anchor="w")

        right = tk.Frame(bar, bg=IVORY)
        right.pack(side="right", fill="y")
        self.avatar = tk.Canvas(right, width=44, height=44, bg=IVORY, highlightthickness=0, bd=0, cursor="hand2")
        self.avatar.pack(side="right", pady=20)
        self.avatar.bind("<Button-1>", lambda e: ProfileDialog(self))
        self.bell_btn = tk.Canvas(right, width=44, height=44, bg=IVORY, highlightthickness=0, bd=0, cursor="hand2")
        self.bell_btn.pack(side="right", padx=12, pady=20)
        self.bell_btn.bind("<Button-1>", lambda e: RemindersDialog(self))

    def update_topbar(self):
        today, name = date.today(), self.store.data["name"]
        hour = __import__("datetime").datetime.now().hour
        part = "pagi" if hour < 11 else "siang" if hour < 15 else "sore" if hour < 18 else "malam"
        self.greet_var.set(f"Selamat {part}, {name}")
        self.date_var.set(fmt_date(today))

        a = self.avatar
        a.delete("all")
        a.create_oval(1, 1, 43, 43, fill=GOLD, outline=GOLD)
        a.create_text(22, 22, text=name[:1].upper(), font=F(14, True), fill=BLACK)

        b = self.bell_btn
        b.delete("all")
        b.create_oval(1, 1, 43, 43, fill=WHITE, outline=LINE)
        draw_icon(b, "bell", 22, 22, TEXT)
        n = len(self.store.reminders(today))
        if n:
            b.create_oval(26, 2, 42, 18, fill=GOLD, outline=IVORY, width=2)
            b.create_text(34, 10, text=str(min(n, 9)), font=F(8, True), fill=BLACK)

    def update_sidebar(self):
        body = self.tip.body
        for w in body.winfo_children():
            w.destroy()
        today = date.today()
        month = self.store.in_period("Bulanan", today)
        inc, exp = self.store.total("in", month), self.store.total("out", month)
        lbl(body, "Rasio tabungan bulan ini", 9, False, SOFT_DK).pack(anchor="w")
        if inc > 0:
            ratio = max(0.0, (inc - exp) / inc)
            lbl(body, f"{ratio * 100:.0f}%", 22, True, GOLD).pack(anchor="w", pady=(2, 8))
            Bar(body, ratio, 6, GOLD, "#2B2B31").pack(fill="x")
            lbl(body, "dari pemasukan yang tersisa" if exp <= inc else "pengeluaran melebihi pemasukan", 8, False, SOFT_DK
                ).pack(anchor="w", pady=(6, 0))
        else:
            lbl(body, "–", 22, True, GOLD).pack(anchor="w", pady=(2, 4))
            lbl(body, "Belum ada pemasukan bulan ini", 8, False, SOFT_DK).pack(anchor="w")

    # ---------------------------------------------------------- navigasi
    def navigate(self, key, force=False):
        if not force and self.page_key == "Alokasi" and key != "Alokasi" and self.draft is not None and self.alloc_dirty():
            ans = messagebox.askyesnocancel("Perubahan belum disimpan", "Simpan perubahan alokasi sebelum pindah halaman?",
                                            parent=self)
            if ans is None:
                return
            if ans and not self.save_alloc():
                return
        if key != "Alokasi":
            self.draft = None
        self.page_key = key
        for k, n in self.nav_items.items():
            n.set_active(k == key)
        self.refresh(reset_scroll=True)

    def refresh(self, reset_scroll=False):
        cv = self.scroll.canvas
        pos = 0.0 if reset_scroll else cv.yview()[0]
        for w in self.scroll.inner.winfo_children():
            w.destroy()
        self.alloc_rows, self.tx_box = [], None
        self.page = tk.Frame(self.scroll.inner, bg=IVORY)
        self.page.pack(fill="both", expand=True, padx=(6, 26), pady=(4, 30))
        getattr(self, "page_" + self.page_key.lower())()
        self.update_topbar()
        self.update_sidebar()
        self.update_idletasks()
        cv.configure(scrollregion=cv.bbox("all"))
        cv.yview_moveto(pos)

    def commit(self, message=None):
        err = self.store.save()
        if err:
            messagebox.showerror("Gagal menyimpan", f"Data tidak bisa disimpan:\n{err}", parent=self)
        self.refresh()
        if message and not err:
            self.toast(message)

    def toast(self, text):
        if self._toast is not None:
            try:
                self._toast.destroy()
            except tk.TclError:
                pass
        t = tk.Label(self, text=text, bg=BLACK, fg=GOLD_L, font=F(10, True), padx=18, pady=10)
        t.place(relx=1.0, rely=1.0, x=-28, y=-28, anchor="se")
        t.lift()
        self._toast = t
        self.after(2200, lambda: t.destroy() if t.winfo_exists() else None)

    def _tick(self):
        if date.today() != self._today:
            self._today = date.today()
            self.refresh()
        self.after(60000, self._tick)

    def _on_wheel(self, e):
        try:
            if e.widget.winfo_toplevel() is not self:
                return
        except (AttributeError, tk.TclError):
            return
        if getattr(e, "num", None) == 4:
            step = -1
        elif getattr(e, "num", None) == 5:
            step = 1
        else:
            d = e.delta
            if d == 0:
                return
            step = -d if sys.platform == "darwin" else (-int(d / 120) or (-1 if d > 0 else 1))
        self.scroll.scroll(step)

    def report_callback_exception(self, exc, val, tb):
        import traceback
        traceback.print_exception(exc, val, tb)
        messagebox.showerror("Terjadi kesalahan", f"{exc.__name__}: {val}", parent=self)

    # ------------------------------------------------------- blok umum UI
    def header(self, title, subtitle, *buttons):
        row = tk.Frame(self.page, bg=IVORY)
        row.pack(fill="x", pady=(4, 18))
        left = tk.Frame(row, bg=IVORY)
        left.pack(side="left")
        lbl(left, title, 24, True).pack(anchor="w")
        lbl(left, subtitle, 10, False, MUTED).pack(anchor="w")
        right = tk.Frame(row, bg=IVORY)
        right.pack(side="right")
        for make in buttons:  # urutan = dari kanan ke kiri
            make(right).pack(side="right", padx=(8, 0))

    def grid_frame(self, weights):
        f = tk.Frame(self.page, bg=IVORY)
        f.pack(fill="x")
        for i, w in enumerate(weights):
            f.grid_columnconfigure(i, weight=w, uniform="c")
        return f

    def period_bar(self, options, current, ref, on_pick, on_shift, on_today):
        bar = tk.Frame(self.page, bg=IVORY)
        bar.pack(fill="x", pady=(0, 16))
        seg = Card(bar, bg=WHITE, radius=22, pad=4)
        seg.pack(side="left")
        for opt in options:
            Pill(seg.body, opt, lambda o=opt: on_pick(o), "black" if opt == current else "ghost", padx=16).pack(side="left", padx=1)
        nav = Card(bar, bg=WHITE, radius=22, pad=4)
        nav.pack(side="right")
        Pill(nav.body, "‹", lambda: on_shift(-1), "ghost", padx=12).pack(side="left")
        lbl(nav.body, period_label(current, ref), 10, True).pack(side="left", padx=10)
        Pill(nav.body, "›", lambda: on_shift(1), "ghost", padx=12).pack(side="left")
        Pill(nav.body, "Hari ini", on_today, "white", size=9, padx=12).pack(side="left", padx=(6, 2))

    def tx_row(self, parent, t, actions=True):
        bg = parent["bg"]
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", pady=7)
        is_in = t["t"] == "in"
        dot = tk.Canvas(row, width=38, height=38, bg=bg, highlightthickness=0, bd=0)
        dot.create_oval(1, 1, 37, 37, fill=GOLD if is_in else BLACK, outline=GOLD if is_in else BLACK)
        dot.create_text(19, 19, text="+" if is_in else "−", font=F(15, True), fill=BLACK if is_in else GOLD_L)
        dot.pack(side="left")
        if actions:
            Pill(row, "Hapus", lambda: self.delete_tx(t), "danger", size=9, padx=10, pady=4).pack(side="right")
            Pill(row, "Ubah", lambda: self.open_tx(t), "ghost", size=9, padx=10, pady=4).pack(side="right")
        lbl(row, ("+" if is_in else "−") + rupiah(t["a"]), 11, True, GOLD_D if is_in else TEXT).pack(side="right", padx=14)
        mid = tk.Frame(row, bg=bg)
        mid.pack(side="left", padx=12, fill="x", expand=True)
        lbl(mid, shorten(t["n"] or ("Pemasukan" if is_in else "Pengeluaran"), 34), 10, True).pack(anchor="w")
        meta = fmt_date(parse_iso(t["d"]), "medium") + (f" · {t['b']}" if t["b"] else "")
        lbl(mid, meta, 9, False, MUTED).pack(anchor="w")
        sep(parent)

    def sch_row(self, parent, item, day, actions=True):
        s, bg = self.store, parent["bg"]
        done = s.is_done(item, day)
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", pady=7)
        CheckDot(row, done, lambda: self.toggle_done(item, day)).pack(side="left")
        if actions:
            Pill(row, "Hapus", lambda: self.delete_item(item), "danger", size=9, padx=10, pady=4).pack(side="right")
            Pill(row, "Ubah", lambda: self.open_sch(item), "ghost", size=9, padx=10, pady=4).pack(side="right")
        lbl(row, item["h"], 9, True, GOLD_D, bg=CHAMP, padx=8, pady=3).pack(side="right", padx=10)
        mid = tk.Frame(row, bg=bg)
        mid.pack(side="left", padx=12, fill="x", expand=True)
        font = tkfont.Font(family=FONT, size=10, weight="bold", overstrike=done)
        title = tk.Label(mid, text=shorten(item["ti"], 38), font=font, bg=bg, fg=MUTED if done else TEXT)
        title._keep = font
        title.pack(anchor="w")
        lbl(mid, REPEATS[item["r"]], 9, False, MUTED).pack(anchor="w")
        sep(parent)

    # ------------------------------------------------------------ aksi
    def open_tx(self, tx=None):
        TxDialog(self, tx)

    def open_sch(self, item=None, day=None):
        ScheduleDialog(self, item, day or (self.sch_ref if self.sch_view == "Harian" else date.today()))

    def delete_tx(self, t):
        if messagebox.askyesno("Hapus transaksi", "Yakin ingin menghapus transaksi ini?", parent=self):
            self.store.delete_tx(t["id"])
            self.commit("Transaksi dihapus")

    def delete_item(self, item):
        extra = "\nSemua pengulangannya ikut terhapus." if item["r"] != "none" else ""
        if messagebox.askyesno("Hapus jadwal", f"Hapus jadwal “{item['ti']}”?{extra}", parent=self):
            self.store.delete_item(item["id"])
            self.commit("Jadwal dihapus")

    def toggle_done(self, item, day):
        self.store.toggle_done(item, day)
        self.commit()

    # =========================================================== DASHBOARD
    def page_dashboard(self):
        s, today = self.store, date.today()
        self.header("Dashboard", "Ringkasan keuanganmu hari ini",
                    lambda p: Pill(p, "+ Transaksi", self.open_tx, "gold"),
                    lambda p: Pill(p, "+ Jadwal", self.open_sch, "white"))
        g = self.grid_frame((3, 2))
        month = s.in_period("Bulanan", today)
        inc, exp = s.total("in", month), s.total("out", month)
        sched = s.items_on(today)
        done = sum(1 for i in sched if s.is_done(i, today))

        hero = Card(g, bg=BLACK, radius=22, pad=24, border=BLACK)
        hero.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 16))
        b = hero.body
        lbl(b, "Total saldo", 10, False, SOFT_DK).pack(anchor="w")
        lbl(b, rupiah(s.total("in") - s.total("out")), 30, True, GOLD).pack(anchor="w", pady=(2, 14))
        row = tk.Frame(b, bg=BLACK)
        row.pack(fill="x")
        for title, val in (("Pemasukan bulan ini", inc), ("Pengeluaran bulan ini", exp)):
            col = tk.Frame(row, bg=BLACK)
            col.pack(side="left", padx=(0, 34))
            lbl(col, title, 9, False, SOFT_DK).pack(anchor="w")
            lbl(col, rupiah(val), 13, True, WHITE).pack(anchor="w")
        chips = tk.Frame(b, bg=BLACK)
        chips.pack(fill="x", pady=(20, 0))
        for k, (num, text) in enumerate(((len(sched), "Jadwal hari ini"), (done, "Selesai"), (len(sched) - done, "Tersisa"))):
            chip = Card(chips, bg=INK, radius=14, pad=10, border=EDGE_DK)
            chip.pack(side="left", expand=True, fill="x", padx=(0 if k == 0 else 8, 0))
            lbl(chip.body, str(num), 18, True, GOLD_L).pack()
            lbl(chip.body, text, 9, False, SOFT_DK).pack()

        a = s.allowance(today)
        card = Card(g)
        card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 16))
        b = card.body
        lbl(b, "Jatah belanja hari ini", 11, True).pack(anchor="w")
        lbl(b, rupiah(a["left"]), 26, True, TEXT if a["left"] >= 0 else DANGER).pack(anchor="w", pady=(8, 2))
        lbl(b, f"Terpakai {rupiah(a['spent'])} dari {rupiah(a['allow'])}", 9, False, MUTED).pack(anchor="w", pady=(0, 10))
        Bar(b, a["spent"] / a["allow"] if a["allow"] > 0 else 0, 8).pack(fill="x")
        if a["allow"] <= 0:
            lbl(b, "Isi penghasilan di menu Alokasi untuk melihat jatah harianmu.", 9, False, MUTED, wraplength=250,
                justify="left").pack(anchor="w", pady=(10, 0))
            Pill(b, "Atur alokasi", lambda: self.navigate("Alokasi"), "black", size=9).pack(anchor="w", pady=(10, 0))

        card = Card(g)
        card.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=(0, 16))
        head = tk.Frame(card.body, bg=WHITE)
        head.pack(fill="x", pady=(0, 8))
        lbl(head, "Arus kas 7 hari terakhir", 11, True).pack(side="left")
        for color, text in ((BLACK, "Keluar"), (GOLD, "Masuk")):
            lbl(head, text, 9, False, MUTED).pack(side="right", padx=(0, 4))
            sw = tk.Frame(head, bg=color, width=10, height=10)
            sw.pack(side="right", padx=(10, 2))
        BarChart(card.body, s.chart_series("Harian", today), 210).pack(fill="x")

        card = Card(g)
        card.grid(row=1, column=1, sticky="nsew", padx=(10, 0), pady=(0, 16))
        head = tk.Frame(card.body, bg=WHITE)
        head.pack(fill="x", pady=(0, 6))
        lbl(head, "Jadwal hari ini", 11, True).pack(side="left")
        Pill(head, "Lihat semua", lambda: self.navigate("Jadwal"), "ghost", size=9, padx=10, pady=3).pack(side="right")
        if not sched:
            lbl(card.body, "Belum ada jadwal hari ini.", 10, False, MUTED).pack(anchor="w", pady=8)
        for item in sched[:5]:
            self.sch_row(card.body, item, today, actions=False)
        if len(sched) > 5:
            lbl(card.body, f"+{len(sched) - 5} jadwal lainnya", 9, False, MUTED).pack(anchor="w", pady=(6, 0))

        card = Card(g)
        card.grid(row=2, column=0, sticky="nsew", padx=(0, 10))
        lbl(card.body, "Alokasi bulan ini", 11, True).pack(anchor="w", pady=(0, 10))
        rows, others = s.alloc_rows(today)
        if not rows:
            lbl(card.body, "Belum ada pos alokasi.", 10, False, MUTED).pack(anchor="w")
        for r in rows:
            top = tk.Frame(card.body, bg=WHITE)
            top.pack(fill="x")
            lbl(top, f"{r['name']} · {fmt_num(r['pct'])}%", 10, True).pack(side="left")
            lbl(top, f"{rupiah(r['spent'])} / {rupiah(r['monthly'])}", 9, False, MUTED).pack(side="right")
            Bar(card.body, r["spent"] / r["monthly"] if r["monthly"] > 0 else 0, 7).pack(fill="x", pady=(4, 12))
        if others > 0:
            top = tk.Frame(card.body, bg=WHITE)
            top.pack(fill="x")
            lbl(top, "Tanpa pos", 10, True).pack(side="left")
            lbl(top, rupiah(others), 9, False, MUTED).pack(side="right")

        card = Card(g)
        card.grid(row=2, column=1, sticky="nsew", padx=(10, 0))
        head = tk.Frame(card.body, bg=WHITE)
        head.pack(fill="x", pady=(0, 6))
        lbl(head, "Transaksi terbaru", 11, True).pack(side="left")
        Pill(head, "Lihat semua", lambda: self.navigate("Keuangan"), "ghost", size=9, padx=10, pady=3).pack(side="right")
        recent = sorted(s.data["tx"], key=lambda t: (t["d"], t["id"]), reverse=True)[:5]
        if not recent:
            lbl(card.body, "Belum ada transaksi.", 10, False, MUTED).pack(anchor="w", pady=8)
        for t in recent:
            self.tx_row(card.body, t, actions=False)

    # ============================================================ KEUANGAN
    def page_keuangan(self):
        s, period, ref = self.store, self.fin_period, self.fin_ref
        self.header("Keuangan", "Pantau pemasukan dan pengeluaran harian, bulanan, dan tahunan",
                    lambda p: Pill(p, "+ Transaksi", self.open_tx, "gold"))
        self.period_bar(["Harian", "Bulanan", "Tahunan"], period, ref, self._fin_period, self._fin_shift, self._fin_today)

        cur = s.in_period(period, ref)
        prev = s.in_period(period, shift_ref(period, ref, -1))
        word = {"Harian": "kemarin", "Bulanan": "bulan lalu", "Tahunan": "tahun lalu"}[period]
        i, e = s.total("in", cur), s.total("out", cur)
        pi, pe = s.total("in", prev), s.total("out", prev)
        g = self.grid_frame((1, 1, 1))
        specs = [("Pemasukan", i, pct_change_text(i, pi, word), False),
                 ("Pengeluaran", e, pct_change_text(e, pe, word), False),
                 ("Selisih", i - e, f"{len(cur)} transaksi", True)]
        for col, (title, val, sub, dark) in enumerate(specs):
            card = Card(g, bg=BLACK if dark else WHITE, radius=20, pad=18, border=BLACK if dark else LINE)
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0 if col == 2 else 8), pady=(0, 16))
            lbl(card.body, title, 10, False, SOFT_DK if dark else MUTED).pack(anchor="w")
            lbl(card.body, rupiah(val), 20, True, GOLD if dark else TEXT).pack(anchor="w", pady=(4, 2))
            lbl(card.body, sub, 9, False, SOFT_DK if dark else MUTED).pack(anchor="w")

        card = Card(self.page)
        card.pack(fill="x", pady=(0, 16))
        head = tk.Frame(card.body, bg=WHITE)
        head.pack(fill="x", pady=(0, 8))
        lbl(head, {"Harian": "Arus kas 7 hari", "Bulanan": "Arus kas per hari", "Tahunan": "Arus kas per bulan"}[period],
            11, True).pack(side="left")
        for color, text in ((BLACK, "Keluar"), (GOLD, "Masuk")):
            lbl(head, text, 9, False, MUTED).pack(side="right", padx=(0, 4))
            tk.Frame(head, bg=color, width=10, height=10).pack(side="right", padx=(10, 2))
        BarChart(card.body, s.chart_series(period, ref), 230).pack(fill="x")

        box = Card(self.page)
        box.pack(fill="x")
        top = tk.Frame(box.body, bg=WHITE)
        top.pack(fill="x", pady=(0, 8))
        lbl(top, "Riwayat transaksi", 12, True).pack(side="left")
        seg = tk.Frame(top, bg=WHITE)
        seg.pack(side="right")
        for key, text in (("out", "Keluar"), ("in", "Masuk"), ("all", "Semua")):
            Pill(seg, text, lambda k=key: self._fin_kind(k), "black" if self.fin_kind == key else "ghost",
                 size=9, padx=12, pady=5).pack(side="right", padx=1)
        search = entry(top, self.fin_query, 20)
        search.pack(side="right", padx=14, ipady=4)
        search.bind("<KeyRelease>", lambda e: self._schedule_fill())
        lbl(top, "Cari:", 9, False, MUTED).pack(side="right")
        self.tx_box = tk.Frame(box.body, bg=WHITE)
        self.tx_box.pack(fill="x")
        self.fill_tx_list()

    def _schedule_fill(self):
        if self._debounce:
            self.after_cancel(self._debounce)
        self._debounce = self.after(180, self.fill_tx_list)

    def fill_tx_list(self):
        box = self.tx_box
        if self.page_key != "Keuangan" or box is None or not box.winfo_exists():
            return
        for w in box.winfo_children():
            w.destroy()
        txs = self.store.in_period(self.fin_period, self.fin_ref)
        if self.fin_kind != "all":
            txs = [t for t in txs if t["t"] == self.fin_kind]
        q = self.fin_query.get().strip().lower()
        if q:
            txs = [t for t in txs if q in t["n"].lower() or q in t["b"].lower() or q in fmt_num(t["a"])]
        if not txs:
            lbl(box, "Tidak ada transaksi yang cocok di periode ini.", 10, False, MUTED).pack(anchor="w", pady=12)
            return
        for t in txs[: self.fin_limit]:
            self.tx_row(box, t)
        if len(txs) > self.fin_limit:
            Pill(box, f"Tampilkan lebih banyak ({len(txs) - self.fin_limit} lagi)", self._fin_more, "white").pack(pady=12)

    def _fin_more(self):
        self.fin_limit += 40
        self.fill_tx_list()

    def _fin_period(self, p):
        self.fin_period, self.fin_limit = p, 40
        self.refresh()

    def _fin_shift(self, n):
        self.fin_ref, self.fin_limit = shift_ref(self.fin_period, self.fin_ref, n), 40
        self.refresh()

    def _fin_today(self):
        self.fin_ref, self.fin_limit = date.today(), 40
        self.refresh()

    def _fin_kind(self, k):
        self.fin_kind, self.fin_limit = k, 40
        self.refresh()

    # ============================================================= ALOKASI
    def new_draft(self):
        d = self.store.data
        return {"inc": fmt_num(d["inc"]), "per": d["per"],
                "bk": [{"orig": b["n"], "n": b["n"], "p": fmt_num(b["p"]), "sv": b["sv"]} for b in d["bk"]]}

    def alloc_dirty(self):
        return draft_snapshot(self.draft) != store_snapshot(self.store.data)

    def page_alokasi(self):
        if self.draft is None:
            self.draft = self.new_draft()
        d = self.draft
        self.header("Alokasi keuangan", "Bagi penghasilanmu dengan persen untuk jatah harian, mingguan, dan bulanan",
                    lambda p: Pill(p, "Simpan perubahan", self.save_alloc, "gold"))
        g = self.grid_frame((3, 2))

        card = Card(g)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 16))
        b = card.body
        lbl(b, "Penghasilan kamu", 12, True).pack(anchor="w", pady=(0, 10))
        row = tk.Frame(b, bg=WHITE)
        row.pack(fill="x")
        f = tk.Frame(row, bg=WHITE)
        f.pack(side="left", fill="x", expand=True, padx=(0, 14))
        lbl(f, "Jumlah (Rp)", 9, True, MUTED).pack(anchor="w", pady=(0, 4))
        self.inc_var = tk.StringVar(value=d["inc"])
        entry(f, self.inc_var).pack(fill="x", ipady=7)
        self.inc_prev = lbl(f, "", 9, False, GOLD_D)
        self.inc_prev.pack(anchor="w", pady=(4, 0))
        self.inc_var.trace_add("write", lambda *a: self._draft_inc())
        f = tk.Frame(row, bg=WHITE)
        f.pack(side="left")
        lbl(f, "Diterima per", 9, True, MUTED).pack(anchor="w", pady=(0, 4))
        seg = Card(f, bg=IVORY, radius=20, pad=3)
        seg.pack()
        for key, text in INCOME_PER.items():
            Pill(seg.body, text, lambda k=key: self._draft_per(k), "black" if d["per"] == key else "ghost",
                 size=9, padx=12, pady=6).pack(side="left", padx=1)
        stats = tk.Frame(b, bg=WHITE)
        stats.pack(fill="x", pady=(16, 0))
        self.inc_stats = []
        for k, title in enumerate(("Per hari", "Per minggu", "Per bulan")):
            c = Card(stats, bg=CHAMP, radius=14, pad=10, border=CHAMP)
            c.pack(side="left", expand=True, fill="x", padx=(0 if k == 0 else 8, 0))
            lbl(c.body, title, 9, False, MUTED).pack(anchor="w")
            v = lbl(c.body, "", 11, True)
            v.pack(anchor="w")
            self.inc_stats.append(v)
        Pill(b, "Pakai pemasukan bulan ini", self._use_month_income, "white", size=9).pack(anchor="w", pady=(14, 0))

        card = Card(g, bg=BLACK, radius=22, pad=20, border=BLACK)
        card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 16))
        b = card.body
        lbl(b, "Komposisi alokasi", 11, True, WHITE).pack(anchor="w", pady=(0, 10))
        self.donut = Donut(b, 170, 22, BLACK)
        self.donut.pack()
        self.legend = []
        leg = tk.Frame(b, bg=BLACK)
        leg.pack(fill="x", pady=(12, 0))
        for i, _ in enumerate(d["bk"]):
            r = tk.Frame(leg, bg=BLACK)
            r.pack(fill="x", pady=2)
            sw = tk.Frame(r, bg=DONUT_COLORS[i % len(DONUT_COLORS)], width=10, height=10)
            sw.pack(side="left", padx=(0, 8))
            name = lbl(r, "", 9, False, WHITE)
            name.pack(side="left")
            pct = lbl(r, "", 9, True, GOLD_L)
            pct.pack(side="right")
            self.legend.append((name, pct))

        box = Card(self.page)
        box.pack(fill="x")
        top = tk.Frame(box.body, bg=WHITE)
        top.pack(fill="x", pady=(0, 10))
        lbl(top, "Pembagian anggaran", 12, True).pack(side="left")
        Pill(top, "+ Tambah pos", self._add_bucket, "black", size=9).pack(side="right")
        Pill(top, "Seimbangkan ke 100%", self._balance, "white", size=9).pack(side="right", padx=8)
        self._alloc_table(box.body)
        foot = tk.Frame(box.body, bg=WHITE)
        foot.pack(fill="x", pady=(14, 0))
        self.total_lbl = lbl(foot, "", 11, True)
        self.total_lbl.pack(side="left")
        self.dirty_lbl = lbl(foot, "", 9, False, MUTED)
        self.dirty_lbl.pack(side="right")
        lbl(box.body, "Centang “Tabungan” untuk pos yang tidak dihitung sebagai jatah belanja harian.", 9, False, MUTED
            ).pack(anchor="w", pady=(8, 0))
        self.recalc_alloc()

    def _alloc_table(self, parent):
        tbl = tk.Frame(parent, bg=WHITE)
        tbl.pack(fill="x")
        tbl.grid_columnconfigure(6, weight=1)
        for c, h in enumerate(("Pos anggaran", "%", "Tabungan", "Harian", "Mingguan", "Bulanan", "Terpakai bulan ini", "")):
            lbl(tbl, h, 9, True, MUTED).grid(row=0, column=c, sticky="e" if c in (3, 4, 5) else "w", padx=6, pady=(0, 6))
        for idx, b in enumerate(self.draft["bk"]):
            r = idx + 1
            nv, pv = tk.StringVar(value=b["n"]), tk.StringVar(value=b["p"])
            ne = entry(tbl, nv, 18)
            ne.grid(row=r, column=0, padx=6, pady=5, ipady=5, sticky="w")
            pe = entry(tbl, pv, 6)
            pe.grid(row=r, column=1, padx=6, pady=5, ipady=5, sticky="w")
            dot = CheckDot(tbl, b["sv"], lambda i=idx: self._toggle_saving(i))
            dot.grid(row=r, column=2, padx=6, sticky="w")
            cells = []
            for k in range(3):
                c = lbl(tbl, "", 10)
                c.grid(row=r, column=3 + k, padx=8, sticky="e")
                cells.append(c)
            cell = tk.Frame(tbl, bg=WHITE)
            cell.grid(row=r, column=6, sticky="ew", padx=8)
            spent = lbl(cell, "", 9, False, MUTED)
            spent.pack(anchor="w")
            bar = Bar(cell, 0, 6)
            bar.pack(fill="x", pady=(3, 0))
            Pill(tbl, "Hapus", lambda i=idx: self._delete_bucket(i), "danger", size=9, padx=10, pady=4
                 ).grid(row=r, column=7, padx=6)
            nv.trace_add("write", lambda *a, i=idx, v=nv: self._draft_field(i, "n", v.get()))
            pv.trace_add("write", lambda *a, i=idx, v=pv: self._draft_field(i, "p", v.get()))
            self.alloc_rows.append({"pe": pe, "dot": dot, "cells": cells, "spent": spent, "bar": bar})

    # --- perubahan draft (belum disimpan) -----------------------------------
    def _draft_inc(self):
        self.draft["inc"] = self.inc_var.get()
        self.recalc_alloc()

    def _draft_per(self, key):
        self.draft["per"] = key
        self.refresh()

    def _draft_field(self, i, key, value):
        if self.draft and i < len(self.draft["bk"]):
            self.draft["bk"][i][key] = value
            self.recalc_alloc()

    def _toggle_saving(self, i):
        b = self.draft["bk"][i]
        b["sv"] = not b["sv"]
        self.alloc_rows[i]["dot"].set(b["sv"])
        self.recalc_alloc()

    def _use_month_income(self):
        inc = self.store.total("in", self.store.in_period("Bulanan", date.today()))
        self.draft["inc"], self.draft["per"] = fmt_num(inc), "month"
        self.refresh()

    def _add_bucket(self):
        names = {b["n"].strip().lower() for b in self.draft["bk"]}
        n, k = "Pos baru", 2
        while n.lower() in names:
            n, k = f"Pos baru {k}", k + 1
        self.draft["bk"].append({"orig": None, "n": n, "p": "0", "sv": False})
        self.refresh()

    def _delete_bucket(self, i):
        b = self.draft["bk"][i]
        used = sum(1 for t in self.store.data["tx"] if b["orig"] and t["b"] == b["orig"])
        if used and not messagebox.askyesno("Hapus pos", f"Pos “{b['n']}” dipakai {used} transaksi. Transaksi tetap "
                                            "tersimpan sebagai “Tanpa pos”. Lanjutkan?", parent=self):
            return
        self.draft["bk"].pop(i)
        self.refresh()

    def _balance(self):
        bks = self.draft["bk"]
        if not bks:
            return
        vals = []
        for b in bks:
            try:
                vals.append(parse_percent(b["p"]))
            except ValueError:
                vals.append(0.0)
        total = sum(vals)
        if total <= 0:
            new = [round(100 / len(bks), 2)] * len(bks)
        else:
            new = [round(v * 100 / total, 2) for v in vals]
        new[new.index(max(new))] = round(new[new.index(max(new))] + (100 - sum(new)), 2)
        for b, v in zip(bks, new):
            b["p"] = fmt_num(v)
        self.refresh()

    def recalc_alloc(self):
        d = self.draft
        if d is None or self.page_key != "Alokasi" or len(self.alloc_rows) != len(d["bk"]):
            return
        try:
            try:
                inc = parse_money(d["inc"])
                self.inc_prev.configure(text=rupiah(inc), fg=GOLD_D)
            except ValueError:
                inc = 0.0
                self.inc_prev.configure(text="Angka belum valid. Contoh: 5000000, 5.000.000, 5jt", fg=DANGER)
            today = date.today()
            daily, weekly, monthly = split_income(inc, d["per"], today)
            for lab, v in zip(self.inc_stats, (daily, weekly, monthly)):
                lab.configure(text=rupiah(v))
            spent_map = self.store.spent_by_bucket(today)
            parts, total = [], 0.0
            for i, (row, b) in enumerate(zip(self.alloc_rows, d["bk"])):
                try:
                    p, ok = parse_percent(b["p"]), True
                except ValueError:
                    p, ok = 0.0, False
                row["pe"].configure(highlightbackground=LINE if ok else DANGER)
                total += p
                f = p / 100
                for lab, v in zip(row["cells"], (daily * f, weekly * f, monthly * f)):
                    lab.configure(text=rupiah(v))
                spent = spent_map.get(b["orig"] or b["n"].strip(), 0.0)
                bud = monthly * f
                row["spent"].configure(text=f"{rupiah(spent)} dari {rupiah(bud)}")
                row["bar"].update_ratio(spent / bud if bud > 0 else 0)
                parts.append((p, DONUT_COLORS[i % len(DONUT_COLORS)]))
                name, pct = self.legend[i]
                name.configure(text=shorten(b["n"].strip() or "(tanpa nama)", 22))
                pct.configure(text=f"{fmt_num(p)}%")
            self.donut.update_parts(parts, f"{fmt_num(total)}%")
            gap = round(100 - total, 2)
            if abs(gap) < 0.01:
                self.total_lbl.configure(text="Total 100%  ·  pas", fg=GOLD_D)
            else:
                self.total_lbl.configure(text=f"Total {fmt_num(total)}%  ·  {'kurang' if gap > 0 else 'lebih'} {fmt_num(abs(gap))}%",
                                         fg=DANGER)
            self.dirty_lbl.configure(text="Ada perubahan yang belum disimpan" if self.alloc_dirty() else "Semua perubahan tersimpan")
        except tk.TclError:
            pass

    def save_alloc(self):
        """-> True bila berhasil disimpan."""
        d = self.draft
        if d is None:
            return True
        try:
            inc = parse_money(d["inc"])
        except ValueError:
            messagebox.showwarning("Penghasilan belum valid", "Isi penghasilan dengan angka, contoh: 5000000 atau 5.000.000.",
                                   parent=self)
            return False
        rows, seen = [], set()
        for b in d["bk"]:
            name = b["n"].strip()
            if not name:
                messagebox.showwarning("Nama pos kosong", "Setiap pos harus punya nama.", parent=self)
                return False
            if name.lower() in seen:
                messagebox.showwarning("Nama pos kembar", f"Nama pos “{name}” dipakai lebih dari sekali.", parent=self)
                return False
            seen.add(name.lower())
            try:
                p = parse_percent(b["p"])
            except ValueError:
                messagebox.showwarning("Persentase belum valid", f"Persentase pos “{name}” harus berupa angka 0–100.",
                                       parent=self)
                return False
            rows.append({"orig": b["orig"], "n": name, "p": p, "sv": b["sv"]})
        total = sum(r["p"] for r in rows)
        if rows and abs(total - 100) > 0.01 and not messagebox.askyesno(
                "Total belum 100%", f"Total persentase saat ini {fmt_num(total)}%. Tetap simpan?", parent=self):
            return False
        self.store.set_allocation(inc, d["per"], rows)
        self.draft = None
        self.commit("Alokasi tersimpan")
        return True

    # ============================================================== JADWAL
    def page_jadwal(self):
        view, ref = self.sch_view, self.sch_ref
        self.header("Jadwal", "Atur agenda harian, mingguan, dan bulanan",
                    lambda p: Pill(p, "+ Jadwal", self.open_sch, "gold"))
        self.period_bar(["Harian", "Mingguan", "Bulanan"], view, ref, self._sch_view, self._sch_shift, self._sch_today)
        {"Harian": self.sch_day, "Mingguan": self.sch_week, "Bulanan": self.sch_month}[view](ref)

    def _sch_view(self, v):
        self.sch_view = v
        self.refresh()

    def _sch_shift(self, n):
        self.sch_ref = shift_ref(self.sch_view, self.sch_ref, n)
        self.refresh()

    def _sch_today(self):
        self.sch_ref = date.today()
        self.refresh()

    def _goto_day(self, d):
        self.sch_ref, self.sch_view = d, "Harian"
        self.refresh()

    def sch_day(self, ref):
        s = self.store
        g = self.grid_frame((3, 2))
        card = Card(g)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        items = s.items_on(ref)
        done = sum(1 for i in items if s.is_done(i, ref))
        head = tk.Frame(card.body, bg=WHITE)
        head.pack(fill="x", pady=(0, 6))
        lbl(head, "Agenda", 12, True).pack(side="left")
        lbl(head, f"{done} dari {len(items)} selesai" if items else "", 9, False, MUTED).pack(side="right")
        if not items:
            lbl(card.body, "Belum ada jadwal di tanggal ini. Tambahkan lewat tombol “+ Jadwal”.", 10, False, MUTED,
                wraplength=420, justify="left").pack(anchor="w", pady=12)
        for item in items:
            self.sch_row(card.body, item, ref)

        card = Card(g, bg=BLACK, radius=22, pad=20, border=BLACK)
        card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        lbl(card.body, "Agenda terdekat", 12, True, WHITE).pack(anchor="w", pady=(0, 8))
        today, seen, upcoming = date.today(), set(), []
        for k in range(30):
            day = today + timedelta(days=k)
            for item in s.items_on(day):
                if item["id"] in seen or s.is_done(item, day):
                    continue
                seen.add(item["id"])
                upcoming.append((day, item))
        if not upcoming:
            lbl(card.body, "Tidak ada agenda dalam 30 hari ke depan.", 10, False, SOFT_DK, wraplength=260,
                justify="left").pack(anchor="w", pady=6)
        for day, item in upcoming[:6]:
            row = tk.Frame(card.body, bg=BLACK)
            row.pack(fill="x", pady=7)
            lbl(row, f"{DAYS_SHORT[day.weekday()]}\n{day.day}", 10, True, BLACK, bg=GOLD, width=4, pady=4).pack(side="left")
            col = tk.Frame(row, bg=BLACK)
            col.pack(side="left", padx=12, fill="x", expand=True)
            lbl(col, shorten(item["ti"], 26), 10, True, WHITE).pack(anchor="w")
            lbl(col, f"{item['h']} · {REPEATS[item['r']]}", 9, False, SOFT_DK).pack(anchor="w")
            row.bind("<Button-1>", lambda e, d=day: self._goto_day(d))

    def sch_week(self, ref):
        s, today = self.store, date.today()
        g = tk.Frame(self.page, bg=IVORY)
        g.pack(fill="x")
        start = monday_of(ref)
        for c in range(7):
            g.grid_columnconfigure(c, weight=1, uniform="w")
            day = start + timedelta(days=c)
            today_col = day == today
            card = Card(g, bg=BLACK if today_col else WHITE, radius=18, pad=10, border=BLACK if today_col else LINE)
            card.grid(row=0, column=c, sticky="nsew", padx=(0 if c == 0 else 4, 0 if c == 6 else 4))
            b = card.body
            bg = BLACK if today_col else WHITE
            head = lbl(b, f"{DAYS_SHORT[c]} {day.day}", 10, True, GOLD_L if today_col else TEXT)
            head.pack(anchor="w")
            head.bind("<Button-1>", lambda e, d=day: self._goto_day(d))
            items = s.items_on(day)
            if not items:
                lbl(b, "–", 9, False, SOFT_DK if today_col else MUTED).pack(anchor="w", pady=(8, 0))
            for item in items:
                done = s.is_done(item, day)
                row = tk.Frame(b, bg=bg)
                row.pack(fill="x", pady=(8, 0))
                CheckDot(row, done, lambda i=item, d=day: self.toggle_done(i, d), 18).pack(side="left", anchor="n")
                col = lbl(row, f"{item['h']}\n{shorten(item['ti'], 16)}", 8, False,
                          (SOFT_DK if done else WHITE) if today_col else (MUTED if done else TEXT),
                          justify="left", wraplength=84, anchor="w")
                col.pack(side="left", padx=(6, 0), fill="x", expand=True)
                col.bind("<Button-1>", lambda e, i=item: self.open_sch(i))

    def sch_month(self, ref):
        s, today = self.store, date.today()
        g = tk.Frame(self.page, bg=IVORY)
        g.pack(fill="x")
        for c in range(7):
            g.grid_columnconfigure(c, weight=1, uniform="m")
            lbl(g, DAYS_SHORT[c], 10, True, MUTED).grid(row=0, column=c, pady=(0, 6))
        weeks = calendar.Calendar(0).monthdatescalendar(ref.year, ref.month)
        for r, week in enumerate(weeks, start=1):
            g.grid_rowconfigure(r, minsize=100)
            for c, day in enumerate(week):
                if day.month != ref.month:
                    continue
                is_today = day == today
                cell = tk.Frame(g, bg=WHITE, highlightthickness=2 if is_today else 1,
                                highlightbackground=GOLD if is_today else LINE, cursor="hand2", height=100)
                cell.grid(row=r, column=c, sticky="nsew", padx=2, pady=2)
                cell.pack_propagate(False)
                num = lbl(cell, str(day.day), 10, True, GOLD_L if is_today else TEXT, bg=BLACK if is_today else WHITE,
                          padx=7, pady=1)
                num.pack(anchor="nw", padx=6, pady=(6, 2))
                items = s.items_on(day)
                kids = [num]
                for item in items[:2]:
                    chip = lbl(cell, f"• {item['h']} {shorten(item['ti'], 10)}", 8, False,
                               MUTED if s.is_done(item, day) else TEXT, anchor="w")
                    chip.pack(fill="x", padx=6)
                    kids.append(chip)
                if len(items) > 2:
                    more = lbl(cell, f"+{len(items) - 2} lagi", 8, True, GOLD_D, anchor="w")
                    more.pack(fill="x", padx=6)
                    kids.append(more)
                for w in [cell] + kids:
                    w.bind("<Button-1>", lambda e, d=day: self._goto_day(d))


# =============================================================================
#  UJI LOGIKA  (python kasku_black_gold.py --selftest)
# =============================================================================
def run_selftest():
    def raises(fn, *a):
        try:
            fn(*a)
        except ValueError:
            return True
        return False

    # angka
    assert parse_money("50.000") == 50000 and parse_money("1.500.000") == 1500000
    assert parse_money("Rp 75rb") == 75000 and parse_money("1,5jt") == 1500000
    assert parse_money("1.500,50") == 1500.5 and parse_money("12.5") == 12.5 and parse_money("5000000") == 5e6
    assert parse_money("Rp 50.000,-") == 50000 and parse_money("0.5") == 0.5
    for bad in ("", "abc", "nan", "inf", "-5", "1.2.3", "1e999", "1..2"):
        assert raises(parse_money, bad), bad
    assert parse_percent("33,5%") == 33.5 and raises(parse_percent, "nan") and raises(parse_percent, "101")
    assert rupiah(1500000) == "Rp 1.500.000" and rupiah(-5000) == "-Rp 5.000" and rupiah(float("nan")) == "Rp 0"
    assert short_rp(1500000) == "1,5jt" and short_rp(2000) == "2rb" and short_rp(950) == "950"
    assert nice_ceil(180000) == 200000 and nice_ceil(0) == 1
    # tanggal & pengulangan
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 1, 15), -2) == date(2025, 11, 15)
    m31 = {"d": "2026-01-31", "r": "month"}
    assert occurs(m31, date(2026, 2, 28)) and not occurs(m31, date(2026, 2, 27)) and occurs(m31, date(2026, 3, 31))
    wk = {"d": "2026-10-19", "r": "week"}
    assert occurs(wk, date(2026, 10, 26)) and not occurs(wk, date(2026, 10, 25)) and not occurs(wk, date(2026, 10, 12))
    assert occurs({"d": "2026-10-21", "r": "none"}, date(2026, 10, 21)) and not occurs({"d": "2026-10-21", "r": "none"}, date(2026, 10, 22))
    # alokasi
    d, w, mo = split_income(3100000, "month", date(2026, 10, 1))
    assert abs(d - 100000) < 1e-6 and abs(mo - 3100000) < 1e-6 and abs(w - 700000) < 1e-6
    # bersih-bersih data rusak
    raw = {"inc": "abc", "per": "zzz", "bk": [{"n": "A", "p": "nan"}, {"n": "a", "p": 10}, {"n": "Tabungan", "p": 500}],
           "tx": [{"id": 1, "t": "in", "a": "nan", "d": "2026-10-01"}, {"id": 1, "t": "out", "a": 5, "d": "bukan-tanggal"},
                  {"id": 7, "t": "out", "a": 5000, "b": "A", "d": "2026-10-02"}, {"id": 7, "t": "in", "a": 9, "d": "2026-10-03"}],
           "sc": [{"ti": "", "d": "2026-10-01"}, {"ti": "X", "d": "2026-10-01", "h": "9:05", "r": "??", "dn": {"2026-10-01": True, "x": True}}]}
    clean, notes = sanitize(raw)
    assert clean["inc"] == 0 and clean["per"] == "month" and [b["n"] for b in clean["bk"]] == ["A", "Tabungan"]
    assert clean["bk"][1]["p"] == 100 and clean["bk"][1]["sv"] is True
    assert len(clean["tx"]) == 2 and len({t["id"] for t in clean["tx"]}) == 2
    assert clean["sc"][0]["h"] == "09:05" and clean["sc"][0]["r"] == "none" and clean["sc"][0]["dn"] == {"2026-10-01": True}
    assert notes and sanitize("sampah")[0] == empty_data()
    # simpan / muat / cadangan
    tmp = Path(tempfile.mkdtemp())
    try:
        st = Store(tmp / "k.json")
        assert st.data["tx"] and st.save() is None
        st.add_tx("out", 25000, "Kebutuhan", " kopi ", date(2026, 10, 21))
        assert st.save() is None and Store(tmp / "k.json").data["tx"][-1]["n"] == "kopi"
        (tmp / "k.json").write_text("{rusak", encoding="utf-8")
        assert Store(tmp / "k.json").data["tx"], "harus pulih dari .bak"
        (tmp / "k.bak").unlink()
        broken = Store(tmp / "k.json")
        assert broken.data["tx"] == [] and broken.notes and (tmp / "k.corrupt").exists()
        # ganti nama pos memindahkan transaksi; urutan tukar nama tidak saling menimpa
        st = Store(tmp / "x.json")
        st.data = empty_data()
        st.data["bk"] = [{"n": "A", "p": 50.0, "sv": False}, {"n": "B", "p": 50.0, "sv": False}]
        st.add_tx("out", 10, "A", "", date(2026, 10, 1))
        st.add_tx("out", 20, "B", "", date(2026, 10, 1))
        st.set_allocation(1000, "month", [{"orig": "A", "n": "B", "p": 50, "sv": False}, {"orig": "B", "n": "A", "p": 50, "sv": False}])
        assert [t["b"] for t in st.data["tx"]] == ["B", "A"]
        # jatah harian: pos tabungan tidak dihitung
        st.data = empty_data()
        st.data["inc"], st.data["per"] = 3100000.0, "month"
        st.add_tx("out", 10000, "Kebutuhan", "", date(2026, 10, 5))
        st.add_tx("out", 99999, "Tabungan", "", date(2026, 10, 5))
        a = st.allowance(date(2026, 10, 5))
        assert abs(a["allow"] - 80000) < 1e-6 and a["spent"] == 10000
        rows, others = st.alloc_rows(date(2026, 10, 5))
        assert abs(rows[0]["monthly"] - 1550000) < 1e-6 and rows[0]["spent"] == 10000 and others == 0
        series = st.chart_series("Bulanan", date(2026, 10, 5))
        assert len(series) == 31 and series[4][2] == 109999
        assert len(st.chart_series("Tahunan", date(2026, 10, 5))) == 12 and len(st.chart_series("Harian", date(2026, 10, 5))) == 7
        st.export_csv(tmp / "e.csv")
        assert (tmp / "e.csv").read_text(encoding="utf-8-sig").startswith("Tanggal,Jenis")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("Semua uji logika lulus.")


def main():
    if "--selftest" in sys.argv:
        run_selftest()
        return
    app = KaskuApp()
    app.mainloop()


if __name__ == "__main__":
    main()
