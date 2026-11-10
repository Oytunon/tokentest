#!/usr/bin/env python3
"""CLI test — .env'deki token(lari) CANLI dener. Her token icin:
  1) Account/CheckAuthentication → CRM yetkisi (ViewCRM)
  2) .env'de CLIENT_ID varsa → Client/GetClientById?id=<CLIENT_ID> → telefon tam mi maskeli mi

Token'lar maskeli basilir. GUI'siz; dogrulama icindir.
Kullanim:  py -3 crm_test_cli.py   (.env: TOKENS=... ve ops. CLIENT_ID=...)
"""

import sys
from pathlib import Path

import requests

import crm_logic

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "https://backofficewebadmin.betconstruct.com/api/en"
CHECK_AUTH = f"{BASE}/Account/CheckAuthentication"
GET_CLIENT_BY_ID = f"{BASE}/Client/GetClientById"
DEFAULT_HEADER = "Authentication"

CAT_TR = {
    crm_logic.CAT_CRM: "CRM yetkili",
    crm_logic.CAT_NO_CRM: "CRM yetkisi yok",
    crm_logic.CAT_INVALID: "Geçersiz / ölü token",
    crm_logic.CAT_RATE: "Rate-limit (403/429)",
    crm_logic.CAT_OTHER: "Diğer/Hata",
}


def load_env(path: Path) -> dict:
    env: dict = {}
    if not path.is_file():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def tokens_from_env(env: dict) -> list[str]:
    parts: list[str] = []
    for key, value in env.items():
        if key.upper().startswith("TOKEN") and value:
            parts.extend(chunk for chunk in value.replace(",", " ").split())
    out, seen = [], set()
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            out.append(part)
    return out


def mask(token: str) -> str:
    return f"{token[:4]}…{token[-4:]}" if len(token) > 10 else "*" * len(token)


def mask_mid(s: str) -> str:
    s = str(s)
    if not s or "*" in s or sum(c.isdigit() for c in s) < 6:
        return s
    return s[:4] + "*" * max(0, len(s) - 6) + s[-2:]


def main() -> int:
    env = load_env(Path(__file__).resolve().parent / ".env")
    tokens = tokens_from_env(env)
    if not tokens:
        print("HATA: .env icinde test token'i yok. TOKENS= satirina en az bir token yaz.")
        return 1
    header = env.get("AUTH_HEADER") or DEFAULT_HEADER
    client_id = (env.get("CLIENT_ID") or "").strip()
    print(f"{len(tokens)} token denenecek · CheckAuthentication")
    if client_id:
        print(f"telefon kontrolü için Client ID: {client_id}")
    else:
        print("(CLIENT_ID yok → telefon kontrol edilmez; .env'e CLIENT_ID=... ekle)")
    print()

    for index, token in enumerate(tokens, 1):
        try:
            r = requests.get(CHECK_AUTH, headers={"Accept": "application/json", header: token}, timeout=20)
            payload = r.json() if r.content else None
        except Exception as exc:
            print(f"[{index}] {mask(token)}  HATA: {exc}\n")
            continue
        res = crm_logic.classify(r.status_code, payload)
        perms = crm_logic.extract_permissions(payload)
        print(f"[{index}] {mask(token)}  HTTP {r.status_code}  →  {CAT_TR.get(res.category, res.category)}  ({len(perms)} yetki)")
        if res.detail:
            print(f"     not: {res.detail}")

        if res.category == crm_logic.CAT_CRM and client_id:
            try:
                d = requests.get(f"{GET_CLIENT_BY_ID}?id={client_id}",
                                 headers={"Accept": "application/json", header: token}, timeout=20)
                js = d.json()
                verdict, sample = crm_logic.phone_verdict(js)
                extra = f"  ({mask_mid(sample)})" if sample else ""
                print(f"     telefon (GetClientById): {verdict}{extra}")
            except Exception as exc:
                print(f"     telefon kontrol hatası: {exc}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
