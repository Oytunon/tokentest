#!/usr/bin/env python3
"""CRM Yetki Kontrolü — 2 sekmeli araç.

Sekme 1 (CRM Yetki): token listesi → Account/CheckAuthentication → PermissionList.
  ViewCRM varsa CRM yetkisi vardır. Token'lar: CRM Yetkili / CRM Yok / Geçersiz.
Sekme 2 (Telefon): aynı org'un token listesi + o org'dan bir Client ID →
  her token için Client/GetClientById?id=<id> çağrılır, dönen telefon tam mı maskeli mi.
  Telefon Açık / Maskeli / Geçersiz-Yok.

Karar mantığı crm_logic.py içindedir.
"""

import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from dark_theme import (
    FAIL_BG, FAIL_FG, OK_BG, OK_FG, OTHER_BG, OTHER_FG, RATE_BG, RATE_FG,
    apply_dark_theme, style_menu, style_text_widget,
)
import crm_logic
from crm_logic import CAT_CRM, CAT_NO_CRM

DEFAULT_CONCURRENCY = 8
BASE_URL = "https://backofficewebadmin.betconstruct.com/api/en"
CHECK_AUTH_URL = f"{BASE_URL}/Account/CheckAuthentication"
GET_CLIENT_BY_ID_URL = f"{BASE_URL}/Client/GetClientById"

_thread_local = threading.local()


def _session() -> requests.Session:
    s = getattr(_thread_local, "s", None)
    if s is None:
        s = requests.Session()
        _thread_local.s = s
    return s


def _editable(root, widget):
    widget.config(exportselection=True, undo=True)

    def paste(_e=None):
        try:
            widget.insert(tk.INSERT, root.clipboard_get())
        except tk.TclError:
            pass
        return "break"

    def copy(_e=None):
        try:
            root.clipboard_clear()
            root.clipboard_append(widget.get(tk.SEL_FIRST, tk.SEL_LAST))
        except tk.TclError:
            pass
        return "break"

    def select_all(_e=None):
        widget.tag_add(tk.SEL, "1.0", tk.END)
        return "break"

    for seq in ("<Control-v>", "<Control-V>", "<Shift-Insert>"):
        widget.bind(seq, paste)
    for seq in ("<Control-c>", "<Control-C>"):
        widget.bind(seq, copy)
    for seq in ("<Control-a>", "<Control-A>"):
        widget.bind(seq, select_all)
    m = tk.Menu(widget, tearoff=0)
    m.add_command(label="Yapıştır", command=lambda: paste())
    m.add_command(label="Kopyala", command=lambda: copy())
    m.add_command(label="Tümünü Seç", command=lambda: select_all())
    style_menu(m)
    widget.bind("<Button-3>", lambda e: m.tk_popup(e.x_root, e.y_root))


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("CRM Yetki Kontrolü")
        root.geometry("1120x820")
        root.minsize(900, 640)
        apply_dark_theme(root)

        self._stop1 = threading.Event()
        self._w1: threading.Thread | None = None
        self._stop2 = threading.Event()
        self._w2: threading.Thread | None = None

        self._perm_tabs: dict[str, dict] = {}

        nb = ttk.Notebook(root)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        t1 = ttk.Frame(nb, padding=10)
        t2 = ttk.Frame(nb, padding=10)
        t3 = ttk.Frame(nb, padding=10)
        t4 = ttk.Frame(nb, padding=10)
        t5 = ttk.Frame(nb, padding=10)
        nb.add(t1, text="CRM Yetki (toplu)")
        nb.add(t2, text="Telefon (Client ID)")
        nb.add(t3, text="Bilgi Güncelleme")
        nb.add(t4, text="Correction Up")
        nb.add(t5, text="Sistem Uyumu")
        self._build_crm(t1)
        self._build_phone(t2)
        self._build_perm_tab(
            t3, "upd", "ManageClients",
            "Her token için Account/CheckAuthentication çağrılır; yetki listesinde ManageClients varsa "
            "müşteri bilgilerini güncelleme (kart üstünde Güncelle/Kaydet) yetkisi vardır. Org fark etmez. "
            "Yetki adından emin değilsen üstteki kutudan değiştirip tekrar çalıştır — doğru adları yetkiler.txt'de bulursun.",
        )
        self._build_perm_tab(
            t4, "corr", "MakeCorrection",
            "Her token için Account/CheckAuthentication çağrılır; yetki listesinde MakeCorrection varsa "
            "Correction Up yetkisi vardır (bakiyeye para ekleme = 'corr up'; canlı test ile doğrulandı — "
            "yetki yoksa sunucu 'Not allowed (MakeCorrectionUp)' döner, para eklenmez). Org fark etmez. "
            "Yetki adını üstteki kutudan değiştirebilirsin.",
            ok_label="Correction Up Yetkili ✓",
        )
        self._build_compat_tab(t5)

    # ---------- ortak ----------
    def _paste_into(self, widget):
        try:
            widget.insert(tk.INSERT, self.root.clipboard_get())
            widget.focus_set()
        except tk.TclError:
            messagebox.showinfo("Bilgi", "Panoda metin yok.")

    def _lines(self, widget) -> list[str]:
        out, seen = [], set()
        for line in widget.get("1.0", tk.END).splitlines():
            s = line.strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out

    def _panel(self, parent, title, bg, fg):
        f = ttk.LabelFrame(parent, text=title, padding=4)
        count = tk.StringVar(value="0")
        head = ttk.Frame(f)
        head.pack(fill=tk.X)
        ttk.Label(head, textvariable=count, font=("", 9, "bold")).pack(side=tk.RIGHT)
        txt = scrolledtext.ScrolledText(f, height=14, wrap=tk.NONE, font=("Consolas", 9))
        txt.pack(fill=tk.BOTH, expand=True)
        style_text_widget(txt, bg=bg, fg=fg)
        return {"frame": f, "text": txt, "count": count}

    def _add(self, panel, line):
        panel["text"].insert(tk.END, line + "\n")
        panel["text"].see(tk.END)
        panel["count"].set(str(int(panel["count"].get()) + 1))

    def _copy_panel(self, panel):
        content = panel["text"].get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Bilgi", "Kopyalanacak sonuç yok.")
            return
        out = []
        for line in content.splitlines():
            c = line.split("  →  ")[0].strip()
            if c.startswith("[") and "] " in c:
                c = c.split("] ", 1)[-1].strip()
            if c:
                out.append(c)
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(out))
        messagebox.showinfo("Kopyalandı", f"{len(out)} token kopyalandı.")

    # ==================== SEKME 1: CRM ====================
    def _build_crm(self, main):
        info = ttk.LabelFrame(main, text="Bu sekme ne yapar?", padding=8)
        info.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(
            info,
            text="Tüm token'ları tek seferde CRM yetkisine göre ayırır. Her token için "
            "Account/CheckAuthentication çağrılır; yetki listesinde ViewCRM varsa CRM yetkisi vardır. "
            "Org fark etmez — hepsini birden yapıştırabilirsin.",
            wraplength=1060,
        ).pack(anchor=tk.W)

        s = ttk.LabelFrame(main, text="İstek Ayarları", padding=8)
        s.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(s, text="Auth header:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.c_header = tk.StringVar(value="Authentication")
        ttk.Entry(s, textvariable=self.c_header, width=18).grid(row=0, column=1, sticky=tk.W, padx=(6, 0))
        ttk.Label(s, text="Timeout (sn):").grid(row=0, column=2, sticky=tk.W, padx=(16, 0))
        self.c_timeout = tk.StringVar(value="15")
        ttk.Entry(s, textvariable=self.c_timeout, width=8).grid(row=0, column=3, sticky=tk.W, padx=(6, 0))
        ttk.Label(s, text="Eşzamanlı:").grid(row=0, column=4, sticky=tk.W, padx=(16, 0))
        self.c_conc = tk.StringVar(value=str(DEFAULT_CONCURRENCY))
        ttk.Entry(s, textvariable=self.c_conc, width=8).grid(row=0, column=5, sticky=tk.W, padx=(6, 0))

        tf = ttk.LabelFrame(main, text="Token Listesi (her satıra bir token)", padding=8)
        tf.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(tf, text="Yapıştır", command=lambda: self._paste_into(self.c_tokens)).pack(anchor=tk.E, pady=(0, 4))
        self.c_tokens = scrolledtext.ScrolledText(tf, height=9, wrap=tk.NONE, font=("Consolas", 10))
        self.c_tokens.pack(fill=tk.X)
        style_text_widget(self.c_tokens)
        _editable(self.root, self.c_tokens)

        ctr = ttk.Frame(main)
        ctr.pack(fill=tk.X, pady=(0, 8))
        self.c_start = ttk.Button(ctr, text="Kontrol Et", command=self._crm_start)
        self.c_start.pack(side=tk.LEFT)
        self.c_stop = ttk.Button(ctr, text="Durdur", command=lambda: self._stop1.set(), state=tk.DISABLED)
        self.c_stop.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(ctr, text="Temizle", command=self._crm_clear).pack(side=tk.LEFT, padx=(8, 0))
        self.c_prog_var = tk.StringVar(value="Hazır")
        ttk.Label(ctr, textvariable=self.c_prog_var).pack(side=tk.LEFT, padx=(16, 0))
        self.c_prog = ttk.Progressbar(main, mode="determinate")
        self.c_prog.pack(fill=tk.X, pady=(0, 8))

        res = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        res.pack(fill=tk.BOTH, expand=True)
        self.c_ok = self._panel(res, "CRM Yetkili ✓", OK_BG, OK_FG)
        self.c_no = self._panel(res, "CRM Yok", OTHER_BG, OTHER_FG)
        self.c_bad = self._panel(res, "Geçersiz / Hata", FAIL_BG, FAIL_FG)
        for p in (self.c_ok, self.c_no, self.c_bad):
            res.add(p["frame"], weight=1)

        summ = ttk.Frame(main)
        summ.pack(fill=tk.X, pady=(8, 0))
        self.c_summary = tk.StringVar(value="")
        ttk.Label(summ, textvariable=self.c_summary).pack(side=tk.LEFT)
        ttk.Button(summ, text="CRM Yok Kopyala", command=lambda: self._copy_panel(self.c_no)).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(summ, text="CRM Yetkili Kopyala", command=lambda: self._copy_panel(self.c_ok)).pack(side=tk.RIGHT, padx=(4, 0))

    def _crm_check(self, token, header, timeout):
        try:
            r = _session().get(CHECK_AUTH_URL, headers={"Accept": "application/json", header: token}, timeout=timeout)
        except requests.RequestException as e:
            return token, "bad", str(e)
        try:
            payload = r.json()
        except ValueError:
            payload = None
        res = crm_logic.classify(r.status_code, payload)
        if res.category == CAT_CRM:
            return token, "ok", f"{res.permission_count} yetki"
        if res.category == CAT_NO_CRM:
            return token, "no", f"{res.permission_count} yetki"
        return token, "bad", res.detail

    def _crm_start(self):
        tokens = self._lines(self.c_tokens)
        if not tokens:
            messagebox.showwarning("Uyarı", "En az bir token girin.")
            return
        header = self.c_header.get().strip() or "Authentication"
        try:
            timeout = float(self.c_timeout.get().strip())
            conc = int(self.c_conc.get().strip())
            if timeout <= 0 or conc <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Uyarı", "Timeout/eşzamanlı geçerli sayı olmalı.")
            return
        for p in (self.c_ok, self.c_no, self.c_bad):
            p["text"].delete("1.0", tk.END)
            p["count"].set("0")
        self.c_summary.set("")
        self._stop1.clear()
        self.c_start.config(state=tk.DISABLED)
        self.c_stop.config(state=tk.NORMAL)
        self.c_prog.config(maximum=len(tokens), value=0)

        def worker():
            counts = {"ok": 0, "no": 0, "bad": 0}
            done = 0
            ex = ThreadPoolExecutor(max_workers=conc)
            futs = [ex.submit(self._crm_check, t, header, timeout) for t in tokens]
            try:
                for fut in as_completed(futs):
                    if self._stop1.is_set():
                        break
                    token, kind, note = fut.result()
                    counts[kind] += 1
                    panel = {"ok": self.c_ok, "no": self.c_no, "bad": self.c_bad}[kind]
                    line = f"{token}  →  {note}" if kind != "bad" else f"[{note or 'hata'}] {token}"
                    self.root.after(0, lambda p=panel, l=line: self._add(p, l))
                    done += 1
                    self.root.after(0, lambda d=done: self.c_prog.config(value=d))
                    self.root.after(0, lambda d=done, n=len(tokens): self.c_prog_var.set(f"İşleniyor: {d}/{n}"))
            finally:
                ex.shutdown(wait=False, cancel_futures=True)

            def fin():
                self.c_start.config(state=tk.NORMAL)
                self.c_stop.config(state=tk.DISABLED)
                self.c_prog_var.set("Durduruldu" if self._stop1.is_set() else "Tamamlandı")
                self.c_summary.set(f"Toplam: {len(tokens)} | CRM Yetkili: {counts['ok']} | CRM Yok: {counts['no']} | Geçersiz/Hata: {counts['bad']}")
            self.root.after(0, fin)

        self._w1 = threading.Thread(target=worker, daemon=True)
        self._w1.start()

    def _crm_clear(self):
        if self._w1 and self._w1.is_alive():
            messagebox.showinfo("Bilgi", "Önce durdurun.")
            return
        self.c_tokens.delete("1.0", tk.END)
        for p in (self.c_ok, self.c_no, self.c_bad):
            p["text"].delete("1.0", tk.END)
            p["count"].set("0")
        self.c_summary.set("")
        self.c_prog.config(value=0)
        self.c_prog_var.set("Hazır")

    # ==================== SEKME 2: TELEFON ====================
    def _build_phone(self, main):
        info = ttk.LabelFrame(main, text="Bu sekme ne yapar?", padding=8)
        info.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(
            info,
            text="Aynı org'un token'larını listeye yapıştır ve o org'dan bir Client ID gir. Her token için "
            "Client/GetClientById?id=<ID> çağrılır; telefon tam (905...) dönüyorsa o token telefonu AÇIK görüyor, "
            "**** dönüyorsa maskeli. Client ID her org'da farklıdır, org değişince ID'yi de değiştir.",
            wraplength=1060,
        ).pack(anchor=tk.W)

        s = ttk.LabelFrame(main, text="İstek Ayarları", padding=8)
        s.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(s, text="Client ID:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.p_cid = tk.StringVar(value="")
        ttk.Entry(s, textvariable=self.p_cid, width=20).grid(row=0, column=1, sticky=tk.W, padx=(6, 0))
        ttk.Label(s, text="(bu org'dan bir müşteri ID'si)").grid(row=0, column=2, columnspan=3, sticky=tk.W, padx=(8, 0))
        ttk.Label(s, text="Auth header:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.p_header = tk.StringVar(value="Authentication")
        ttk.Entry(s, textvariable=self.p_header, width=18).grid(row=1, column=1, sticky=tk.W, padx=(6, 0))
        ttk.Label(s, text="Timeout:").grid(row=1, column=2, sticky=tk.W, padx=(16, 0))
        self.p_timeout = tk.StringVar(value="15")
        ttk.Entry(s, textvariable=self.p_timeout, width=8).grid(row=1, column=3, sticky=tk.W, padx=(6, 0))
        ttk.Label(s, text="Eşzamanlı:").grid(row=1, column=4, sticky=tk.W, padx=(16, 0))
        self.p_conc = tk.StringVar(value=str(DEFAULT_CONCURRENCY))
        ttk.Entry(s, textvariable=self.p_conc, width=8).grid(row=1, column=5, sticky=tk.W, padx=(6, 0))

        tf = ttk.LabelFrame(main, text="Token Listesi (aynı org — her satıra bir token)", padding=8)
        tf.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(tf, text="Yapıştır", command=lambda: self._paste_into(self.p_tokens)).pack(anchor=tk.E, pady=(0, 4))
        self.p_tokens = scrolledtext.ScrolledText(tf, height=9, wrap=tk.NONE, font=("Consolas", 10))
        self.p_tokens.pack(fill=tk.X)
        style_text_widget(self.p_tokens)
        _editable(self.root, self.p_tokens)

        ctr = ttk.Frame(main)
        ctr.pack(fill=tk.X, pady=(0, 8))
        self.p_start = ttk.Button(ctr, text="Telefonu Kontrol Et", command=self._phone_start)
        self.p_start.pack(side=tk.LEFT)
        self.p_stop = ttk.Button(ctr, text="Durdur", command=lambda: self._stop2.set(), state=tk.DISABLED)
        self.p_stop.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(ctr, text="Temizle", command=self._phone_clear).pack(side=tk.LEFT, padx=(8, 0))
        self.p_prog_var = tk.StringVar(value="Hazır")
        ttk.Label(ctr, textvariable=self.p_prog_var).pack(side=tk.LEFT, padx=(16, 0))
        self.p_prog = ttk.Progressbar(main, mode="determinate")
        self.p_prog.pack(fill=tk.X, pady=(0, 8))

        res = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        res.pack(fill=tk.BOTH, expand=True)
        self.p_open = self._panel(res, "Telefon Açık ✓", OK_BG, OK_FG)
        self.p_masked = self._panel(res, "Telefon Maskeli", RATE_BG, RATE_FG)
        self.p_bad = self._panel(res, "Geçersiz / Telefon Yok", FAIL_BG, FAIL_FG)
        for p in (self.p_open, self.p_masked, self.p_bad):
            res.add(p["frame"], weight=1)

        summ = ttk.Frame(main)
        summ.pack(fill=tk.X, pady=(8, 0))
        self.p_summary = tk.StringVar(value="")
        ttk.Label(summ, textvariable=self.p_summary).pack(side=tk.LEFT)
        ttk.Button(summ, text="Maskeli Kopyala", command=lambda: self._copy_panel(self.p_masked)).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(summ, text="Açık Kopyala", command=lambda: self._copy_panel(self.p_open)).pack(side=tk.RIGHT, padx=(4, 0))

    @staticmethod
    def _mask_mid(s):
        s = str(s)
        if not s or "*" in s or sum(c.isdigit() for c in s) < 6:
            return s
        return s[:4] + "*" * max(0, len(s) - 6) + s[-2:]

    def _phone_check(self, token, cid, header, timeout):
        try:
            d = _session().get(f"{GET_CLIENT_BY_ID_URL}?id={cid}",
                               headers={"Accept": "application/json", header: token}, timeout=timeout)
        except requests.RequestException as e:
            return token, "bad", str(e)
        if d.status_code != 200:
            return token, "bad", f"HTTP {d.status_code}"
        try:
            js = d.json()
        except ValueError:
            return token, "bad", "json yok"
        verdict, sample = crm_logic.phone_verdict(js)
        if verdict == "açık":
            return token, "open", sample  # tam numara — kendi aracın, maskeleme yok
        if verdict == "maskeli":
            return token, "masked", sample
        return token, "bad", "telefon yok"

    def _phone_start(self):
        cid = self.p_cid.get().strip()
        if not cid:
            messagebox.showwarning("Uyarı", "Client ID girin (bu org'dan bir müşteri ID'si).")
            return
        tokens = self._lines(self.p_tokens)
        if not tokens:
            messagebox.showwarning("Uyarı", "En az bir token girin.")
            return
        header = self.p_header.get().strip() or "Authentication"
        try:
            timeout = float(self.p_timeout.get().strip())
            conc = int(self.p_conc.get().strip())
            if timeout <= 0 or conc <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Uyarı", "Timeout/eşzamanlı geçerli sayı olmalı.")
            return
        for p in (self.p_open, self.p_masked, self.p_bad):
            p["text"].delete("1.0", tk.END)
            p["count"].set("0")
        self.p_summary.set("")
        self._stop2.clear()
        self.p_start.config(state=tk.DISABLED)
        self.p_stop.config(state=tk.NORMAL)
        self.p_prog.config(maximum=len(tokens), value=0)

        def worker():
            counts = {"open": 0, "masked": 0, "bad": 0}
            done = 0
            ex = ThreadPoolExecutor(max_workers=conc)
            futs = [ex.submit(self._phone_check, t, cid, header, timeout) for t in tokens]
            try:
                for fut in as_completed(futs):
                    if self._stop2.is_set():
                        break
                    token, kind, note = fut.result()
                    counts[kind] += 1
                    panel = {"open": self.p_open, "masked": self.p_masked, "bad": self.p_bad}[kind]
                    line = f"{token}  →  {note}" if kind != "bad" else f"[{note or 'hata'}] {token}"
                    self.root.after(0, lambda p=panel, l=line: self._add(p, l))
                    done += 1
                    self.root.after(0, lambda d=done: self.p_prog.config(value=d))
                    self.root.after(0, lambda d=done, n=len(tokens): self.p_prog_var.set(f"İşleniyor: {d}/{n}"))
            finally:
                ex.shutdown(wait=False, cancel_futures=True)

            def fin():
                self.p_start.config(state=tk.NORMAL)
                self.p_stop.config(state=tk.DISABLED)
                self.p_prog_var.set("Durduruldu" if self._stop2.is_set() else "Tamamlandı")
                self.p_summary.set(f"Toplam: {len(tokens)} | Telefon Açık: {counts['open']} | Maskeli: {counts['masked']} | Geçersiz/Yok: {counts['bad']}")
            self.root.after(0, fin)

        self._w2 = threading.Thread(target=worker, daemon=True)
        self._w2.start()

    def _phone_clear(self):
        if self._w2 and self._w2.is_alive():
            messagebox.showinfo("Bilgi", "Önce durdurun.")
            return
        self.p_tokens.delete("1.0", tk.END)
        for p in (self.p_open, self.p_masked, self.p_bad):
            p["text"].delete("1.0", tk.END)
            p["count"].set("0")
        self.p_summary.set("")
        self.p_prog.config(value=0)
        self.p_prog_var.set("Hazır")

    # ============ GENEL YETKİ SEKMELERİ (Bilgi Güncelleme / Corr Up) ============
    # CRM sekmesinin birebir aynısı; tek farkı kontrol edilen yetki adının
    # düzenlenebilir olması. Her sekmenin durumu self._perm_tabs[key] içinde tutulur.
    def _build_perm_tab(self, main, key, default_perm, info_text, ok_label="Yetki Var ✓"):
        st = {"stop": threading.Event(), "thread": None}
        self._perm_tabs[key] = st

        info = ttk.LabelFrame(main, text="Bu sekme ne yapar?", padding=8)
        info.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(info, text=info_text, wraplength=1060).pack(anchor=tk.W)

        s = ttk.LabelFrame(main, text="İstek Ayarları", padding=8)
        s.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(s, text="Yetki adı:").grid(row=0, column=0, sticky=tk.W, pady=2)
        st["perm"] = tk.StringVar(value=default_perm)
        ttk.Entry(s, textvariable=st["perm"], width=26).grid(row=0, column=1, sticky=tk.W, padx=(6, 0))
        ttk.Label(s, text="(PermissionList'teki ad — yanlışsa değiştir, yetkiler.txt'ye bak)").grid(
            row=0, column=2, columnspan=4, sticky=tk.W, padx=(8, 0))
        ttk.Label(s, text="Auth header:").grid(row=1, column=0, sticky=tk.W, pady=2)
        st["header"] = tk.StringVar(value="Authentication")
        ttk.Entry(s, textvariable=st["header"], width=18).grid(row=1, column=1, sticky=tk.W, padx=(6, 0))
        ttk.Label(s, text="Timeout (sn):").grid(row=1, column=2, sticky=tk.W, padx=(16, 0))
        st["timeout"] = tk.StringVar(value="15")
        ttk.Entry(s, textvariable=st["timeout"], width=8).grid(row=1, column=3, sticky=tk.W, padx=(6, 0))
        ttk.Label(s, text="Eşzamanlı:").grid(row=1, column=4, sticky=tk.W, padx=(16, 0))
        st["conc"] = tk.StringVar(value=str(DEFAULT_CONCURRENCY))
        ttk.Entry(s, textvariable=st["conc"], width=8).grid(row=1, column=5, sticky=tk.W, padx=(6, 0))

        tf = ttk.LabelFrame(main, text="Token Listesi (her satıra bir token)", padding=8)
        tf.pack(fill=tk.X, pady=(0, 8))
        st["tokens"] = scrolledtext.ScrolledText(tf, height=9, wrap=tk.NONE, font=("Consolas", 10))
        ttk.Button(tf, text="Yapıştır", command=lambda: self._paste_into(st["tokens"])).pack(anchor=tk.E, pady=(0, 4))
        st["tokens"].pack(fill=tk.X)
        style_text_widget(st["tokens"])
        _editable(self.root, st["tokens"])

        ctr = ttk.Frame(main)
        ctr.pack(fill=tk.X, pady=(0, 8))
        st["start"] = ttk.Button(ctr, text="Kontrol Et", command=lambda: self._perm_start(key))
        st["start"].pack(side=tk.LEFT)
        st["stopb"] = ttk.Button(ctr, text="Durdur", command=lambda: st["stop"].set(), state=tk.DISABLED)
        st["stopb"].pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(ctr, text="Temizle", command=lambda: self._perm_clear(key)).pack(side=tk.LEFT, padx=(8, 0))
        st["prog_var"] = tk.StringVar(value="Hazır")
        ttk.Label(ctr, textvariable=st["prog_var"]).pack(side=tk.LEFT, padx=(16, 0))
        st["prog"] = ttk.Progressbar(main, mode="determinate")
        st["prog"].pack(fill=tk.X, pady=(0, 8))

        res = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        res.pack(fill=tk.BOTH, expand=True)
        st["ok"] = self._panel(res, ok_label, OK_BG, OK_FG)
        st["no"] = self._panel(res, "Yetki Yok", OTHER_BG, OTHER_FG)
        st["bad"] = self._panel(res, "Geçersiz / Hata", FAIL_BG, FAIL_FG)
        for p in (st["ok"], st["no"], st["bad"]):
            res.add(p["frame"], weight=1)

        summ = ttk.Frame(main)
        summ.pack(fill=tk.X, pady=(8, 0))
        st["summary"] = tk.StringVar(value="")
        ttk.Label(summ, textvariable=st["summary"]).pack(side=tk.LEFT)
        ttk.Button(summ, text="Yetki Yok Kopyala", command=lambda: self._copy_panel(st["no"])).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(summ, text="Yetki Var Kopyala", command=lambda: self._copy_panel(st["ok"])).pack(side=tk.RIGHT, padx=(4, 0))

    def _perm_check(self, token, perm, header, timeout):
        try:
            r = _session().get(CHECK_AUTH_URL, headers={"Accept": "application/json", header: token}, timeout=timeout)
        except requests.RequestException as e:
            return token, "bad", str(e)
        try:
            payload = r.json()
        except ValueError:
            payload = None
        kind, detail, _ = crm_logic.classify_permission(r.status_code, payload, perm)
        route = {
            crm_logic.PERM_YES: "ok",
            crm_logic.PERM_NO: "no",
            crm_logic.PERM_INVALID: "bad",
            crm_logic.PERM_RATE: "bad",
            crm_logic.PERM_OTHER: "bad",
        }
        return token, route[kind], detail

    def _perm_start(self, key):
        st = self._perm_tabs[key]
        perm = st["perm"].get().strip()
        if not perm:
            messagebox.showwarning("Uyarı", "Yetki adı girin.")
            return
        tokens = self._lines(st["tokens"])
        if not tokens:
            messagebox.showwarning("Uyarı", "En az bir token girin.")
            return
        header = st["header"].get().strip() or "Authentication"
        try:
            timeout = float(st["timeout"].get().strip())
            conc = int(st["conc"].get().strip())
            if timeout <= 0 or conc <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Uyarı", "Timeout/eşzamanlı geçerli sayı olmalı.")
            return
        for p in (st["ok"], st["no"], st["bad"]):
            p["text"].delete("1.0", tk.END)
            p["count"].set("0")
        st["summary"].set("")
        st["stop"].clear()
        st["start"].config(state=tk.DISABLED)
        st["stopb"].config(state=tk.NORMAL)
        st["prog"].config(maximum=len(tokens), value=0)

        def worker():
            counts = {"ok": 0, "no": 0, "bad": 0}
            done = 0
            ex = ThreadPoolExecutor(max_workers=conc)
            futs = [ex.submit(self._perm_check, t, perm, header, timeout) for t in tokens]
            try:
                for fut in as_completed(futs):
                    if st["stop"].is_set():
                        break
                    token, kind, note = fut.result()
                    counts[kind] += 1
                    panel = {"ok": st["ok"], "no": st["no"], "bad": st["bad"]}[kind]
                    line = f"{token}  →  {note}" if kind != "bad" else f"[{note or 'hata'}] {token}"
                    self.root.after(0, lambda p=panel, l=line: self._add(p, l))
                    done += 1
                    self.root.after(0, lambda d=done: st["prog"].config(value=d))
                    self.root.after(0, lambda d=done, n=len(tokens): st["prog_var"].set(f"İşleniyor: {d}/{n}"))
            finally:
                ex.shutdown(wait=False, cancel_futures=True)

            def fin():
                st["start"].config(state=tk.NORMAL)
                st["stopb"].config(state=tk.DISABLED)
                st["prog_var"].set("Durduruldu" if st["stop"].is_set() else "Tamamlandı")
                st["summary"].set(
                    f"Yetki: {perm} | Toplam: {len(tokens)} | Var: {counts['ok']} | Yok: {counts['no']} | Geçersiz/Hata: {counts['bad']}")
            self.root.after(0, fin)

        st["thread"] = threading.Thread(target=worker, daemon=True)
        st["thread"].start()

    def _perm_clear(self, key):
        st = self._perm_tabs[key]
        if st["thread"] and st["thread"].is_alive():
            messagebox.showinfo("Bilgi", "Önce durdurun.")
            return
        st["tokens"].delete("1.0", tk.END)
        for p in (st["ok"], st["no"], st["bad"]):
            p["text"].delete("1.0", tk.END)
            p["count"].set("0")
        st["summary"].set("")
        st["prog"].config(value=0)
        st["prog_var"].set("Hazır")

    # ==================== SEKME 5: SİSTEM UYUMU ====================
    # Token, gerekli yetkilerin HEPSİNE sahip mi? (telefon açık + mail görme +
    # bc mesaj + mail gönderme). Gerekli yetki listesi düzenlenebilir.
    DEFAULT_REQUIRED = "ViewMaskedPhone, ViewClientEmail, ManageClientMessage, ManageClientEmail"

    def _build_compat_tab(self, main):
        st = {"stop": threading.Event(), "thread": None}
        self._compat = st

        info = ttk.LabelFrame(main, text="Bu sekme ne yapar?", padding=8)
        info.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(
            info,
            text="Her token için Account/CheckAuthentication çağrılır; aşağıdaki gerekli yetkilerin "
            "HEPSİ varsa token 'Tam Uyumlu' sayılır, bazısı eksikse 'Eksik Yetki' panelinde hangi "
            "yetkilerin eksik olduğu yazılır. Varsayılan set: telefon açık (ViewMaskedPhone) + mail görme "
            "(ViewClientEmail) + BC içi mesaj (ManageClientMessage) + mail gönderme (ManageClientEmail). "
            "Gerekli yetkileri aşağıdan değiştirebilirsin (virgülle ayır).",
            wraplength=1060,
        ).pack(anchor=tk.W)

        s = ttk.LabelFrame(main, text="İstek Ayarları", padding=8)
        s.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(s, text="Gerekli yetkiler:").grid(row=0, column=0, sticky=tk.W, pady=2)
        st["required"] = tk.StringVar(value=self.DEFAULT_REQUIRED)
        req_entry = ttk.Entry(s, textvariable=st["required"], width=70)
        req_entry.grid(row=0, column=1, columnspan=5, sticky=tk.W + tk.E, padx=(6, 0))
        ttk.Label(s, text="Auth header:").grid(row=1, column=0, sticky=tk.W, pady=2)
        st["header"] = tk.StringVar(value="Authentication")
        ttk.Entry(s, textvariable=st["header"], width=18).grid(row=1, column=1, sticky=tk.W, padx=(6, 0))
        ttk.Label(s, text="Timeout (sn):").grid(row=1, column=2, sticky=tk.W, padx=(16, 0))
        st["timeout"] = tk.StringVar(value="15")
        ttk.Entry(s, textvariable=st["timeout"], width=8).grid(row=1, column=3, sticky=tk.W, padx=(6, 0))
        ttk.Label(s, text="Eşzamanlı:").grid(row=1, column=4, sticky=tk.W, padx=(16, 0))
        st["conc"] = tk.StringVar(value=str(DEFAULT_CONCURRENCY))
        ttk.Entry(s, textvariable=st["conc"], width=8).grid(row=1, column=5, sticky=tk.W, padx=(6, 0))

        tf = ttk.LabelFrame(main, text="Token Listesi (her satıra bir token)", padding=8)
        tf.pack(fill=tk.X, pady=(0, 8))
        st["tokens"] = scrolledtext.ScrolledText(tf, height=9, wrap=tk.NONE, font=("Consolas", 10))
        ttk.Button(tf, text="Yapıştır", command=lambda: self._paste_into(st["tokens"])).pack(anchor=tk.E, pady=(0, 4))
        st["tokens"].pack(fill=tk.X)
        style_text_widget(st["tokens"])
        _editable(self.root, st["tokens"])

        ctr = ttk.Frame(main)
        ctr.pack(fill=tk.X, pady=(0, 8))
        st["start"] = ttk.Button(ctr, text="Kontrol Et", command=self._compat_start)
        st["start"].pack(side=tk.LEFT)
        st["stopb"] = ttk.Button(ctr, text="Durdur", command=lambda: st["stop"].set(), state=tk.DISABLED)
        st["stopb"].pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(ctr, text="Temizle", command=self._compat_clear).pack(side=tk.LEFT, padx=(8, 0))
        st["prog_var"] = tk.StringVar(value="Hazır")
        ttk.Label(ctr, textvariable=st["prog_var"]).pack(side=tk.LEFT, padx=(16, 0))
        st["prog"] = ttk.Progressbar(main, mode="determinate")
        st["prog"].pack(fill=tk.X, pady=(0, 8))

        res = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        res.pack(fill=tk.BOTH, expand=True)
        st["ok"] = self._panel(res, "Tam Uyumlu ✓", OK_BG, OK_FG)
        st["missing"] = self._panel(res, "Eksik Yetki", RATE_BG, RATE_FG)
        st["bad"] = self._panel(res, "Geçersiz / Hata", FAIL_BG, FAIL_FG)
        for p in (st["ok"], st["missing"], st["bad"]):
            res.add(p["frame"], weight=1)

        summ = ttk.Frame(main)
        summ.pack(fill=tk.X, pady=(8, 0))
        st["summary"] = tk.StringVar(value="")
        ttk.Label(summ, textvariable=st["summary"]).pack(side=tk.LEFT)
        ttk.Button(summ, text="Eksikleri Kopyala", command=lambda: self._copy_panel(st["missing"])).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(summ, text="Tam Uyumlu Kopyala", command=lambda: self._copy_panel(st["ok"])).pack(side=tk.RIGHT, padx=(4, 0))

    def _compat_check(self, token, required, header, timeout):
        try:
            r = _session().get(CHECK_AUTH_URL, headers={"Accept": "application/json", header: token}, timeout=timeout)
        except requests.RequestException as e:
            return token, "bad", str(e)
        try:
            payload = r.json()
        except ValueError:
            payload = None
        kind, missing, count, detail = crm_logic.classify_permissions(r.status_code, payload, required)
        if kind == crm_logic.COMPAT_ALL:
            return token, "ok", f"{count} yetki, hepsi var"
        if kind == crm_logic.COMPAT_MISSING:
            return token, "missing", "eksik: " + ", ".join(missing)
        return token, "bad", detail

    def _compat_start(self):
        st = self._compat
        required = [x for x in st["required"].get().replace(",", " ").split() if x]
        if not required:
            messagebox.showwarning("Uyarı", "En az bir gerekli yetki girin.")
            return
        tokens = self._lines(st["tokens"])
        if not tokens:
            messagebox.showwarning("Uyarı", "En az bir token girin.")
            return
        header = st["header"].get().strip() or "Authentication"
        try:
            timeout = float(st["timeout"].get().strip())
            conc = int(st["conc"].get().strip())
            if timeout <= 0 or conc <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Uyarı", "Timeout/eşzamanlı geçerli sayı olmalı.")
            return
        for p in (st["ok"], st["missing"], st["bad"]):
            p["text"].delete("1.0", tk.END)
            p["count"].set("0")
        st["summary"].set("")
        st["stop"].clear()
        st["start"].config(state=tk.DISABLED)
        st["stopb"].config(state=tk.NORMAL)
        st["prog"].config(maximum=len(tokens), value=0)

        def worker():
            counts = {"ok": 0, "missing": 0, "bad": 0}
            done = 0
            ex = ThreadPoolExecutor(max_workers=conc)
            futs = [ex.submit(self._compat_check, t, required, header, timeout) for t in tokens]
            try:
                for fut in as_completed(futs):
                    if st["stop"].is_set():
                        break
                    token, kind, note = fut.result()
                    counts[kind] += 1
                    panel = {"ok": st["ok"], "missing": st["missing"], "bad": st["bad"]}[kind]
                    line = f"{token}  →  {note}" if kind != "bad" else f"[{note or 'hata'}] {token}"
                    self.root.after(0, lambda p=panel, l=line: self._add(p, l))
                    done += 1
                    self.root.after(0, lambda d=done: st["prog"].config(value=d))
                    self.root.after(0, lambda d=done, n=len(tokens): st["prog_var"].set(f"İşleniyor: {d}/{n}"))
            finally:
                ex.shutdown(wait=False, cancel_futures=True)

            def fin():
                st["start"].config(state=tk.NORMAL)
                st["stopb"].config(state=tk.DISABLED)
                st["prog_var"].set("Durduruldu" if st["stop"].is_set() else "Tamamlandı")
                st["summary"].set(
                    f"Toplam: {len(tokens)} | Tam Uyumlu: {counts['ok']} | Eksik: {counts['missing']} | Geçersiz/Hata: {counts['bad']}")
            self.root.after(0, fin)

        st["thread"] = threading.Thread(target=worker, daemon=True)
        st["thread"].start()

    def _compat_clear(self):
        st = self._compat
        if st["thread"] and st["thread"].is_alive():
            messagebox.showinfo("Bilgi", "Önce durdurun.")
            return
        st["tokens"].delete("1.0", tk.END)
        for p in (st["ok"], st["missing"], st["bad"]):
            p["text"].delete("1.0", tk.END)
            p["count"].set("0")
        st["summary"].set("")
        st["prog"].config(value=0)
        st["prog_var"].set("Hazır")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
