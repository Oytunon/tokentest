"""crm_logic testleri. classify CRM'e bakar (CAT_CRM/CAT_NO_CRM/...); telefon ise
phone_verdict ile GetClientById cevabından belirlenir. Dış bağımlılık yok."""

import unittest

from crm_logic import (
    CAT_CRM,
    CAT_INVALID,
    CAT_NO_CRM,
    CAT_OTHER,
    CAT_RATE,
    COMPAT_ALL,
    COMPAT_INVALID,
    COMPAT_MISSING,
    COMPAT_RATE,
    PERM_INVALID,
    PERM_NO,
    PERM_OTHER,
    PERM_RATE,
    PERM_YES,
    classify,
    classify_permission,
    classify_permissions,
    extract_permissions,
    phone_verdict,
)

REQ4 = ["ViewMaskedPhone", "ViewClientEmail", "ManageClientMessage", "ManageClientEmail"]


def auth_response(perms):
    """Account/CheckAuthentication başarılı cevabını taklit eder."""
    return {
        "HasError": False,
        "AlertMessage": None,
        "Data": {"UserName": "tester", "PermissionList": list(perms)},
    }


class Permissions(unittest.TestCase):
    def test_extract_from_data_permissionlist(self):
        perms = extract_permissions(auth_response(["ViewCRM", "ViewReports"]))
        self.assertEqual(perms, {"ViewCRM", "ViewReports"})

    def test_extract_empty_when_missing(self):
        self.assertEqual(extract_permissions({"Data": {}}), set())
        self.assertEqual(extract_permissions({}), set())
        self.assertEqual(extract_permissions(None), set())


class Classify(unittest.TestCase):
    def test_crm_token(self):
        result = classify(200, auth_response(["ViewCRM", "ViewReports"]))
        self.assertEqual(result.category, CAT_CRM)
        self.assertTrue(result.crm)

    def test_no_crm_but_valid(self):
        result = classify(200, auth_response(["ViewClients", "ViewReports"]))
        self.assertEqual(result.category, CAT_NO_CRM)
        self.assertFalse(result.crm)

    def test_invalid_token_401(self):
        self.assertEqual(classify(401, None).category, CAT_INVALID)

    def test_haserror_is_invalid(self):
        self.assertEqual(classify(200, {"HasError": True, "AlertMessage": "bad"}).category, CAT_INVALID)

    def test_empty_permissionlist_is_invalid(self):
        self.assertEqual(classify(200, auth_response([])).category, CAT_INVALID)

    def test_rate_limited(self):
        self.assertEqual(classify(403, None).category, CAT_RATE)
        self.assertEqual(classify(429, None).category, CAT_RATE)

    def test_other_and_connection_error(self):
        self.assertEqual(classify(500, None).category, CAT_OTHER)
        self.assertEqual(classify(-1, None).category, CAT_OTHER)

    def test_permission_count_reported(self):
        result = classify(200, auth_response(["ViewCRM", "ViewReports", "ViewClients"]))
        self.assertEqual(result.permission_count, 3)


class ClassifyPermission(unittest.TestCase):
    """Genel yetki kontrolü — Bilgi Güncelleme (ManageClients) / Corr Up (MakeCorrection) sekmeleri."""

    def test_permission_present(self):
        kind, _, count = classify_permission(200, auth_response(["ManageClients", "ViewCRM"]), "ManageClients")
        self.assertEqual(kind, PERM_YES)
        self.assertEqual(count, 2)

    def test_permission_absent(self):
        kind, _, count = classify_permission(200, auth_response(["ViewCRM", "ViewReports"]), "ManageClients")
        self.assertEqual(kind, PERM_NO)
        self.assertEqual(count, 2)

    def test_case_insensitive_match(self):
        kind, _, _ = classify_permission(200, auth_response(["makecorrection"]), "MakeCorrection")
        self.assertEqual(kind, PERM_YES)

    def test_invalid_401(self):
        self.assertEqual(classify_permission(401, None, "ManageClients")[0], PERM_INVALID)

    def test_haserror_invalid(self):
        kind, _, _ = classify_permission(200, {"HasError": True, "AlertMessage": "bad"}, "ManageClients")
        self.assertEqual(kind, PERM_INVALID)

    def test_empty_list_invalid(self):
        self.assertEqual(classify_permission(200, auth_response([]), "ManageClients")[0], PERM_INVALID)

    def test_rate_and_other(self):
        self.assertEqual(classify_permission(403, None, "X")[0], PERM_RATE)
        self.assertEqual(classify_permission(429, None, "X")[0], PERM_RATE)
        self.assertEqual(classify_permission(500, None, "X")[0], PERM_OTHER)
        self.assertEqual(classify_permission(-1, None, "X")[0], PERM_OTHER)

    def test_empty_perm_name_never_matches(self):
        kind, _, _ = classify_permission(200, auth_response(["ManageClients"]), "")
        self.assertEqual(kind, PERM_NO)


class ClassifyPermissions(unittest.TestCase):
    """Sistem Uyumu — token verilen yetkilerin HEPSİNE sahip mi?"""

    def test_all_present(self):
        kind, missing, count, _ = classify_permissions(200, auth_response(REQ4 + ["ViewCRM"]), REQ4)
        self.assertEqual(kind, COMPAT_ALL)
        self.assertEqual(missing, [])
        self.assertEqual(count, 5)

    def test_some_missing_reports_which(self):
        have = ["ViewMaskedPhone", "ManageClientMessage"]  # mail görme + mail gönderme yok
        kind, missing, _, _ = classify_permissions(200, auth_response(have), REQ4)
        self.assertEqual(kind, COMPAT_MISSING)
        self.assertEqual(missing, ["ViewClientEmail", "ManageClientEmail"])

    def test_case_insensitive(self):
        have = [p.lower() for p in REQ4]
        kind, missing, _, _ = classify_permissions(200, auth_response(have), REQ4)
        self.assertEqual(kind, COMPAT_ALL)
        self.assertEqual(missing, [])

    def test_invalid_and_rate(self):
        self.assertEqual(classify_permissions(401, None, REQ4)[0], COMPAT_INVALID)
        self.assertEqual(classify_permissions(429, None, REQ4)[0], COMPAT_RATE)

    def test_empty_required_is_invalid(self):
        self.assertEqual(classify_permissions(200, auth_response(REQ4), [])[0], COMPAT_INVALID)


class PhoneVerdict(unittest.TestCase):
    """GetClientById detay cevabındaki telefon tam mı maskeli mi."""

    def test_full_phone_is_acik(self):
        # Gerçek GetClientById şekli: Data.Phone tam numara.
        data = {"Data": {"Id": 1, "Phone": "905000000000", "MobilePhone": None}}
        verdict, sample = phone_verdict(data)
        self.assertEqual(verdict, "açık")
        self.assertEqual(sample, "905000000000")

    def test_masked_phone_is_maskeli(self):
        verdict, _ = phone_verdict({"Data": {"Phone": "****", "MobilePhone": "****"}})
        self.assertEqual(verdict, "maskeli")

    def test_partial_mask_is_maskeli(self):
        verdict, _ = phone_verdict({"Data": {"Phone": "0555*****67"}})
        self.assertEqual(verdict, "maskeli")

    def test_last4_visible_mask_is_maskeli(self):
        # Yetkisiz hesaplarda sık görülen biçim: son 4 hane açık, önü yıldızlı.
        verdict, _ = phone_verdict({"Data": {"Phone": "****4847"}})
        self.assertEqual(verdict, "maskeli")

    def test_no_phone_field(self):
        verdict, sample = phone_verdict({"Data": {"Id": 1}})
        self.assertEqual(verdict, "yok")
        self.assertEqual(sample, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
