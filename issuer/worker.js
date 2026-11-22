// ro pro 라이선스 발급기(Cloudflare Workers). docs/SITE-PLAN.md P3 + '자동 활성화'.
//   POST /polar/webhook  Polar order.paid → 서명 검사 → 오프라인 키(ro/license.py) 서명 → KV 보관 + 백업 메일
//   GET  /buy            ?plan=yearly|monthly[&i=<설치 토큰의 SHA-256 hex>] → Polar 결제 세션을 만들어 결제창으로 보낸다
//   POST /license        {"install": <설치 토큰>} → 그 Mac 몫의 최신 키(없으면 404). 앱이 이 Mac에서 다시 서명을 검사한다
//
// 비밀값(wrangler secret put, 저장소·로그 금지):
//   POLAR_WEBHOOK_SECRET  Polar 웹훅 비밀(whsec_…, 2026-09-08 이후 만든 Standard Webhooks 방식)
//   POLAR_ACCESS_TOKEN    Polar 조직 액세스 토큰(checkouts:write)
//   LICENSE_SEED_HEX      scripts/license-tool.py keygen이 만든 개인 시드(hex 64자)
//   RESEND_API_KEY        메일 발송
// 일반 설정(wrangler.toml [vars]): LICENSE_KID, MAIL_FROM, POLAR_PRODUCT_IDS, POLAR_API, POLAR_PRODUCT_YEARLY,
//   POLAR_PRODUCT_MONTHLY, SUCCESS_URL. KV 바인딩: LICENSES(없으면 메일만 보낸다)
//
// 설치 토큰 원본은 /license 요청 본문에만 온다(URL·로그·Polar에 안 남김). KV와 Polar에는 SHA-256만 둔다.
// 로그에는 웹훅 id·이벤트 종류·결과만 남긴다. 이메일 주소·키·토큰은 남기지 않는다(원칙 2).

const DOMAIN = new TextEncoder().encode("ro-license-v1\n");
const GRACE_SECONDS = 14 * 86400;   // 결제 기간 끝 + 14일 유예(기획서 '구독 + 오프라인 키 설계')
const TOLERANCE_SECONDS = 5 * 60;   // Standard Webhooks 권장 시각 허용 범위
const MAX_BODY = 256 * 1024;
const PKCS8_ED25519_PREFIX = "302e020100300506032b657004220420";
const HASH_RE = /^[0-9a-f]{64}$/;
const TOKEN_RE = /^[A-Za-z0-9_-]{43}$/;     // 32바이트 base64url(패딩 없음)
const KEEP_AFTER_EXP = 30 * 86400;          // 키가 만료된 뒤에도 30일은 KV에 둔다(늦게 켠 Mac)

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/polar/webhook") return webhook(request, env);
    if (request.method === "GET" && url.pathname === "/buy") return buy(url, env);
    if (request.method === "POST" && url.pathname === "/license") return fetchLicense(request, env);
    return new Response("not found", { status: 404 });
  },
};

async function webhook(request, env) {
    const body = await request.text();
    if (body.length > MAX_BODY) return new Response("too large", { status: 413 });
    const hookId = request.headers.get("webhook-id") || "";
    if (!(await verifyWebhook(request.headers, body, env.POLAR_WEBHOOK_SECRET))) {
      log(hookId, "-", "bad signature");
      return new Response("bad signature", { status: 401 });
    }
    let event;
    try { event = JSON.parse(body); } catch { return new Response("bad json", { status: 400 }); }
    const grant = extractGrant(event, env);
    if (!grant.ok) {
      // 다시 보내도 결과가 같으므로 2xx로 받는다(Polar는 실패 10번 연속이면 엔드포인트를 끈다). 필요하면 license-tool로 수동 발급
      log(hookId, event && event.type, grant.reason);
      return new Response(null, { status: 202 });
    }
    const key = await issueKey(grant, env);
    const kept = await keepForMac(env, grant, key);   // 앱이 스스로 받아 가게(같은 주문이면 같은 키라 다시 써도 같다)
    await sendKey(env, grant, key);   // 실패하면 예외 → 500 → Polar가 다시 보낸다(같은 주문이면 같은 키)
    log(hookId, event.type, kept ? "issued+kept" : "issued");
    return new Response(null, { status: 202 });
}

async function sha256Hex(text) {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", enc(text)));
  return [...d].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** 결제 → 그 Mac(설치 토큰 해시) 몫으로 KV에 둔다. 갱신 주문은 구독 id로 같은 Mac을 찾는다. */
async function keepForMac(env, grant, key) {
  if (!env.LICENSES) return false;
  let h = grant.install;
  if (!h && grant.subId) h = await env.LICENSES.get(`sub:${grant.subId}`);
  if (!h || !HASH_RE.test(h)) return false;
  const expiration = grant.exp + KEEP_AFTER_EXP;
  await env.LICENSES.put(`lic:${h}`, JSON.stringify({ key, exp: grant.exp }), { expiration });
  if (grant.subId) await env.LICENSES.put(`sub:${grant.subId}`, h, { expiration });
  return true;
}

/** 앱(또는 사이트 버튼)에서 온 구매 시작: 설치 토큰 해시를 붙인 Polar 결제 세션을 만들어 그리로 보낸다. */
export async function buy(url, env) {
  const plan = url.searchParams.get("plan");
  const product = plan === "yearly" ? env.POLAR_PRODUCT_YEARLY : plan === "monthly" ? env.POLAR_PRODUCT_MONTHLY : null;
  if (!product) return new Response("unknown plan", { status: 400 });
  const install = url.searchParams.get("i");
  if (install !== null && !HASH_RE.test(install)) return new Response("bad install", { status: 400 });
  if (!env.POLAR_ACCESS_TOKEN || !env.POLAR_API || !env.SUCCESS_URL) return new Response("not configured", { status: 503 });
  const body = { products: [product], success_url: env.SUCCESS_URL, allow_discount_codes: true };
  if (install) body.metadata = { ro_install: install };
  const res = await fetch(`${env.POLAR_API.replace(/\/$/, "")}/v1/checkouts/`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.POLAR_ACCESS_TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) { log("-", "buy", `polar ${res.status}`); return new Response("checkout unavailable", { status: 502 }); }
  const checkout = await res.json();
  if (typeof checkout.url !== "string" || !checkout.url.startsWith("https://")) return new Response("checkout unavailable", { status: 502 });
  return new Response(null, { status: 302, headers: { Location: checkout.url, "Cache-Control": "no-store" } });
}

/** 앱이 자기 몫의 최신 키를 받아 간다. 토큰 원본은 본문으로만 받고 해시로 찾는다. */
export async function fetchLicense(request, env) {
  const headers = { "Content-Type": "application/json", "Cache-Control": "no-store" };
  const raw = await request.text();
  if (raw.length > 1024) return new Response("{}", { status: 413, headers });
  let install;
  try { install = JSON.parse(raw).install; } catch { return new Response("{}", { status: 400, headers }); }
  if (typeof install !== "string" || !TOKEN_RE.test(install)) return new Response("{}", { status: 400, headers });
  if (!env.LICENSES) return new Response("{}", { status: 404, headers });
  const kept = await env.LICENSES.get(`lic:${await sha256Hex(install)}`);
  if (!kept) return new Response("{}", { status: 404, headers });
  const { key } = JSON.parse(kept);
  return new Response(JSON.stringify({ key }), { status: 200, headers });
}

function log(hookId, type, result) {
  console.log(JSON.stringify({ webhook: String(hookId).slice(0, 64), type: String(type).slice(0, 40), result }));
}

const enc = (s) => new TextEncoder().encode(s);

function b64decode(s) {
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}

function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function hexToBytes(hex) {
  if (typeof hex !== "string" || !/^[0-9a-fA-F]*$/.test(hex) || hex.length % 2) throw new Error("bad hex");
  return Uint8Array.from(hex.match(/../g) || [], (h) => parseInt(h, 16));
}

/** Standard Webhooks: HMAC-SHA256(base64(secret 뒷부분), "id.timestamp.body"), 헤더 "v1,<base64>"(공백으로 여러 개) */
export async function verifyWebhook(headers, body, secret, now = Date.now() / 1000) {
  const id = headers.get("webhook-id"), ts = headers.get("webhook-timestamp"), sigs = headers.get("webhook-signature");
  if (!id || !ts || !sigs || typeof secret !== "string" || !secret) return false;
  if (!/^\d{1,12}$/.test(ts) || Math.abs(now - Number(ts)) > TOLERANCE_SECONDS) return false;
  let keyBytes;
  try { keyBytes = b64decode(secret.startsWith("whsec_") ? secret.slice(6) : secret); } catch { return false; }
  if (!keyBytes.length) return false;
  const key = await crypto.subtle.importKey("raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
  const data = enc(`${id}.${ts}.${body}`);
  for (const part of sigs.split(" ")) {
    const comma = part.indexOf(",");
    if (comma < 0 || part.slice(0, comma) !== "v1") continue;
    let sig;
    try { sig = b64decode(part.slice(comma + 1)); } catch { continue; }
    if (await crypto.subtle.verify("HMAC", key, sig, data)) return true;   // 비교는 WebCrypto가 상수 시간으로
  }
  return false;
}

const toSeconds = (iso) => {
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
};

/**
 * order.paid 웹훅에서 발급에 필요한 값만 뽑는다. 첫 구독 결제와 갱신 결제 모두 order.paid가 온다.
 * 확인 필요(2026-11-19 공식 예시 페이로드를 못 열었다): data.customer.email, data.subscription.current_period_end,
 * data.subscription_id, data.product_id, data.created_at 경로. P3 완료 조건인 샌드박스 실제 웹훅으로 맞춘다.
 */
export function extractGrant(event, env = {}) {
  if (!event || event.type !== "order.paid" || !event.data || typeof event.data !== "object") {
    return { ok: false, reason: "ignored event" };
  }
  const o = event.data;
  const allowed = String(env.POLAR_PRODUCT_IDS || "").split(",").map((s) => s.trim()).filter(Boolean);
  const productId = o.product_id ?? (o.product && o.product.id);
  if (allowed.length && !allowed.includes(productId)) return { ok: false, reason: "other product" };
  const email = o.customer && o.customer.email;
  if (typeof email !== "string" || !/^[^\s@]+@[^\s@]+$/.test(email) || email.length > 320) {
    return { ok: false, reason: "no customer email" };
  }
  const subId = o.subscription_id ?? (o.subscription && o.subscription.id);
  const periodEnd = toSeconds(o.subscription && o.subscription.current_period_end);
  if (!subId || !periodEnd) return { ok: false, reason: "not a subscription order" };   // pro는 구독만 판다
  const iat = toSeconds(o.created_at) ?? toSeconds(event.timestamp) ?? Math.floor(Date.now() / 1000);
  // 결제 세션에 붙인 설치 토큰 해시(첫 결제). 갱신 주문엔 없을 수 있어 구독 id로도 찾는다(keepForMac)
  const tagged = (o.metadata && o.metadata.ro_install) || (o.subscription && o.subscription.metadata && o.subscription.metadata.ro_install);
  const install = typeof tagged === "string" && /^[0-9a-f]{64}$/.test(tagged) ? tagged : null;
  // iat·exp가 주문에서 정해지므로 같은 주문을 다시 받아도 같은 키가 나온다(Ed25519는 결정적 서명)
  return { ok: true, email, id: String(subId).slice(0, 128), subId: String(subId).slice(0, 128), install, iat, exp: periodEnd + GRACE_SECONDS };
}

/** ro/license.py encode와 같은 바이트: 키 정렬·공백 없는 JSON, 서명 = Ed25519(DOMAIN + payload) */
export async function issueKey({ id, iat, exp }, env) {
  const kid = env.LICENSE_KID;
  const seed = hexToBytes(env.LICENSE_SEED_HEX || "");
  if (!kid || seed.length !== 32) throw new Error("issuer is not configured");
  const payload = { exp, iat, id, kid, plan: "pro", v: 1 };   // 알파벳 순서(Python sort_keys와 같게)
  const body = enc(JSON.stringify(payload));
  const msg = new Uint8Array(DOMAIN.length + body.length);
  msg.set(DOMAIN);
  msg.set(body, DOMAIN.length);
  const pkcs8 = new Uint8Array([...hexToBytes(PKCS8_ED25519_PREFIX), ...seed]);
  const priv = await crypto.subtle.importKey("pkcs8", pkcs8, { name: "Ed25519" }, true, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("Ed25519", priv, msg));
  // 자기 검사: 개인 키에서 공개 키를 꺼내 방금 서명을 확인한다(시드 형식 실수로 틀린 키를 보내지 않게)
  const { x } = await crypto.subtle.exportKey("jwk", priv);
  const pub = await crypto.subtle.importKey("jwk", { kty: "OKP", crv: "Ed25519", x }, { name: "Ed25519" }, false, ["verify"]);
  if (!(await crypto.subtle.verify("Ed25519", pub, sig, msg))) throw new Error("self-check failed");
  return `RO1.${b64url(body)}.${b64url(sig)}`;
}

export function mailText(key, exp) {
  const until = new Date(exp * 1000).toISOString().slice(0, 10);
  return [
    "ro pro를 구매해 주셔서 고마워요. / Thanks for getting ro pro.",
    "",
    "라이선스 키 / License key:",
    key,
    "",
    `유효 기한 / Valid until: ${until} (구독이 갱신되면 새 키가 이메일로 와요 / a new key arrives when your subscription renews)`,
    "",
    "넣는 법: 메뉴 막대의 ro 아이콘 → 라이선스… → 붙여 넣기 → 키 저장 → 지금 ro 다시 시작",
    "How to use: ro menu bar icon → License… → paste → Save key → Restart ro now",
    "",
    "키는 이 Mac 안에서만 검사하고 인터넷으로 보내지 않아요. / The key is checked on your Mac only.",
  ].join("\n");
}

async function sendKey(env, grant, key) {
  if (!env.RESEND_API_KEY || !env.MAIL_FROM) throw new Error("mail is not configured");
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.RESEND_API_KEY}`,
      "Content-Type": "application/json",
      "Idempotency-Key": `ro-license-${grant.id}-${grant.exp}`,   // 웹훅 재전송으로 같은 메일이 여러 번 가지 않게
    },
    body: JSON.stringify({ from: env.MAIL_FROM, to: [grant.email], subject: "ro pro 라이선스 키 / License key", text: mailText(key, grant.exp) }),
  });
  if (!res.ok) throw new Error(`mail failed: ${res.status}`);
}
