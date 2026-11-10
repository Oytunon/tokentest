"""CRM + telefon görme yetkisi tespiti — Account/CheckAuthentication tabanlı.

Backoffice token'ıyla GET /api/en/Account/CheckAuthentication çağrılır; cevaptaki
Data.PermissionList (hesabın yetki listesi) okunur. Bu liste, backoffice sol menüsünü
çizen yetkilerin ta kendisidir — GetClients gibi herkese açık bir çağrıdan çok daha
doğrudur (GetClients, CRM'i olmayan hesaplara da 200 döner).

CRM yetkisi = PermissionList içinde 'ViewCRM'.

TELEFON ayrı belirlenir: GetClients listesi telefonu HERKESE '****' maskeler, bu yüzden
yetki göstergesi DEĞİLDİR. Full telefon ancak müşteri DETAY çağrısında görünür:
  GET /api/en/Client/GetClientById?id=<client_id>  → Data.Phone tam (905...) ya da '****'.
Bir token o detayda tam numara görüyorsa telefon görme yetkisi VAR, '****' görüyorsa yok.
Bu kontrol GUI'de bir Client ID ile yapılır (org'a göre girilir); classify sadece CRM'e bakar.

Kategoriler:
  CAT_CRM        → token geçerli ve ViewCRM var (telefon henüz belirlenmedi)
  CAT_NO_CRM     → token geçerli ama ViewCRM yok
  CAT_INVALID    → token geçersiz/ölü (401) ya da HasError
  CAT_RATE       → 403/429 (rate-limit)
  CAT_OTHER      → diğer HTTP / bağlantı hatası
GUI, CAT_CRM token'ları GetClientById telefon sonucuna göre CAT_CRM_PHONE / CAT_CRM_ONLY yapar.
"""

from dataclasses import dataclass

CAT_CRM = "crm"  # geçerli token + ViewCRM; telefon ayrı GetClientById çağrısıyla belirlenir
CAT_CRM_PHONE = "crm_phone"  # CAT_CRM + telefon açık (GUI'de atanır)
CAT_CRM_ONLY = "crm_only"  # CAT_CRM + telefon maskeli/yok (GUI'de atanır)
CAT_NO_CRM = "no_crm"
CAT_INVALID = "invalid"
CAT_RATE = "rate"
CAT_OTHER = "other"

PERM_CRM = "ViewCRM"


@dataclass
class Classification:
    category: str
    crm: bool = False
    phone_state: str = ""  # "açık" | "maskeli" | "yok" | ""
    detail: str = ""
    permission_count: int = 0


def iter_leaves(data, prefix=""):
    """JSON ağacındaki skaler yaprakları (anahtar_yolu, değer) olarak gezer."""
    if isinstance(data, dict):
        for key, value in data.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from iter_leaves(value, next_prefix)
    elif isinstance(data, (list, tuple)):
        for item in data:
            yield from iter_leaves(item, prefix)
    else:
        yield prefix, data


def extract_permissions(json_data) -> set[str]:
    """CheckAuthentication cevabından Data.PermissionList'i küme olarak döner."""
    if not isinstance(json_data, dict):
        return set()
    data = json_data.get("Data")
    perms = data.get("PermissionList") if isinstance(data, dict) else None
    if isinstance(perms, list):
        return {str(p).strip() for p in perms if str(p).strip()}
    return set()


PHONE_FIELDS_DETAIL = ("Phone", "MobilePhone")


def phone_values(json_data) -> list[str]:
    """Cevaptaki Phone / MobilePhone alanlarının boş olmayan değerleri."""
    out: list[str] = []
    for key_path, value in iter_leaves(json_data):
        if key_path.split(".")[-1] in PHONE_FIELDS_DETAIL:
            text = "" if value is None else str(value).strip()
            if text:
                out.append(text)
    return out


def is_masked_value(text: str) -> bool:
    return "*" in text


def phone_verdict(json_data) -> tuple[str, str]:
    """Detay cevabındaki telefona göre ('açık' | 'maskeli' | 'yok', örnek)."""
    values = phone_values(json_data)
    for text in values:
        if not is_masked_value(text) and sum(ch.isdigit() for ch in text) >= 7:
            return "açık", text
    for text in values:
        if is_masked_value(text):
            return "maskeli", text
    return "yok", ""


def classify(http_status: int, json_data) -> Classification:
    """HTTP kodu + CheckAuthentication gövdesinden token'ı kategorilere ayırır."""
    if http_status == 200 and isinstance(json_data, dict):
        if json_data.get("HasError") is True:
            message = str(json_data.get("AlertMessage") or json_data.get("Message") or "HasError")
            return Classification(CAT_INVALID, detail=message)
        perms = extract_permissions(json_data)
        if not perms:
            return Classification(CAT_INVALID, detail="yetki listesi boş/yok")
        # CRM yetkisi burada belirlenir; telefon ayrı GetClientById çağrısıyla (GUI'de).
        if PERM_CRM in perms:
            return Classification(CAT_CRM, True, "", "", len(perms))
        return Classification(CAT_NO_CRM, False, "", "", len(perms))

    if http_status == 401:
        return Classification(CAT_INVALID, detail="401 geçersiz/ölü token")
    if http_status in (403, 429):
        return Classification(CAT_RATE, detail=str(http_status))
    if http_status < 0:
        return Classification(CAT_OTHER, detail="bağlantı hatası")
    return Classification(CAT_OTHER, detail=f"HTTP {http_status}")


# Genel yetki kontrolü: PermissionList'te belirli bir yetki var mı?
# CRM/telefon sekmeleri gibi özel değil — herhangi bir yetki adıyla çalışır.
PERM_YES = "yes"       # token geçerli + yetki var
PERM_NO = "no"         # token geçerli + yetki yok
PERM_INVALID = "invalid"  # 401 / HasError / boş liste
PERM_RATE = "rate"     # 403 / 429
PERM_OTHER = "other"   # diğer HTTP / bağlantı hatası


def classify_permission(http_status: int, json_data, perm: str) -> tuple[str, str, int]:
    """CheckAuthentication cevabında `perm` yetkisinin olup olmadığını döner.

    (kind, detail, permission_count) — kind: PERM_YES/PERM_NO/PERM_INVALID/PERM_RATE/PERM_OTHER.
    Yetki adı büyük/küçük harf duyarsız eşleşir (PermissionList adları değişebiliyor).
    """
    perm_norm = (perm or "").strip().lower()
    if http_status == 200 and isinstance(json_data, dict):
        if json_data.get("HasError") is True:
            message = str(json_data.get("AlertMessage") or json_data.get("Message") or "HasError")
            return PERM_INVALID, message, 0
        perms = extract_permissions(json_data)
        if not perms:
            return PERM_INVALID, "yetki listesi boş/yok", 0
        have = {p.lower() for p in perms}
        if perm_norm and perm_norm in have:
            return PERM_YES, f"{len(perms)} yetki", len(perms)
        return PERM_NO, f"{len(perms)} yetki", len(perms)

    if http_status == 401:
        return PERM_INVALID, "401 geçersiz/ölü token", 0
    if http_status in (403, 429):
        return PERM_RATE, str(http_status), 0
    if http_status < 0:
        return PERM_OTHER, "bağlantı hatası", 0
    return PERM_OTHER, f"HTTP {http_status}", 0


# Çoklu yetki kontrolü: bir token verilen yetkilerin HEPSİNE sahip mi?
# "Sistem Uyumu" sekmesi için (ör. telefon açık + mail görme + bc mesaj + mail gönderme).
COMPAT_ALL = "all"          # token geçerli ve gerekli yetkilerin hepsi var
COMPAT_MISSING = "missing"  # token geçerli ama bazı yetkiler eksik
COMPAT_INVALID = "invalid"  # 401 / HasError / boş liste
COMPAT_RATE = "rate"        # 403 / 429
COMPAT_OTHER = "other"      # diğer HTTP / bağlantı hatası


def classify_permissions(http_status: int, json_data, required) -> tuple[str, list[str], int, str]:
    """Token, `required` listesindeki yetkilerin HEPSİNE sahip mi?

    (kind, missing, permission_count, detail) döner.
      kind: COMPAT_ALL/COMPAT_MISSING/COMPAT_INVALID/COMPAT_RATE/COMPAT_OTHER
      missing: eksik yetki adları (COMPAT_MISSING'te dolu). Eşleşme case-insensitive,
               eksik adlar orijinal yazımıyla döner.
    """
    req = [str(r).strip() for r in (required or []) if str(r).strip()]
    if http_status == 200 and isinstance(json_data, dict):
        if json_data.get("HasError") is True:
            message = str(json_data.get("AlertMessage") or json_data.get("Message") or "HasError")
            return COMPAT_INVALID, [], 0, message
        perms = extract_permissions(json_data)
        if not perms:
            return COMPAT_INVALID, [], 0, "yetki listesi boş/yok"
        if not req:
            return COMPAT_INVALID, [], len(perms), "gerekli yetki girilmedi"
        have = {p.lower() for p in perms}
        missing = [r for r in req if r.lower() not in have]
        if not missing:
            return COMPAT_ALL, [], len(perms), ""
        return COMPAT_MISSING, missing, len(perms), ""

    if http_status == 401:
        return COMPAT_INVALID, [], 0, "401 geçersiz/ölü token"
    if http_status in (403, 429):
        return COMPAT_RATE, [], 0, str(http_status)
    if http_status < 0:
        return COMPAT_OTHER, [], 0, "bağlantı hatası"
    return COMPAT_OTHER, [], 0, f"HTTP {http_status}"
