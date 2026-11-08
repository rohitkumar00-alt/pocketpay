"""PocketPay: an offline Android wallet demonstration. No real money."""

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from kivy.config import Config
from kivy.utils import platform

if platform not in ("android", "ios"):
    Config.set("graphics", "width", "430")
    Config.set("graphics", "height", "820")
Config.set("input", "mouse", "mouse,disable_multitouch")

from kivy.app import App
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from wallet.service import WalletError, WalletService, format_money, parse_amount

NAVY = (0.055, 0.09, 0.15, 1)
PAPER = (0.95, 0.96, 0.945, 1)
WHITE = (1, 1, 1, 1)
INK = (0.09, 0.14, 0.19, 1)
MUTED = (0.37, 0.43, 0.47, 1)
TEAL = (0.02, 0.43, 0.36, 1)
MINT = (0.75, 0.94, 0.83, 1)
PALE = (0.89, 0.94, 0.91, 1)
RED = (0.7, 0.16, 0.18, 1)


class Surface(BoxLayout):
    def __init__(self, color=WHITE, **kwargs):
        super().__init__(orientation="vertical", size_hint_y=None,
                         padding=dp(20), spacing=dp(10), **kwargs)
        self.bind(minimum_height=self.setter("height"))
        with self.canvas.before:
            Color(*color)
            self.shape = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(20)])
        self.bind(pos=self._resize, size=self._resize)

    def _resize(self, *_):
        self.shape.pos, self.shape.size = self.pos, self.size


class Action(Button):
    def __init__(self, text, callback, secondary=False, **kwargs):
        super().__init__(text=text, size_hint_y=None, height=dp(50),
                         background_normal="", background_down="",
                         background_color=(0, 0, 0, 0),
                         color=TEAL if secondary else WHITE,
                         font_size=dp(14), bold=True, **kwargs)
        self.fill = PALE if secondary else TEAL
        with self.canvas.before:
            self.paint = Color(*self.fill)
            self.shape = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(12)])
        self.bind(pos=self._resize, size=self._resize, state=self._state)
        self.bind(on_release=lambda *_: callback())

    def _resize(self, *_):
        self.shape.pos, self.shape.size = self.pos, self.size

    def _state(self, *_):
        self.paint.rgba = tuple(c * 0.85 for c in self.fill[:3]) + (1,) if self.state == "down" else self.fill


def label(text, size=14, color=INK, bold=False):
    item = Label(text=text, font_size=dp(size), color=color, bold=bold,
                 size_hint_y=None, height=dp(22), halign="left", valign="middle")
    item.bind(width=lambda obj, value: setattr(obj, "text_size", (value, None)))
    item.bind(texture_size=lambda obj, value: setattr(obj, "height", max(dp(22), value[1] + dp(4))))
    return item


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%d %b %Y, %I:%M %p")


class PocketPayApp(App):
    title = "PocketPay | Demo wallet"

    def build(self):
        Window.clearcolor = PAPER
        Window.softinput_mode = "below_target"
        Window.bind(on_keyboard=self.on_keyboard)
        folder = Path(os.environ.get("POCKETPAY_DATA_DIR") or self.user_data_dir)
        folder.mkdir(parents=True, exist_ok=True)
        self.store = WalletService(str(folder / "wallet.sqlite3"))
        self.selected_merchant = "m_cafe"
        self.pay_draft = {}
        self.request_id = None
        self.page = "home"
        self.controls = {}
        self.shell = BoxLayout(orientation="vertical")
        with self.shell.canvas.before:
            Color(*PAPER)
            self.background = RoundedRectangle(pos=self.shell.pos, size=self.shell.size, radius=[0])
        self.shell.bind(pos=self.resize_background, size=self.resize_background)
        self.render("home")
        return self.shell

    def resize_background(self, *_):
        self.background.pos, self.background.size = self.shell.pos, self.shell.size

    def on_stop(self):
        self.store.close()

    def on_pause(self):
        return True

    def on_resume(self):
        if self.page in ("home", "history", "merchant"):
            self.render(self.page)

    def on_keyboard(self, _window, key, *_):
        if key == 27 and self.page != "home":
            self.render("pay" if self.page == "review" else "home")
            return True
        return False

    def render(self, page, receipt=None):
        self.page = page
        self.controls = {}
        self.shell.clear_widgets()
        header = BoxLayout(size_hint_y=None, height=dp(76), padding=[dp(22), dp(16)], spacing=dp(12))
        header.add_widget(label("pocketpay", 25, TEAL, True))
        badge = label("DEMO WALLET", 10, MUTED, True)
        badge.size_hint_x = 0.55
        badge.halign = "right"
        header.add_widget(badge)
        self.shell.add_widget(header)
        scroll = ScrollView(do_scroll_x=False)
        self.body = BoxLayout(orientation="vertical", size_hint_y=None,
                              padding=[dp(20), dp(2), dp(20), dp(22)], spacing=dp(16))
        self.body.bind(minimum_height=self.body.setter("height"))
        scroll.add_widget(self.body)
        self.shell.add_widget(scroll)
        getattr(self, "show_" + page)(receipt) if page == "receipt" else getattr(self, "show_" + page)()
        navigation = BoxLayout(size_hint_y=None, height=dp(66), spacing=dp(5), padding=[dp(12), dp(8)])
        for title, target in [("Wallet", "home"), ("Pay", "pay"), ("Activity", "history"), ("Merchant", "merchant")]:
            selected = page == target or (target == "pay" and page == "review")
            button = Action(title, lambda t=target: self.begin_payment() if t == "pay" else self.render(t), secondary=not selected)
            button.height = dp(48)
            navigation.add_widget(button)
            self.controls["nav_" + target] = button
        self.shell.add_widget(navigation)

    def heading(self, title, subtitle):
        self.body.add_widget(label(title, 27, INK, True))
        self.body.add_widget(label(subtitle, 13, MUTED))

    def card(self, color=WHITE):
        card = Surface(color=color)
        self.body.add_widget(card)
        return card

    def button(self, parent, key, text, callback, secondary=False):
        button = Action(text, callback, secondary)
        parent.add_widget(button)
        self.controls[key] = button
        return button

    def field(self, parent, key, hint, value="", numeric=False):
        item = TextInput(text=value, hint_text=hint, multiline=False, size_hint_y=None,
                         height=dp(52), padding=[dp(12), dp(14)], font_size=dp(16),
                         foreground_color=INK, cursor_color=TEAL, background_normal="",
                         background_active="", background_color=PAPER,
                         # Kivy's Android number keyboard omits the decimal flag.
                         input_type="text", keyboard_suggestions=not numeric, write_tab=False)
        parent.add_widget(item)
        self.controls[key] = item
        return item

    def error_label(self, parent):
        self.error = label("", 13, RED)
        parent.add_widget(self.error)

    def show_home(self):
        self.heading("Your everyday wallet.", "One place to pay, track and keep things simple.")
        card = self.card(NAVY)
        card.add_widget(label("AVAILABLE DEMO BALANCE", 11, MINT, True))
        card.add_widget(label(format_money(self.store.balance()), 34, WHITE, True))
        card.add_widget(label("Personal wallet  /  INR", 13, (0.69, 0.75, 0.8, 1)))
        self.button(card, "add_money", "+  Add demo money", self.begin_topup)
        row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(12))
        self.body.add_widget(row)
        self.button(row, "pay_merchant", "Pay a merchant", self.begin_payment)
        self.button(row, "view_activity", "View activity", lambda: self.render("history"), True)
        self.body.add_widget(label("RECENT ACTIVITY", 11, MUTED, True))
        items = self.store.history()[:3]
        if items:
            for item in items:
                self.transaction_row(item)
        else:
            card = self.card()
            card.add_widget(label("Your first payment starts here", 17, INK, True))
            card.add_widget(label("Add demo money, choose a merchant, then review and confirm your payment.", 14, MUTED))
        self.body.add_widget(label("Practice money only. No bank account or real payment is connected.", 12, MUTED))

    def begin_topup(self):
        self.request_id = uuid4().hex
        self.render("topup")

    def show_topup(self):
        self.heading("Add demo money", "Try the full payment flow with simulated funds.")
        card = self.card()
        card.add_widget(label("Amount in INR", 13, MUTED, True))
        amount = self.field(card, "topup_amount", "e.g. 1000.00", numeric=True)
        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        card.add_widget(row)
        for value in (500, 1000, 2000):
            self.button(row, "preset_" + str(value), str(value), lambda v=value: setattr(amount, "text", str(v)), True)
        card.add_widget(label("Up to INR 100,000 per top-up. This does not charge a bank account.", 13, MUTED))
        self.error_label(card)
        self.button(card, "confirm_topup", "Add to demo wallet", self.topup)
        self.button(card, "cancel", "Cancel", lambda: self.render("home"), True)

    def topup(self):
        if self.page != "topup":
            return
        button = self.controls["confirm_topup"]
        if button.disabled:
            return
        button.disabled = True
        try:
            receipt = self.store.add_demo_money(self.controls["topup_amount"].text, self.request_id)
        except (WalletError, sqlite3.Error) as exc:
            button.disabled = False
            self.report_error(exc)
            return
        self.render("receipt", receipt)

    def begin_payment(self):
        self.pay_draft = {}
        self.request_id = uuid4().hex
        self.render("pay")

    def show_pay(self):
        self.heading("Pay a merchant", "Choose who to pay. You’ll review before sending.")
        card = self.card()
        card.add_widget(label("Available: " + format_money(self.store.balance()), 14, TEAL, True))
        card.add_widget(label("Merchant", 13, MUTED, True))
        self.merchant_names = {m["name"]: m["id"] for m in self.store.merchants()}
        spinner = Spinner(text=self.pay_draft.get("merchant_name", "Choose a merchant"),
                          values=tuple(self.merchant_names), size_hint_y=None, height=dp(52),
                          background_normal="", background_color=TEAL, color=WHITE, font_size=dp(15))
        card.add_widget(spinner)
        self.controls["merchant"] = spinner
        card.add_widget(label("Amount in INR", 13, MUTED, True))
        self.field(card, "amount", "0.00", self.pay_draft.get("amount", ""), True)
        card.add_widget(label("Note (optional, up to 120 characters)", 12, MUTED))
        self.field(card, "note", "What’s it for?", self.pay_draft.get("note", ""))
        self.error_label(card)
        self.button(card, "review", "Review payment", self.review_payment)
        self.button(card, "cancel", "Cancel", lambda: self.render("home"), True)
        self.body.add_widget(label("All merchants are sample businesses on this device.", 12, MUTED))

    def review_payment(self):
        name = self.controls["merchant"].text
        amount = self.controls["amount"].text.strip()
        note = self.controls["note"].text.strip()
        try:
            if name not in self.merchant_names:
                raise WalletError("Choose a merchant to continue.")
            units = parse_amount(amount)
            if units > self.store.balance():
                raise WalletError("Not enough demo money. Add funds from your wallet.")
            if len(note) > 120:
                raise WalletError("Keep your note to 120 characters or fewer.")
        except WalletError as exc:
            self.report_error(exc)
            return
        self.pay_draft = dict(merchant_name=name, merchant_id=self.merchant_names[name], amount=amount, note=note)
        self.render("review")

    def show_review(self):
        self.heading("Review your payment", "Nothing moves until you confirm.")
        card = self.card(NAVY)
        card.add_widget(label("YOU’RE PAYING", 11, MINT, True))
        card.add_widget(label(format_money(parse_amount(self.pay_draft["amount"])), 34, WHITE, True))
        card.add_widget(label("to " + self.pay_draft["merchant_name"], 18, WHITE))
        details = self.card()
        details.add_widget(label("Merchant ID: " + self.pay_draft["merchant_id"], 13, MUTED))
        details.add_widget(label("Note: " + (self.pay_draft["note"] or "No note"), 14))
        details.add_widget(label("Fee: INR 0.00", 14))
        after = self.store.balance() - parse_amount(self.pay_draft["amount"])
        details.add_widget(label("Balance after payment: " + format_money(after), 14, TEAL, True))
        self.error_label(details)
        self.button(details, "confirm_payment", "Confirm demo payment", self.confirm_payment)
        self.button(details, "edit_payment", "Back to edit", lambda: self.render("pay"), True)

    def confirm_payment(self):
        if self.page != "review":
            return
        button = self.controls["confirm_payment"]
        if button.disabled:
            return
        button.disabled = True
        try:
            draft = self.pay_draft
            receipt = self.store.pay(draft["merchant_id"], draft["amount"], draft["note"], self.request_id)
        except (WalletError, sqlite3.Error) as exc:
            button.disabled = False
            self.report_error(exc)
            return
        self.render("receipt", receipt)

    def report_error(self, exc):
        self.error.text = str(exc) if isinstance(exc, WalletError) else "Could not save this transaction. Please try again."

    def show_receipt(self, receipt):
        self.last_receipt = receipt
        is_topup = receipt["kind"] == "topup"
        self.heading("Money added" if is_topup else "Payment complete", "Saved to your wallet activity.")
        card = self.card()
        card.add_widget(label("SUCCESSFUL  /  DEMO", 11, TEAL, True))
        card.add_widget(label(format_money(receipt["amount"]), 34, INK, True))
        card.add_widget(label("Demo wallet top-up" if is_topup else receipt["merchant_name"], 19, INK, True))
        card.add_widget(label(timestamp(receipt["created_at"]), 13, MUTED))
        if receipt["note"]:
            card.add_widget(label(receipt["note"], 14))
        card.add_widget(label("Transaction reference", 12, MUTED))
        card.add_widget(label(receipt["id"], 12, INK, True))
        card.add_widget(label("Balance after transaction\n" + format_money(receipt["customer_balance_after"]), 15, TEAL, True))
        self.button(card, "done", "Back to wallet", lambda: self.render("home"))
        if not is_topup:
            self.button(card, "merchant_receipt", "See merchant’s balance", lambda: self.open_merchant(receipt["merchant_id"]), True)
        self.body.add_widget(label("This receipt records a simulated transaction on this device.", 12, MUTED))

    def transaction_row(self, item, merchant=False):
        card = self.card()
        title = "Demo money added" if item["kind"] == "topup" else item["merchant_name"]
        card.add_widget(label(title, 16, INK, True))
        incoming = merchant or item["kind"] == "topup"
        card.add_widget(label(("+ " if incoming else "- ") + format_money(item["amount"]), 20, TEAL if incoming else INK, True))
        card.add_widget(label(timestamp(item["created_at"]), 12, MUTED))
        self.button(card, "receipt_" + item["id"], "View receipt", lambda: self.render("receipt", self.store.receipt(item["id"])), True)

    def show_history(self):
        self.heading("Wallet activity", "Your saved top-ups and merchant payments.")
        items = self.store.history()
        if not items:
            self.card().add_widget(label("No transactions yet. Add demo funds to get started.", 15, MUTED))
        for item in items:
            self.transaction_row(item)

    def open_merchant(self, merchant_id):
        self.selected_merchant = merchant_id
        self.render("merchant")

    def show_merchant(self):
        self.heading("Merchant desk", "See the other side of every demo payment.")
        merchants = self.store.merchants()
        names = {m["name"]: m["id"] for m in merchants}
        merchant = next(m for m in merchants if m["id"] == self.selected_merchant)
        spinner = Spinner(text=merchant["name"], values=tuple(names), size_hint_y=None,
                          height=dp(52), background_normal="", background_color=TEAL, color=WHITE)
        spinner.bind(text=lambda _obj, text: self.open_merchant(names[text]) if names[text] != self.selected_merchant else None)
        self.body.add_widget(spinner)
        self.controls["merchant_switch"] = spinner
        card = self.card(NAVY)
        card.add_widget(label("TOTAL DEMO RECEIVED", 11, MINT, True))
        card.add_widget(label(format_money(merchant["balance"]), 34, WHITE, True))
        card.add_widget(label(merchant["id"] + "  /  " + merchant["category"], 13, WHITE))
        self.body.add_widget(label("RECEIVED PAYMENTS", 11, MUTED, True))
        history = self.store.history(self.selected_merchant)
        if not history:
            self.card().add_widget(label("No payments yet. Pay this merchant from the customer wallet.", 15, MUTED))
        for item in history:
            self.transaction_row(item, merchant=True)
        self.body.add_widget(label("Demo role switch. Both views share local data; separate phones do not sync.", 12, MUTED))


if __name__ == "__main__":
    PocketPayApp().run()
