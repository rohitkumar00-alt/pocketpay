"""Local demo ledger. No payment network, real funds, or authentication.

Balances are integer paise. Every successful operation saves its balance changes
and receipt in one SQLite transaction. A request ID makes retrying safe.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


MAX_TRANSFER = 10_000_000  # INR 100,000.00, in paise
MAX_BALANCE = 100_000_000  # INR 1,000,000.00, in paise
MERCHANTS = (
    ("m_cafe", "Campus Cafe", "Food & drinks"),
    ("m_books", "Paper & Pages", "Books & stationery"),
    ("m_market", "Daily Market", "Groceries & essentials"),
)
RECEIPT_COLUMNS = (
    "id, kind, merchant_id, merchant_name, amount, note, created_at, "
    "customer_balance_after"
)


class WalletError(ValueError):
    """A validation or storage error that can be displayed to the user."""


def parse_amount(text: str) -> int:
    """Parse a positive decimal INR amount to paise, without floating point.

    Accept examples: '1', '1.5', '1.50'. Currency symbols, grouping separators,
    signs, exponent notation, and more than two decimal places are rejected.
    """
    if not isinstance(text, str):
        raise WalletError("Enter an amount using numbers, for example 150.00.")
    value = text.strip()
    if len(value) > 20 or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value):
        raise WalletError("Enter a valid amount with up to two decimal places.")
    whole, _, fraction = value.partition(".")
    amount = int(whole) * 100 + int(fraction.ljust(2, "0"))
    if amount <= 0:
        raise WalletError("Amount must be greater than zero.")
    if amount > MAX_TRANSFER:
        raise WalletError("Each demo transaction is limited to INR 100,000.00.")
    return amount


def format_money(amount: int) -> str:
    """Format integer paise as INR without a floating-point conversion."""
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise TypeError("Amount must be integer paise.")
    sign = "-" if amount < 0 else ""
    whole, paise = divmod(abs(amount), 100)
    return f"INR {sign}{whole:,}.{paise:02d}"


class WalletService:
    """One customer and three merchants sharing an on-device demo ledger.

    Create a separate instance per thread. The database serializes writers so
    concurrent service instances cannot spend the same money twice.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        try:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('customer', 'merchant')),
                    balance INTEGER NOT NULL DEFAULT 0
                        CHECK (typeof(balance) = 'integer'
                               AND balance BETWEEN 0 AND 100000000)
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE,
                    request_id TEXT NOT NULL UNIQUE,
                    fingerprint TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('topup', 'payment')),
                    merchant_id TEXT REFERENCES accounts(id),
                    merchant_name TEXT NOT NULL,
                    amount INTEGER NOT NULL CHECK (typeof(amount) = 'integer'
                                                  AND amount BETWEEN 1 AND 10000000),
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    customer_balance_after INTEGER NOT NULL
                        CHECK (customer_balance_after BETWEEN 0 AND 100000000)
                );
                CREATE INDEX IF NOT EXISTS merchant_transactions
                    ON transactions(merchant_id, sequence DESC);
                """
            )
            self._db.execute("BEGIN IMMEDIATE")
            self._db.execute(
                "INSERT OR IGNORE INTO accounts(id,name,category,kind) "
                "VALUES ('customer','My wallet','Demo customer','customer')"
            )
            self._db.executemany(
                "INSERT OR IGNORE INTO accounts(id,name,category,kind) "
                "VALUES (?, ?, ?, 'merchant')", MERCHANTS
            )
            self._db.commit()
        except sqlite3.Error:
            self._db.rollback()
            self._db.close()
            raise

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "WalletService":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def merchants(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT id,name,category,balance FROM accounts "
            "WHERE kind='merchant' ORDER BY name"
        ).fetchall()
        return [dict(row) for row in rows]

    def balance(self, account_id: str = "customer") -> int:
        row = self._db.execute(
            "SELECT balance FROM accounts WHERE id=?", (account_id,)
        ).fetchone()
        if row is None:
            raise WalletError("Wallet not found.")
        return row["balance"]

    def add_demo_money(self, amount_text: str, request_id: str) -> dict:
        return self._write("topup", None, parse_amount(amount_text), "", request_id)

    def pay(self, merchant_id: str, amount_text: str, note: str, request_id: str) -> dict:
        if not isinstance(merchant_id, str) or not merchant_id:
            raise WalletError("Choose a merchant before paying.")
        if not isinstance(note, str) or len(note) > 120:
            raise WalletError("Payment note must be 120 characters or fewer.")
        return self._write(
            "payment", merchant_id, parse_amount(amount_text), note.strip(), request_id
        )

    def history(self, account_id: str = "customer") -> list[dict]:
        self.balance(account_id)  # Reject unknown accounts, even with no history.
        if account_id == "customer":
            rows = self._db.execute(
                f"SELECT {RECEIPT_COLUMNS} FROM transactions ORDER BY sequence DESC"
            ).fetchall()
        else:
            rows = self._db.execute(
                f"SELECT {RECEIPT_COLUMNS} FROM transactions "
                "WHERE merchant_id=? ORDER BY sequence DESC", (account_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def receipt(self, transaction_id: str) -> dict:
        row = self._db.execute(
            f"SELECT {RECEIPT_COLUMNS} FROM transactions WHERE id=?", (transaction_id,)
        ).fetchone()
        if row is None:
            raise WalletError("Transaction not found.")
        return dict(row)

    def _write(self, kind: str, merchant_id: str | None, amount: int,
               note: str, request_id: str) -> dict:
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
            raise WalletError("A payment request ID between 1 and 128 characters is required.")
        fingerprint = json.dumps([kind, merchant_id, amount, note], separators=(",", ":"))
        try:
            self._db.execute("BEGIN IMMEDIATE")
            existing = self._db.execute(
                "SELECT id,fingerprint FROM transactions WHERE request_id=?", (request_id,)
            ).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise WalletError("This request ID was already used for a different transaction.")
                result = self.receipt(existing["id"])
                self._db.commit()
                return result

            customer_balance = self.balance()
            merchant_name = "Demo top-up"
            if kind == "topup":
                next_balance = customer_balance + amount
                if next_balance > MAX_BALANCE:
                    raise WalletError("The demo wallet balance limit is INR 1,000,000.00.")
            else:
                merchant = self._db.execute(
                    "SELECT name,balance FROM accounts WHERE id=? AND kind='merchant'",
                    (merchant_id,),
                ).fetchone()
                if merchant is None:
                    raise WalletError("Merchant not found. Choose a merchant from the list.")
                if amount > customer_balance:
                    raise WalletError("Not enough demo money. Add funds before paying.")
                if merchant["balance"] + amount > MAX_BALANCE:
                    raise WalletError("This merchant has reached the demo balance limit.")
                merchant_name = merchant["name"]
                next_balance = customer_balance - amount
                self._db.execute(
                    "UPDATE accounts SET balance=balance+? WHERE id=?", (amount, merchant_id)
                )

            self._db.execute(
                "UPDATE accounts SET balance=? WHERE id='customer'", (next_balance,)
            )
            result = {
                "id": "TX-" + uuid4().hex.upper(),
                "kind": kind,
                "merchant_id": merchant_id,
                "merchant_name": merchant_name,
                "amount": amount,
                "note": note,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                "customer_balance_after": next_balance,
            }
            self._db.execute(
                "INSERT INTO transactions (id,request_id,fingerprint,kind,merchant_id,"
                "merchant_name,amount,note,created_at,customer_balance_after) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (result["id"], request_id, fingerprint, kind, merchant_id, merchant_name,
                 amount, note, result["created_at"], next_balance),
            )
            self._db.commit()
            return result
        except WalletError:
            self._db.rollback()
            raise
        except sqlite3.Error as exc:
            self._db.rollback()
            raise WalletError("Could not save this transaction. Please retry.") from exc
