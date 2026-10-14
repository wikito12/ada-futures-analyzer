# Nano ADA Futures Signal Lab — iPhone edition

A mobile-friendly Streamlit web dashboard for Coinbase **monthly** Nano ADA futures. This is a research prototype, not a trading bot.

## Access from an iPhone without a computer

1. On your iPhone, sign in to GitHub in Safari and create a **private** repository. GitHub's mobile web interface may require switching to desktop website for file upload.
2. Upload `app.py` and `requirements.txt` from this package into the repository root using GitHub's **Add file → Upload files** interface. Do not upload API keys, credentials, account data or private trades.
3. Open https://share.streamlit.io/ in Safari and sign in. Choose **Create app** → **Deploy a public app from GitHub** (wording can vary), select your repository and `app.py`, then deploy. **Check Streamlit Community Cloud's current repository visibility and app privacy options before deploying. A private GitHub repository does not automatically mean the deployed app is private.** If private deployment is unavailable, do not enter sensitive data in the deployed app.
4. Open the generated HTTPS app URL on your iPhone. In Safari tap **Share → Add to Home Screen → Add**.
5. To use automatic prices, enter the exact Coinbase **monthly futures product ID**. The app attempts Coinbase's public Advanced Trade market endpoints and validates product metadata. This API route may not expose the monthly contract or candles; if verification fails, signals remain disabled. No spot/perpetual substitution occurs.

## Limitations

- Hosting requires a one-time deployment using web interfaces on the phone. The ZIP itself is not an installable iOS app, and no hosted URL is included.
- The automatic futures market-data integration is **unverified** for this contract. No API credentials are requested or stored. Coinbase's derivatives connectivity may require a different authenticated adapter and permissions.
- The app refreshes when interacted with; its data cache expires after 60 seconds. It does not continuously stream or push notifications.
- The current analyzer may include an unfinished most recent candle; the scores are not validated for live trading. This should be fixed before acting on signals.
- 1h and 4h agreement is required for an actionable dashboard signal. 5m/15m provide context.
- Assumes 1,000 ADA per contract; verify current contract rules with Coinbase. P/L excludes slippage, margin and liquidation risk.
- No orders are sent. Never paste exchange API secrets into the app.

## Local development (optional)

`pip install -r requirements.txt`

`streamlit run app.py`
