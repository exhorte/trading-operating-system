"""The one setting the launcher reads from MetaTrader's configuration file: whether expert advisors may run (ADR 0039 § 6). Nothing else of the file is returned or kept."""

from __future__ import annotations

from pathlib import Path

from trading_os.launcher.mt5.adapters import LocalMt5Files


def data_folder(root: Path, name: str, text: str, encoding: str = "utf-16") -> str:
    folder = root / name
    (folder / "config").mkdir(parents=True)
    (folder / "config" / "common.ini").write_text(text, encoding=encoding)
    return str(folder)


def test_enabled_one_is_true_and_zero_is_false(tmp_path: Path) -> None:
    files = LocalMt5Files()
    assert files.experts_enabled(data_folder(tmp_path, "a", "[Experts]\r\nEnabled=1\r\n")) is True
    assert files.experts_enabled(data_folder(tmp_path, "b", "[Experts]\r\nEnabled=0\r\n")) is False


def test_only_the_experts_section_counts(tmp_path: Path) -> None:
    text = "[Common]\r\nEnabled=1\r\n[Experts]\r\nAllowDllImport=1\r\n"
    assert LocalMt5Files().experts_enabled(data_folder(tmp_path, "c", text)) is None


def test_a_missing_or_unreadable_file_is_not_said(tmp_path: Path) -> None:
    assert LocalMt5Files().experts_enabled(str(tmp_path / "nowhere")) is None
    assert (
        LocalMt5Files().experts_enabled(data_folder(tmp_path, "d", "\x00\x01 not a configuration", "latin-1")) is None
    )


def test_utf8_is_read_too(tmp_path: Path) -> None:
    assert LocalMt5Files().experts_enabled(data_folder(tmp_path, "e", "[Experts]\nEnabled=1\n", "utf-8")) is True
