"""
フェーズ1: import_service の純粋関数に対するユニットテスト

DB接続不要で実行できるテストのみ含む。
"""
from app.services.import_service import _guess_account_type, _make_hash


class TestGuessAccountType:
    def test_cash(self):
        assert _guess_account_type("10_財布") == "cash"

    def test_bank(self):
        assert _guess_account_type("30_銀行") == "bank"

    def test_emoney(self):
        assert _guess_account_type("26_Suica") == "e-money"

    def test_card(self):
        assert _guess_account_type("40_クレジット") == "card"

    def test_other(self):
        assert _guess_account_type("99_不明") == "other"


class TestMakeHash:
    def test_returns_64_char_hex(self):
        h = _make_hash("2024-01-01", "食費/外食", "10_財布", "0", "1000", "ランチ")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_input_same_hash(self):
        args = ("2024-01-01", "食費/外食", "10_財布", "0", "1000", "ランチ")
        assert _make_hash(*args) == _make_hash(*args)

    def test_different_memo_different_hash(self):
        h1 = _make_hash("2024-01-01", "食費/外食", "10_財布", "0", "1000", "ランチ")
        h2 = _make_hash("2024-01-01", "食費/外食", "10_財布", "0", "1000", "ディナー")
        assert h1 != h2
