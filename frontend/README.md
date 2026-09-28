# TezTaxiTop Mini App

React, TypeScript and Vite client for the existing Django REST API. Passenger and driver permissions come from `/api/v1/auth/me/`; both-role accounts can switch modes without changing their backend role.

## Run locally

1. Copy `.env.example` to `.env` and set `VITE_TELEGRAM_BOT_USERNAME` if the bot link should be shown.
2. Start Django at `http://127.0.0.1:8000`.
3. Run `npm install` and `npm run dev` in `frontend/`.
4. Open the Vite URL. The dev server proxies `/api` to Django; override `VITE_DJANGO_ORIGIN` if needed.

In Telegram, configure the public HTTPS URL in the root `.env` as `TELEGRAM_WEBAPP_URL`. The bot displays an “Ilovani ochish” Web App button during first-time phone onboarding and in its normal role menu. Set `VITE_API_BASE_URL` to the deployed API base when hosting the built app separately.

## Authentication boundary

The client reads Telegram Web App user data for display only. It does not treat the browser-provided Telegram ID or `initDataUnsafe` as proof of identity and never calls `/auth/register-telegram/` from the browser. That endpoint accepts a raw ID and is documented as safe only when the bot transport authenticates it.

The current backend has no Mini App `initData` verification/token-exchange endpoint, and the existing bot does not issue its DRF token to the Web App. Until a trusted backend exchange exists, an already-issued DRF token is required at the sign-in screen. Phone numbers are read-only in the client and must be shared with the Telegram bot using its contact request button.

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
