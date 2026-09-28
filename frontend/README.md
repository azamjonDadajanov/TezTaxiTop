# TezTaxiTop Mini App

React, TypeScript and Vite client for the existing Django REST API. Passenger and driver permissions come from `/api/v1/auth/me/`; both-role accounts can switch modes without changing their backend role.

## Run locally

1. Copy `.env.example` to `.env` and set `VITE_TELEGRAM_BOT_USERNAME` if the bot link should be shown.
2. Start Django at `http://127.0.0.1:8000`.
3. Run `npm install` and `npm run dev` in `frontend/`.
4. Open the Vite URL. The dev server proxies `/api` to Django; override `VITE_DJANGO_ORIGIN` if needed.

In Telegram, configure the public HTTPS URL in the root `.env` as `TELEGRAM_WEBAPP_URL`. The bot sets Telegram's persistent menu button and sends an inline Web App button on `/start`; inline launch supplies signed Mini App `initData`. Reply-keyboard Web App buttons are intentionally not used for login because that launch type may not provide signed user data. For Netlify, set `VITE_API_BASE_URL` to the public Django API URL ending in `/api/v1` and add the exact Netlify origin to Django's `CORS_ALLOWED_ORIGINS` (for example, `https://willowy-horse-e714d8.netlify.app`). CORS is allowlisted; do not use `*` in production.

## Authentication

On launch, the client submits the raw `Telegram.WebApp.initData` string to `/api/v1/auth/telegram-mini-app/`. Django verifies Telegram's HMAC using the bot token, checks the `auth_date`, and only then creates/loads the account and returns its DRF token. `initDataUnsafe.user` is used only for display; the server never trusts it. The legacy `/auth/register-telegram/` path now requires the same signed `init_data` payload and no longer accepts a raw Telegram ID.

Phone numbers are read-only in the client and are not set by Mini App authentication. Users must share their contact through the Telegram bot's contact-request button.

## Build

Run `npm run build` to type-check and create `dist/`.
# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
