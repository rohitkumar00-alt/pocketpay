# PocketPay demo walkthrough

## Five-minute presentation

1. Start PocketPay. On a fresh installation the customer and all merchants have **INR 0.00**.
2. Add **1000.00** of demo money. Explain that this creates simulated funds locally and does not charge a card or bank account.
3. Open merchant payment, select **Campus Cafe**, enter **150.00**, and add the note `Lunch`.
4. Review the merchant and amount before confirming. The customer balance becomes **INR 850.00**.
5. Show the receipt and its transaction reference. Open customer history to show the top-up and payment.
6. Switch to the merchant view. Campus Cafe has received **INR 150.00**. Both roles use the same device and database.
7. Try paying **900.00** with the remaining INR 850.00. The app must reject the payment without changing balances.
8. Close and reopen PocketPay. Confirm the balances and transaction history remain.

The figures above assume fresh demo data. If you have already used the app, add the starting balances when checking the expected totals. On Android, clearing PocketPay's app storage starts a new demo and erases all its existing history.

## Android device checklist

The packaged APK has not yet been built and validated on a physical device. Record the APK filename, workflow run, phone model, Android version, and results when testing.

- [ ] The APK installs and opens on the intended arm64 device.
- [ ] The first launch starts at zero; demo-money labels are visible.
- [ ] Text, buttons, and amounts fit a small portrait display.
- [ ] The keyboard allows decimal amounts and does not prevent reaching the action button.
- [ ] Top-up, payment review, confirmation, receipt, history, and merchant view work.
- [ ] `0`, negative values, malformed amounts, and more than two decimals are rejected.
- [ ] Insufficient balance leaves both accounts and history unchanged.
- [ ] Cancelling before confirmation does not create a payment.
- [ ] Rapid repeated taps on confirmation do not create duplicate payments.
- [ ] Merchant selection shows the correct merchant's receipts and balance.
- [ ] Backgrounding, returning, closing, and reopening preserve saved transactions.
- [ ] The Android Back button behaves as expected across screens.
- [ ] The complete flow works in airplane mode.
- [ ] Force-closing during a payment leaves either the complete transaction or no transaction, without a partial debit/credit.

## What to explain in your project viva

- **Why Python/Kivy?** The same Python interface can run on a computer for development and be packaged for Android.
- **Why SQLite?** It persists this single-device demo without requiring a server.
- **How is money represented?** Integer paise: INR 150.00 is stored as `15000`.
- **How are repeated requests handled?** A request ID identifies an operation; repeating that operation returns its existing receipt.
- **Why does a payment not create money?** It subtracts from the customer and adds the same amount to the selected merchant in one database transaction.
- **What would production require?** A server-authoritative ledger, authenticated users, independent merchant accounts, a payment-provider integration, and operational/security work. This demo implements none of those services.

## Troubleshooting

| Problem | Next step |
| --- | --- |
| `No module named kivy` | Install `requirements.txt` using the same Python environment that launches `main.py`. |
| Linux reports no window provider | Use a graphical session, or install the CI graphical dependencies and run the smoke test with `xvfb-run`. |
| APK workflow fails | Open the first failing build step and inspect the first concrete error. The configured build has not yet been proven; do not call it deployed until it succeeds. |
| APK cannot update an older copy | Check the package/signature error. Separate debug builds can have different keys; uninstalling the old demo removes its local data. |
| APK does not install on an emulator | The supplied configuration builds arm64 only; an x86/x86_64 emulator needs a separately configured build. |
| Expected balance differs | Check existing history: the walkthrough assumes a fresh database. |
