#!/usr/bin/env bash
# Commercial release preflight check for ro-pet (mini + pro).
# Usage: ./scripts/release-preflight.sh [--strict]
#   Default: fails on code/security/test regressions; prints WARN for external account configs not yet filled.
#   --strict: also fails if commercial launch settings (issuer URL, site checkout URLs, legal drafts, Developer ID) are missing.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STRICT=0
[ "${1:-}" = "--strict" ] && STRICT=1

PASS=0
WARN=0
FAIL=0

ok()   { printf '\033[32m[PASS]\033[0m %s\n' "$*"; PASS=$((PASS + 1)); }
warn() { printf '\033[33m[WARN]\033[0m %s\n' "$*"; WARN=$((WARN + 1)); }
fail() { printf '\033[31m[FAIL]\033[0m %s\n' "$*"; FAIL=$((FAIL + 1)); }

cd "$ROOT"

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"
if printf '%s' "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  ok "pyproject.toml version: $VERSION"
else
  fail "pyproject.toml version invalid: ${VERSION:-empty}"
fi

if python3 -c "from ro import harden; assert not harden.network_offenders(), harden.network_offenders(); assert not harden.license_net_scoped(), harden.license_net_scoped()" 2>/dev/null; then
  ok "Network isolation & licensenet scope guard (ro/harden.py)"
else
  fail "Network isolation guard failed (ro/harden.py)"
fi

if grep -rn --exclude="release-preflight.sh" "rhochoi/ro\.bot" ro/ site/ issuer/ scripts/ install.sh README.md 2>/dev/null | head -n 5 | grep -q .; then
  fail "Private repo link (rhochoi/ro.bot) found in public release files"
else
  ok "No private repo (rhochoi/ro.bot) links in release files"
fi

if python3 -m pytest -q tests/test_license.py tests/test_issuer.py tests/test_site.py tests/test_harden.py tests/test_pet_edition.py tests/test_design_system.py tests/test_payment_ui.py tests/test_server.py >/dev/null 2>&1; then
  ok "Core release test suite (license, issuer, site, harden, edition, design, payment UI)"
else
  fail "Core release test suite failed — run pytest for details"
fi

# Commercial deployment configuration checks (WARN by default, FAIL with --strict)
check_live() {
  local label="$1" ok_cond="$2" hint="$3"
  if eval "$ok_cond"; then
    ok "$label"
  elif [ "$STRICT" = 1 ]; then
    fail "$label — $hint"
  else
    warn "$label — $hint"
  fi
}

check_live "In-app auto-checkout issuer URL (ro/licensenet.py or RO_LICENSE_ISSUER)" \
  'grep -qE "^ISSUER = \"https://" ro/licensenet.py || [ -n "${RO_LICENSE_ISSUER:-}" ]' \
  'Set ISSUER in ro/licensenet.py or pass RO_LICENSE_ISSUER=https://... at DMG build time'

check_live "Web checkout URLs (site/site-config.js)" \
  'grep -qE "yearly:[[:space:]]*\"https://" site/site-config.js && grep -qE "monthly:[[:space:]]*\"https://" site/site-config.js' \
  'Fill Polar checkout URLs in site/site-config.js'

check_live "Customer portal & support email (site/site-config.js)" \
  'grep -qE "portal:[[:space:]]*\"https://" site/site-config.js && grep -qE "support:[[:space:]]*\"[^\"@]+@[^\"]+\"" site/site-config.js' \
  'Fill portal URL and support email in site/site-config.js'

check_live "Cloudflare Worker issuer config (issuer/wrangler.toml)" \
  'grep -qE "^POLAR_PRODUCT_YEARLY = \"[^\"]+\"" issuer/wrangler.toml && grep -qE "^POLAR_PRODUCT_MONTHLY = \"[^\"]+\"" issuer/wrangler.toml && grep -qE "^MAIL_FROM = \"[^\"]+\"" issuer/wrangler.toml && grep -qE "^SUCCESS_URL = \"https://" issuer/wrangler.toml' \
  'Fill Polar product IDs, MAIL_FROM, SUCCESS_URL, and KV id in issuer/wrangler.toml'

check_live "Legal pages finalized (no Draft banner in site/terms & site/refund)" \
  '! grep -q "Nothing is for sale yet" site/terms/index.html site/refund/index.html' \
  'Review site/terms/index.html and site/refund/index.html and remove the Draft notice before launch'

if [ "$(uname -s)" = Darwin ]; then
  check_live "Apple Developer ID signing identity in keychain" \
    'security find-identity -v -p codesigning 2>/dev/null | grep -q "Developer ID Application:"' \
    'Install Developer ID Application certificate to sign and notarize DMG'
fi

echo ""
echo "Summary: PASS=$PASS WARN=$WARN FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
