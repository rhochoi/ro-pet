# ro Commercial Release & Deployment Checklist

This checklist covers everything required to ship **ro** (`mini` free + `pro` paid) to real customers.

## 1. Local Code & Security Gate (Automated)

Run the preflight script:

```bash
./scripts/release-preflight.sh
```

Before going live with real payments, run in strict mode (every check must be `[PASS]`):

```bash
./scripts/release-preflight.sh --strict
```

## 2. Payment Provider & License Issuer Setup (External Accounts)

### 2.1 Polar (Merchant of Record)
1. Create a Polar organization and complete identity/payout verification.
2. Create two recurring products in Sandbox first, then Production:
   - **ro pro — Yearly**: `$24 / year` (optional early-supporter discount code for `$19` first year)
   - **ro pro — Monthly**: `$3 / month`
3. Create Checkout Links for both products with Success URL:
   `https://<your-domain>/thanks/?checkout_id={CHECKOUT_ID}`
4. Create an organization access token (`checkouts:write`) and a Webhook endpoint pointing to:
   `https://<your-issuer-domain>/polar/webhook` (subscribe to `order.paid`).

### 2.2 Email Delivery (Resend)
1. Verify your sending domain in Resend (SPF/DKIM DNS records).
2. Create a sending API key and choose `MAIL_FROM`, e.g. `ro <license@yourdomain.com>`.

### 2.3 Cloudflare Worker (`issuer/`)
1. Generate or locate your Ed25519 private seed matching `ro/license.py` `PUBLIC_KEYS["ro1"]` (never commit or log the private seed):
   ```bash
   python3 scripts/license-tool.py keygen   # only if rotating to a new kid (e.g. ro2)
   ```
2. Create the KV namespace for automatic in-app license pickup:
   ```bash
   cd issuer
   npx wrangler kv namespace create LICENSES
   ```
3. Fill `issuer/wrangler.toml`:
   - `POLAR_API = "https://api.polar.sh"` (use `https://sandbox-api.polar.sh` while testing)
   - `POLAR_PRODUCT_YEARLY`, `POLAR_PRODUCT_MONTHLY`, `POLAR_PRODUCT_IDS`
   - `MAIL_FROM`, `SUCCESS_URL`
   - Uncomment `[[kv_namespaces]]` and paste the KV `id`
4. Store secrets in Cloudflare (never in git):
   ```bash
   npx wrangler secret put POLAR_WEBHOOK_SECRET
   npx wrangler secret put POLAR_ACCESS_TOKEN
   npx wrangler secret put LICENSE_SEED_HEX
   npx wrangler secret put RESEND_API_KEY
   ```
5. Deploy Worker and bind custom domain (e.g. `https://license.yourdomain.com`):
   ```bash
   npx wrangler deploy
   ```

## 3. Website & Legal Finalization (`site/`)

1. Update `site/site-config.js`:
   - `checkout.yearly` / `checkout.monthly`: keep **empty**. Checkout starts inside ro (Get pro…) so the purchase carries the install ID and pro turns on by itself; a web purchase would only email a key, and the app has no key field.
   - `portal`: Polar customer portal URL (`https://...`)
   - `support`: real support email address
2. Review and finalize legal copy:
   - Remove the `<p class="draft">...</p>` notice from `site/terms/index.html` and `site/refund/index.html`.
   - Confirm seller/entity details and refund terms match Polar's requirements.
3. Deploy `site/`:
   - Enable GitHub Pages (`Settings → Pages → Source: GitHub Actions`) for `.github/workflows/pages.yml`, or connect `site/` to Cloudflare Pages with your custom domain.

## 4. App Wiring, Signing, Notarization & Sparkle Release

1. Wire the production issuer URL either by setting `ISSUER = "https://license.yourdomain.com"` in `ro/licensenet.py` or by passing `RO_LICENSE_ISSUER` at DMG build time.
2. Confirm Apple Developer ID certificate and notarytool keychain profile exist on the build Mac:
   ```bash
   security find-identity -v -p codesigning
   xcrun notarytool store-credentials "ro-notary" --apple-id "<APPLE_ID>" --team-id "<TEAM_ID>" --password "<APP_SPECIFIC_PASSWORD>"
   ```
3. Build, sign, notarize, and staple the commercial DMG:
   ```bash
   APP_VERSION=<version> \
     SIGN_IDENTITY="Developer ID Application: youngrok choi (RX7H5VV65U)" \
     NOTARY_PROFILE=ro-notary \
     RO_LICENSE_ISSUER="https://license.yourdomain.com" \
     ./scripts/build-dmg.sh
   ```
4. Generate the Sparkle `appcast.xml` (do not modify the DMG afterward):
   ```bash
   ./scripts/make-appcast.sh build/ro-pet-<version>.dmg
   ```
5. Verify Gatekeeper acceptance:
   ```bash
   spctl --assess --type open --context context:primary-signature -v build/ro-pet-<version>.dmg
   ```
6. Publish the GitHub Release (include a fixed-name `ro-pet.dmg` copy so direct download links always serve the latest notarized DMG):
   ```bash
   cp build/ro-pet-<version>.dmg build/ro-pet.dmg
   gh release create v<version> build/ro-pet-<version>.dmg build/ro-pet.dmg build/appcast.xml \
     --repo rhochoi/ro-pet --title "ro v<version>" \
     --notes "Apple Silicon (macOS 13+). Free mini desktop pet + ro pro licensing and in-app checkout."
   rm -f build/ro-pet.dmg
   ```

## 5. End-to-End Smoke Test Before Public Announcement

1. Download `ro-pet-<version>.dmg` on a clean Mac (or separate user account) and open without Gatekeeper errors.
2. Confirm `mini` mode opens cleanly, pet panel shows **Upgrade to Pro** / **License**.
3. Run a Polar sandbox purchase from **Upgrade to Pro** → verify browser opens checkout → webhook issues `RO1.` key → email arrives → ro auto-activates Pro and restarts into Pro mode.
4. Confirm the **License** tab shows status, the restart bar, and **Get my key automatically** only — there is no key paste or remove (keys arrive only through checkout auto-activation).
5. Test `⌥R` file search (including OCR on a screenshot/PDF without `swiftc` on PATH) and Downloads organize preview + undo.
