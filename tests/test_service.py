"""Ledger behavior tests; run with python -m unittest discover -s tests -v."""

import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path

from wallet.service import MAX_BALANCE, WalletError, WalletService, format_money, parse_amount


class AmountTests(unittest.TestCase):
    def test_valid_amounts_are_integer_paise(self):
        for text, expected in [("1", 100), ("0.01", 1), ("12.5", 1250),
                               (" 12.50 ", 1250), ("100000.00", 10_000_000)]:
            with self.subTest(text=text):
                self.assertEqual(parse_amount(text), expected)
                self.assertIs(type(parse_amount(text)), int)

    def test_malformed_zero_negative_and_oversized_amounts_are_rejected(self):
        invalid = ["", " ", "0", "0.00", "-1", "+1", "1.001", "1e2", "NaN",
                   "Infinity", "1,000", "INR 10", ".50", "1.", "100000.01",
                   "9" * 1000, "١٢", "1\n2", None, 10, True]
        for text in invalid:
            with self.subTest(text=text):
                with self.assertRaises(WalletError):
                    parse_amount(text)

    def test_money_formatting_has_no_float_rounding(self):
        for amount, expected in [(0, "INR 0.00"), (1, "INR 0.01"),
                                 (123456, "INR 1,234.56"), (-105, "INR -1.05"),
                                 (100_000_000, "INR 1,000,000.00")]:
            self.assertEqual(format_money(amount), expected)
        with self.assertRaises(TypeError):
            format_money(1.1)


class WalletTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "wallet.sqlite3"
        self.wallet = WalletService(self.path)

    def tearDown(self):
        self.wallet.close()
        self.temp.cleanup()

    def fund(self, amount="1000", request_id="initial-funds"):
        return self.wallet.add_demo_money(amount, request_id)

    def test_new_wallet_is_empty_and_has_three_merchants(self):
        self.assertEqual(self.wallet.balance(), 0)
        self.assertEqual(self.wallet.history(), [])
        merchants = self.wallet.merchants()
        self.assertEqual({m["id"] for m in merchants}, {"m_cafe", "m_books", "m_market"})
        self.assertTrue(all(m["balance"] == 0 for m in merchants))

    def test_topup_creates_persistent_receipt(self):
        result = self.fund("123.45")
        self.assertEqual(self.wallet.balance(), 12345)
        self.assertEqual(result["kind"], "topup")
        self.assertIsNone(result["merchant_id"])
        self.assertEqual(result["amount"], 12345)
        self.assertEqual(result["customer_balance_after"], 12345)
        self.assertIsNotNone(datetime.fromisoformat(result["created_at"]).tzinfo)
        self.assertEqual(self.wallet.receipt(result["id"]), result)
        self.assertNotIn("request_id", result)

    def test_payment_debits_customer_credits_merchant_and_saves_note(self):
        self.fund()
        result = self.wallet.pay("m_cafe", "250.50", "  Lunch  ", "pay-1")
        self.assertEqual(result["kind"], "payment")
        self.assertEqual(result["merchant_name"], "Campus Cafe")
        self.assertEqual(result["note"], "Lunch")
        self.assertEqual(self.wallet.balance(), 74950)
        self.assertEqual(self.wallet.balance("m_cafe"), 25050)
        self.assertEqual(self.wallet.balance("m_books"), 0)
        self.assertEqual(self.wallet.balance() + sum(m["balance"] for m in self.wallet.merchants()), 100000)

    def test_can_spend_exact_balance(self):
        self.fund("0.01")
        self.wallet.pay("m_books", "0.01", "", "all-money")
        self.assertEqual(self.wallet.balance(), 0)
        self.assertEqual(self.wallet.balance("m_books"), 1)

    def test_insufficient_funds_do_not_change_balances_or_history(self):
        self.fund("10")
        before = self.wallet.history()
        with self.assertRaisesRegex(WalletError, "Not enough"):
            self.wallet.pay("m_cafe", "10.01", "", "too-much")
        self.assertEqual(self.wallet.balance(), 1000)
        self.assertEqual(self.wallet.balance("m_cafe"), 0)
        self.assertEqual(self.wallet.history(), before)

    def test_invalid_merchants_never_receive_money(self):
        self.fund()
        for merchant in ["missing", "customer", "m_cafe'; DROP TABLE accounts;--", "", None]:
            with self.subTest(merchant=merchant):
                with self.assertRaises(WalletError):
                    self.wallet.pay(merchant, "10", "", "invalid-merchant")
        self.assertEqual(self.wallet.balance(), 100000)
        self.assertEqual(len(self.wallet.history()), 1)

    def test_note_limit_is_enforced(self):
        self.fund()
        self.wallet.pay("m_cafe", "1", "x" * 120, "valid-note")
        for note in ["x" * 121, None, 12]:
            with self.assertRaises(WalletError):
                self.wallet.pay("m_cafe", "1", note, "bad-note")

    def test_invalid_request_ids_are_rejected(self):
        for request_id in ["", "  ", "x" * 129, None, 123]:
            with self.subTest(request_id=request_id):
                with self.assertRaises(WalletError):
                    self.wallet.add_demo_money("1", request_id)
        self.assertEqual(self.wallet.balance(), 0)

    def test_retrying_topup_is_idempotent(self):
        first = self.fund("10", "topup-key")
        retry = self.fund("10.00", "topup-key")
        self.assertEqual(first, retry)
        self.assertEqual(self.wallet.balance(), 1000)
        self.assertEqual(len(self.wallet.history()), 1)

    def test_retrying_payment_returns_original_receipt_even_after_later_changes(self):
        self.fund()
        first = self.wallet.pay("m_cafe", "100", "Lunch", "pay-key")
        self.wallet.pay("m_market", "50", "", "later-pay")
        retry = self.wallet.pay("m_cafe", "100.00", "Lunch", "pay-key")
        self.assertEqual(first, retry)
        self.assertEqual(retry["customer_balance_after"], 90000)
        self.assertEqual(self.wallet.balance(), 85000)
        self.assertEqual(self.wallet.balance("m_cafe"), 10000)
        self.assertEqual(len(self.wallet.history()), 3)

    def test_same_request_key_cannot_change_payment_details(self):
        self.fund()
        self.wallet.pay("m_cafe", "10", "Lunch", "same-key")
        for merchant, amount, note in [("m_books", "10", "Lunch"),
                                       ("m_cafe", "11", "Lunch"),
                                       ("m_cafe", "10", "Dinner")]:
            with self.assertRaisesRegex(WalletError, "different transaction"):
                self.wallet.pay(merchant, amount, note, "same-key")
        with self.assertRaises(WalletError):
            self.wallet.add_demo_money("10", "same-key")
        self.assertEqual(len(self.wallet.history()), 2)

    def test_failed_request_can_be_retried_after_adding_funds(self):
        with self.assertRaises(WalletError):
            self.wallet.pay("m_cafe", "20", "", "retry-later")
        self.fund("20")
        self.wallet.pay("m_cafe", "20", "", "retry-later")
        self.assertEqual(self.wallet.balance("m_cafe"), 2000)

    def test_history_is_newest_first_and_merchant_history_is_filtered(self):
        topup = self.fund()
        cafe = self.wallet.pay("m_cafe", "10", "", "cafe-pay")
        books = self.wallet.pay("m_books", "20", "", "books-pay")
        self.assertEqual(self.wallet.history(), [books, cafe, topup])
        self.assertEqual(self.wallet.history("m_cafe"), [cafe])
        self.assertEqual(self.wallet.history("m_books"), [books])
        self.assertEqual(self.wallet.history("m_market"), [])

    def test_unknown_accounts_and_receipts_raise_clear_errors(self):
        with self.assertRaises(WalletError):
            self.wallet.balance("unknown")
        with self.assertRaises(WalletError):
            self.wallet.history("unknown")
        with self.assertRaises(WalletError):
            self.wallet.receipt("unknown")

    def test_balances_history_and_idempotency_survive_reopening(self):
        self.fund()
        paid = self.wallet.pay("m_market", "34.56", "Bread", "saved-payment")
        self.wallet.close()
        self.wallet = WalletService(self.path)
        self.assertEqual(self.wallet.balance(), 96544)
        self.assertEqual(self.wallet.balance("m_market"), 3456)
        self.assertEqual(self.wallet.receipt(paid["id"]), paid)
        self.assertEqual(self.wallet.pay("m_market", "34.56", "Bread", "saved-payment"), paid)
        self.assertEqual(len(self.wallet.history()), 2)
        self.assertEqual(len(self.wallet.merchants()), 3)

    def test_balance_limit_cannot_be_exceeded_by_topup(self):
        for i in range(10):
            self.fund("100000", f"large-{i}")
        with self.assertRaisesRegex(WalletError, "balance limit"):
            self.fund("0.01", "overflow")
        self.assertEqual(self.wallet.balance(), MAX_BALANCE)
        self.assertEqual(len(self.wallet.history()), 10)

    def test_merchant_limit_rejection_preserves_customer_balance(self):
        for i in range(10):
            self.fund("100000", f"fund-{i}")
            self.wallet.pay("m_cafe", "100000", "", f"pay-{i}")
        self.fund("1", "extra-funds")
        with self.assertRaisesRegex(WalletError, "merchant has reached"):
            self.wallet.pay("m_cafe", "0.01", "", "merchant-overflow")
        self.assertEqual(self.wallet.balance(), 100)
        self.assertEqual(self.wallet.balance("m_cafe"), MAX_BALANCE)

    def test_receipt_storage_failure_rolls_back_both_balance_updates(self):
        self.fund()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("""
                CREATE TRIGGER reject_receipt BEFORE INSERT ON transactions
                BEGIN SELECT RAISE(ABORT, 'injected storage failure'); END;
            """)
        with self.assertRaisesRegex(WalletError, "Could not save"):
            self.wallet.pay("m_cafe", "100", "", "storage-retry")
        self.assertEqual(self.wallet.balance(), 100000)
        self.assertEqual(self.wallet.balance("m_cafe"), 0)
        self.assertEqual(len(self.wallet.history()), 1)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DROP TRIGGER reject_receipt")
        self.wallet.pay("m_cafe", "100", "", "storage-retry")
        self.assertEqual(self.wallet.balance(), 90000)

    def test_concurrent_payments_cannot_double_spend(self):
        self.fund("100")
        ready = threading.Barrier(2)

        def attempt(merchant):
            with WalletService(self.path) as wallet:
                ready.wait(timeout=10)
                try:
                    return wallet.pay(merchant, "80", "", f"concurrent-{merchant}")
                except WalletError as error:
                    return error

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, ["m_cafe", "m_books"]))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(sum(isinstance(result, WalletError) for result in results), 1)
        self.assertEqual(self.wallet.balance(), 2000)
        self.assertEqual(sum(m["balance"] for m in self.wallet.merchants()), 8000)
        self.assertEqual(len(self.wallet.history()), 2)

    def test_concurrent_identical_requests_create_only_one_payment(self):
        self.fund("100")
        ready = threading.Barrier(2)

        def attempt(_):
            with WalletService(self.path) as wallet:
                ready.wait(timeout=10)
                return wallet.pay("m_cafe", "80", "", "same-concurrent-key")

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.wallet.balance(), 2000)
        self.assertEqual(self.wallet.balance("m_cafe"), 8000)
        self.assertEqual(len(self.wallet.history()), 2)


if __name__ == "__main__":
    unittest.main()
