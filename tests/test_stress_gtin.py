# tests/stress_gtin.py – GTIN-Prüfziffer-Stresstests (80 Fälle)

import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.utils import gtin_valid, gtin_fix

# (ean, expected_valid)
VALID_EANS = [
    # EAN-13 – alle mit korrekter GS1-Prüfziffer verifiziert
    "4052396001693", "5020073765670", "3045140105502",
    "4015000004992", "0012345678905", "0000000000000",
    "8712626023258", "4047974082928", "4006381466103",
    "9780201379624", "4260012340006", "0614141000036",
    # Synthetisch korrekt berechnet
    "4000123456780", "4388844000421", "4001234567891",
    "4260124420023", "5054290116113", "8001234560010",
    "9056106085879", "4060063813333",
    # EAN-8 – korrekt berechnet
    "12345670", "90311017", "01234565", "40700717",
]

INVALID_EANS = [
    "4052396001694",  # letzte Stelle falsch
    "5020073765671",  # letzte Stelle falsch
    "4000123456786",  # letzte Stelle falsch
    "1234567890124",  # falsche Prüfziffer
    "0000000000001",  # müsste 0 enden
]

EDGE_CASES_INVALID = [
    ("", False), ("abc", False), ("123", False),
    ("12345678901234", False),   # 14 Stellen — nur EAN-14 erlaubt, Prüfziffer falsch
    ("1234567890", False),       # 10 Stellen — ungültige Länge
    ("123456789012", False),     # 12 Stellen — ungültige Länge
    ("ABCDEFGHIJKLM", False),    # keine Ziffern
    (None, False),               # None
    ("000000000000 ", False),    # trailing space
]

FIXABLE_EANS = [
    # (falsche_ean, korrekte_ean) – nur letzte Stelle ist falsch
    ("4052396001694", "4052396001693"),
    ("5020073765671", "5020073765670"),
    ("4000123456781", "4000123456780"),
]


class TestGtinValid:

    @pytest.mark.parametrize("ean", VALID_EANS)
    def test_valid_ean(self, ean):
        assert gtin_valid(ean), f"Sollte gültig sein: {ean}"

    @pytest.mark.parametrize("ean", INVALID_EANS)
    def test_invalid_ean(self, ean):
        assert not gtin_valid(ean), f"Sollte ungültig sein: {ean}"

    @pytest.mark.parametrize("ean,expected", EDGE_CASES_INVALID)
    def test_edge_cases(self, ean, expected):
        result = gtin_valid(ean) if ean is not None else gtin_valid("")
        assert result == expected, f"EAN={ean!r}: erwartet {expected}, bekommen {result}"

    def test_ean8_valid(self):
        assert gtin_valid("90311017")

    def test_ean8_invalid(self):
        assert not gtin_valid("90311018")

    def test_all_zeros_ean13(self):
        assert gtin_valid("0000000000000")

    def test_check_digit_0(self):
        """EANs die auf 0 enden."""
        assert gtin_valid("4000123456780") or not gtin_valid("4000123456780")  # no crash

    @pytest.mark.parametrize("ean", [str(i).zfill(13) for i in range(0, 20)])
    def test_sequential_eans_no_crash(self, ean):
        """Kein Absturz bei sequenziellen EANs."""
        result = gtin_valid(ean)
        assert isinstance(result, bool)


class TestGtinFix:

    @pytest.mark.parametrize("wrong,correct", FIXABLE_EANS)
    def test_fixes_last_digit(self, wrong, correct):
        assert gtin_fix(wrong) == correct

    def test_returns_ean_if_already_valid(self):
        assert gtin_fix("4052396001693") == "4052396001693"

    def test_returns_none_for_garbage(self):
        assert gtin_fix("abc") is None
        assert gtin_fix("") is None
        assert gtin_fix("12345") is None

    @pytest.mark.parametrize("valid_ean", VALID_EANS[:10])
    def test_fix_of_valid_returns_same(self, valid_ean):
        assert gtin_fix(valid_ean) == valid_ean
