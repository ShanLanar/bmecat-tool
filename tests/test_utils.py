# tests/test_utils.py
"""Tests für lib/utils.py – run_7zip und glob_ci."""

import os
import sys
import tempfile
import pytest

# Projektpfad einfügen
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.utils import glob_ci, VERSION


class TestGlobCI:
    """Tests für case-insensitive Glob mit Deduplizierung."""

    def test_empty_directory(self, tmp_path):
        result = glob_ci(str(tmp_path), "jpg")
        assert result == []

    def test_finds_lowercase(self, tmp_path):
        (tmp_path / "image.jpg").touch()
        result = glob_ci(str(tmp_path), "jpg")
        assert len(result) == 1
        assert result[0].endswith("image.jpg")

    def test_finds_uppercase(self, tmp_path):
        (tmp_path / "IMAGE.JPG").touch()
        result = glob_ci(str(tmp_path), "jpg")
        assert len(result) == 1

    def test_no_duplicates(self, tmp_path):
        """Auf case-insensitiven FS (Windows) darf jede Datei nur 1× erscheinen."""
        (tmp_path / "test.jpg").touch()
        (tmp_path / "other.JPG").touch()
        result = glob_ci(str(tmp_path), "jpg")
        # Anzahl Dateien = Anzahl tatsächlicher Dateien (nicht 2×)
        filenames = [os.path.basename(f).lower() for f in result]
        assert len(filenames) == len(set(filenames))

    def test_sorted_output(self, tmp_path):
        (tmp_path / "c.jpg").touch()
        (tmp_path / "a.jpg").touch()
        (tmp_path / "b.jpg").touch()
        result = glob_ci(str(tmp_path), "jpg")
        basenames = [os.path.basename(f) for f in result]
        assert basenames == sorted(basenames)

    def test_extension_with_dot(self, tmp_path):
        (tmp_path / "file.xml").touch()
        result = glob_ci(str(tmp_path), ".xml")
        assert len(result) == 1

    def test_extension_without_dot(self, tmp_path):
        (tmp_path / "file.csv").touch()
        result = glob_ci(str(tmp_path), "csv")
        assert len(result) == 1

    def test_mixed_extensions_no_cross_match(self, tmp_path):
        (tmp_path / "data.csv").touch()
        (tmp_path / "data.xml").touch()
        result = glob_ci(str(tmp_path), "csv")
        assert len(result) == 1
        assert result[0].endswith(".csv")


class TestVersion:
    def test_version_format(self):
        """Version muss X.Y.Z Format haben."""
        parts = VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)


class TestXmlEscape:
    def test_ampersand(self):
        from lib.utils import xml_escape
        assert xml_escape("Clic & Go") == "Clic &amp; Go"

    def test_less_than(self):
        from lib.utils import xml_escape
        assert xml_escape("a < b") == "a &lt; b"

    def test_greater_than(self):
        from lib.utils import xml_escape
        assert xml_escape("a > b") == "a &gt; b"

    def test_quote(self):
        from lib.utils import xml_escape
        assert xml_escape('say "hello"') == "say &quot;hello&quot;"

    def test_combined(self):
        from lib.utils import xml_escape
        assert xml_escape('A & B < C > D "E"') == 'A &amp; B &lt; C &gt; D &quot;E&quot;'

    def test_no_special_chars(self):
        from lib.utils import xml_escape
        assert xml_escape("Leitz Ordner A4") == "Leitz Ordner A4"


class TestXmlFixAmpersands:
    def test_naked_ampersand(self):
        from lib.utils import xml_fix_ampersands
        assert xml_fix_ampersands("Clic & Go") == "Clic &amp; Go"

    def test_already_escaped(self):
        from lib.utils import xml_fix_ampersands
        assert xml_fix_ampersands("Clic &amp; Go") == "Clic &amp; Go"

    def test_mixed(self):
        from lib.utils import xml_fix_ampersands
        assert xml_fix_ampersands("A & B &amp; C") == "A &amp; B &amp; C"

    def test_preserves_entities(self):
        from lib.utils import xml_fix_ampersands
        text = "&lt;tag&gt; &amp; &quot;test&quot;"
        assert xml_fix_ampersands(text) == text

    def test_numeric_entity(self):
        from lib.utils import xml_fix_ampersands
        assert xml_fix_ampersands("&#169; & &#x00A9;") == "&#169; &amp; &#x00A9;"

    def test_no_double_escape(self):
        from lib.utils import xml_fix_ampersands
        # &amp; ist korrekt – darf nicht zu &amp;amp; werden
        assert xml_fix_ampersands("Beistell- &amp; Hänger") == "Beistell- &amp; Hänger"
        assert xml_fix_ampersands("A &amp; B & C") == "A &amp; B &amp; C"
