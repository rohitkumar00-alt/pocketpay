"""Exercise real Kivy buttons with temporary data and optionally save screenshots.

Run from the project root: python tests/ui_smoke.py
Linux CI: xvfb-run -a python tests/ui_smoke.py
"""

import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
temporary = tempfile.TemporaryDirectory(prefix="pocketpay-ui-")
os.environ["POCKETPAY_DATA_DIR"] = temporary.name
os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_FILELOG", "1")
os.environ.setdefault("KIVY_HOME", str(Path(temporary.name) / "kivy"))

from main import PocketPayApp
from kivy.clock import Clock
from kivy.core.window import Window

app = PocketPayApp()
errors = []
screenshots = os.environ.get("POCKETPAY_SCREENSHOTS")


def tap(key):
    app.controls[key].dispatch("on_release")


def capture(name):
    if screenshots:
        folder = Path(screenshots).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        app.root.export_to_png(str(folder / (name + ".png")))


def exercise():
    assert app.store.balance() == 0
    yield
    tap("add_money")
    app.controls["topup_amount"].text = "0"
    tap("confirm_topup")
    assert app.page == "topup" and app.error.text
    app.controls["topup_amount"].text = "1000"
    topup_button = app.controls["confirm_topup"]
    topup_button.dispatch("on_release")
    topup_button.dispatch("on_release")
    assert app.page == "receipt" and app.store.balance() == 100000
    tap("done")
    tap("pay_merchant")
    tap("review")
    assert app.page == "pay" and "merchant" in app.error.text
    app.controls["merchant"].text = "Campus Cafe"
    app.controls["amount"].text = "1200"
    tap("review")
    assert app.page == "pay" and "Not enough" in app.error.text
    app.controls["amount"].text = "150.25"
    app.controls["note"].text = "Coffee and lunch"
    yield
    capture("pay")
    tap("review")
    assert app.page == "review" and app.store.balance() == 100000
    tap("edit_payment")
    assert app.controls["amount"].text == "150.25"
    tap("review")
    yield
    capture("review")
    payment_button = app.controls["confirm_payment"]
    payment_button.dispatch("on_release")
    payment_button.dispatch("on_release")
    assert app.page == "receipt"
    assert app.store.balance() == 84975
    assert app.store.balance("m_cafe") == 15025
    payment_id = app.last_receipt["id"]
    yield
    capture("receipt")
    tap("merchant_receipt")
    assert app.page == "merchant" and app.selected_merchant == "m_cafe"
    yield
    capture("merchant")
    app.controls["merchant_switch"].text = "Daily Market"
    assert app.selected_merchant == "m_market"
    tap("nav_history")
    assert "receipt_" + payment_id in app.controls
    tap("receipt_" + payment_id)
    assert app.last_receipt["id"] == payment_id
    tap("done")
    yield
    capture("home")
    tap("pay_merchant")
    app.controls["merchant"].text = "Campus Cafe"
    app.controls["amount"].text = "50"
    tap("review")
    app.on_keyboard(Window, 27)
    assert app.page == "pay" and app.store.balance() == 84975
    tap("cancel")
    assert len(app.store.history()) == 2
    # Reopen the actual database and check persistence through the UI store.
    from wallet.service import WalletService
    with WalletService(str(Path(temporary.name) / "wallet.sqlite3")) as reopened:
        assert reopened.balance() == 84975 and len(reopened.history()) == 2
    Window.size = (360, 640)
    yield
    capture("compact")
    print("UI smoke passed: top-up, validation, review/edit/cancel, payment, receipt, merchant switch, history and persistence.")


steps = exercise()


def advance(_dt):
    try:
        next(steps)
        Clock.schedule_once(advance, 0.35)
    except StopIteration:
        app.stop()
    except Exception:
        errors.append(traceback.format_exc())
        app.stop()


Clock.schedule_once(advance, 0.6)
try:
    app.run()
finally:
    temporary.cleanup()
if errors:
    print(errors[0], file=sys.stderr)
    sys.exit(1)
