# Changelog

## 1.0.0

First public release.

- Funnel described in one YAML file: steps, buttons (coloured, with custom emoji and copy buttons), questions with validation, reminders, consent screen, prices per currency.
- Payments: Telegram Stars, bank cards through a Telegram payment provider (with fiscal receipts), YooKassa payment links, Crypto Pay, manual transfer approved by a manager.
- After payment: time-limited access to a private channel or group through join requests (reminders, removal with retries, renewal), digital messages and files, manager requests.
- Funnel builder inside the admin panel: steps, coloured buttons, products with prices and gifts (private channel access, message and file, manager request), reminders, questions, payments and language switches, manager chat. Saved to `funnel.yaml`, validated before applying.
- Control panel with buttons inside Telegram: statistics, broadcasts with segments, payments and refunds, customer cards, give or take access, health check, reload.
- Russian and English for every message, Russian by default.
- `funnelbot setup`, `init`, `validate`, `preview`, `doctor`, `run`, `install-service`, `link`, `export`; one-command installer and Docker support.
