"""P3 발급기(issuer/worker.js)를 node에서 돌려, 웹훅 서명 검사와 'JS가 만든 키를 앱(Python)이 받아들이는지'를 본다."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ro import _ed25519, license

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "issuer" / "worker.js"
SEED = bytes(range(32))
PUB = _ed25519.public_key(SEED).hex()
NOW = 1_800_000_000

HARNESS = r"""
import { createHmac } from "node:crypto";
const worker = await import(process.argv[2]);
const cases = JSON.parse(process.argv[3]);
const out = [];
for (const c of cases) {
  const mails = [];
  globalThis.fetch = async (url, init) => {
    mails.push({ url, headers: init.headers, body: JSON.parse(init.body) });
    return new Response("{}", { status: c.mailStatus || 200 });
  };
  const logs = [];
  console.log = (s) => logs.push(s);
  const body = JSON.stringify(c.event);
  const secretKey = Buffer.from(c.secret.slice(6), "base64");
  const ts = String(c.ts);
  const sig = createHmac("sha256", c.signWith ? Buffer.from(c.signWith.slice(6), "base64") : secretKey)
    .update(`msg_1.${ts}.${c.tamper ? body + " " : body}`).digest("base64");
  const req = new Request("https://issuer.example/" + (c.path || "polar/webhook"), {
    method: c.method || "POST", body: c.method === "GET" ? undefined : body,
    headers: { "webhook-id": "msg_1", "webhook-timestamp": ts, "webhook-signature": `v1a,xx v1,${sig}` },
  });
  let status;
  try { status = (await worker.default.fetch(req, c.env)).status; } catch (e) { status = "throw:" + e.message; }
  out.push({ status, mails, logs });
}
process.stdout.write(JSON.stringify(out));
"""

SECRET = "whsec_" + "c2VjcmV0LWtleS1mb3ItdGVzdHMtb25seS0xMjM0NTY="
OTHER_SECRET = "whsec_" + "b3RoZXItc2VjcmV0LWtleS1mb3ItdGVzdHMtMTIzNDU="
ENV = {"POLAR_WEBHOOK_SECRET": SECRET, "LICENSE_SEED_HEX": SEED.hex(), "LICENSE_KID": "t1",
       "RESEND_API_KEY": "test-not-real", "MAIL_FROM": "ro <license@example.test>", "POLAR_PRODUCT_IDS": "prod_pro"}


def order(**over):
    data = {"id": "ord_1", "status": "paid", "billing_reason": "subscription_create", "product_id": "prod_pro",
            "subscription_id": "sub_1", "created_at": "2027-01-15T00:00:00Z",
            "customer": {"email": "buyer@example.test"},
            "subscription": {"id": "sub_1", "current_period_end": "2028-01-15T00:00:00Z"}}
    data.update(over)
    return {"type": "order.paid", "timestamp": "2027-01-15T00:00:01Z", "data": data}


@unittest.skipUnless(shutil.which("node"), "node 필요")
class IssuerTest(unittest.TestCase):
    def run_cases(self, cases):
        import time
        for c in cases:
            c.setdefault("secret", SECRET)
            c.setdefault("ts", int(time.time()))
            c.setdefault("env", ENV)
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "harness.mjs"
            h.write_text(HARNESS)
            r = subprocess.run(["node", str(h), WORKER.as_uri(), json.dumps(cases)],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_paid_order_mails_a_key_the_app_accepts(self):
        (res,) = self.run_cases([{"event": order()}])
        self.assertEqual(res["status"], 202)
        (mail,) = res["mails"]
        self.assertEqual(mail["url"], "https://api.resend.com/emails")
        self.assertEqual(mail["body"]["to"], ["buyer@example.test"])
        key = next(line for line in mail["body"]["text"].splitlines() if line.startswith("RO1."))
        p = license.parse(key, now=NOW, keys={"t1": PUB})
        exp = 1831507200 + 14 * 86400  # 2028-01-15 + 14일 유예
        self.assertEqual((p["id"], p["iat"], p["exp"], p["plan"]), ("sub_1", 1799971200, exp, "pro"))
        # 같은 payload면 Python 발급 도구와 바이트까지 같은 키(재전송해도 같은 키)
        self.assertEqual(key, license.encode({"v": 1, "kid": "t1", "id": "sub_1", "plan": "pro",
                                              "iat": 1799971200, "exp": exp}, SEED))
        self.assertEqual(mail["headers"]["Idempotency-Key"], f"ro-license-sub_1-{exp}")
        self.assertNotIn("buyer@example.test", json.dumps(res["logs"]))  # 로그에 이메일·키 없음
        self.assertNotIn(key.split(".")[2], json.dumps(res["logs"]))

    def test_rejects_bad_signatures(self):
        import time
        old = int(time.time()) - 3600
        res = self.run_cases([{"event": order(), "tamper": True}, {"event": order(), "signWith": OTHER_SECRET},
                              {"event": order(), "ts": old}, {"event": order(), "env": {**ENV, "POLAR_WEBHOOK_SECRET": ""}}])
        self.assertEqual([r["status"] for r in res], [401, 401, 401, 401])
        self.assertFalse(any(r["mails"] for r in res))

    def test_skips_without_mail_but_acknowledges(self):
        no_sub = order(subscription_id=None)
        no_sub["data"].pop("subscription")
        res = self.run_cases([
            {"event": {**order(), "type": "order.refunded"}},
            {"event": order(product_id="prod_other")},
            {"event": order(customer={})},
            {"event": no_sub},
        ])
        self.assertEqual([r["status"] for r in res], [202] * 4)
        self.assertFalse(any(r["mails"] for r in res))
        self.assertIn("other product", res[1]["logs"][0])

    def test_routing_and_failures_surface_for_retry(self):
        res = self.run_cases([
            {"event": order(), "path": "other"},
            {"event": order(), "method": "GET"},
            {"event": order(), "mailStatus": 500},
            {"event": order(), "env": {**ENV, "LICENSE_SEED_HEX": "abcd"}},
        ])
        self.assertEqual(res[0]["status"], 404)
        self.assertEqual(res[1]["status"], 404)
        self.assertTrue(str(res[2]["status"]).startswith("throw:mail failed"))      # Workers에서는 500 → Polar 재전송
        self.assertTrue(str(res[3]["status"]).startswith("throw:issuer is not configured"))
        self.assertFalse(res[3]["mails"])

    def test_no_secrets_in_repo_config(self):
        toml = (ROOT / "issuer" / "wrangler.toml").read_text()
        for name in ("POLAR_WEBHOOK_SECRET", "LICENSE_SEED_HEX", "RESEND_API_KEY"):
            self.assertNotIn(name, toml)


FLOW = r"""
import { createHmac, createHash } from "node:crypto";
const worker = await import(process.argv[2]);
const { env, steps } = JSON.parse(process.argv[3]);
const store = new Map();
env.LICENSES = {
  async get(k) { return store.has(k) ? store.get(k).v : null; },
  async put(k, v, o) { store.set(k, { v, exp: o && o.expiration }); },
};
const polar = [], mails = [];
globalThis.fetch = async (url, init) => {
  if (String(url).includes("/v1/checkouts/")) {
    polar.push({ url, auth: init.headers.Authorization, body: JSON.parse(init.body) });
    return new Response(JSON.stringify({ url: "https://sandbox.polar.sh/checkout/abc" }), { status: 201 });
  }
  mails.push(JSON.parse(init.body));
  return new Response("{}", { status: 200 });
};
console.log = () => {};
const out = [];
for (const s of steps) {
  let req;
  if (s.webhook) {
    const body = JSON.stringify(s.webhook), ts = String(Math.floor(Date.now() / 1000));
    const sig = createHmac("sha256", Buffer.from(env.POLAR_WEBHOOK_SECRET.slice(6), "base64")).update(`m.${ts}.${body}`).digest("base64");
    req = new Request("https://issuer.example/polar/webhook", { method: "POST", body,
      headers: { "webhook-id": "m", "webhook-timestamp": ts, "webhook-signature": `v1,${sig}` } });
  } else {
    req = new Request("https://issuer.example" + s.path, { method: s.method || "GET", body: s.body });
  }
  const res = await worker.default.fetch(req, env);
  out.push({ status: res.status, location: res.headers.get("Location"), body: await res.text() });
}
const hash = (t) => createHash("sha256").update(t).digest("hex");
process.stdout.write(JSON.stringify({ out, polar, mails: mails.length, keys: [...store.keys()],
  stored: Object.fromEntries([...store].map(([k, v]) => [k, v.exp])), hash: hash(steps.find((x) => x.token)?.token || "") }));
"""

TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_AbCdE"  # 43자 base64url(시험용)


@unittest.skipUnless(shutil.which("node"), "node 필요")
class AutoActivationTest(unittest.TestCase):
    """자동 활성화(docs/SITE-PLAN.md): 앱이 연 결제에 설치 토큰 해시를 붙이고, 결제 뒤 앱이 키를 받아 간다."""

    def flow(self, steps, **env_over):
        import hashlib
        env = {**ENV, "POLAR_ACCESS_TOKEN": "test-not-real", "POLAR_API": "https://sandbox-api.polar.sh/",
               "POLAR_PRODUCT_YEARLY": "prod_pro", "POLAR_PRODUCT_MONTHLY": "prod_pro_m",
               "SUCCESS_URL": "https://site.test/thanks/?checkout_id={CHECKOUT_ID}", **env_over}
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "flow.mjs"
            h.write_text(FLOW)
            r = subprocess.run(["node", str(h), WORKER.as_uri(), json.dumps({"env": env, "steps": steps})],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout)
        res["H"] = hashlib.sha256(TOKEN.encode()).hexdigest()
        return res

    def test_buy_then_app_picks_up_the_key_then_renewal_replaces_it(self):
        H = __import__("hashlib").sha256(TOKEN.encode()).hexdigest()
        first = order()
        first["data"]["metadata"] = {"ro_install": H}
        renewal = order(id="ord_2", billing_reason="subscription_cycle", created_at="2028-01-15T00:00:00Z",
                        subscription={"id": "sub_1", "current_period_end": "2029-01-15T00:00:00Z"})
        res = self.flow([
            {"path": "/license", "method": "POST", "body": json.dumps({"install": TOKEN}), "token": TOKEN},  # 사기 전엔 없음
            {"path": f"/buy?plan=yearly&i={H}"},
            {"webhook": first},
            {"path": "/license", "method": "POST", "body": json.dumps({"install": TOKEN})},
            {"webhook": renewal},  # 갱신 주문엔 메타데이터가 없어도 구독 id로 같은 Mac을 찾는다
            {"path": "/license", "method": "POST", "body": json.dumps({"install": TOKEN})},
        ])
        s = res["out"]
        self.assertEqual(s[0]["status"], 404)
        self.assertEqual((s[1]["status"], s[1]["location"]), (302, "https://sandbox.polar.sh/checkout/abc"))
        (call,) = res["polar"]
        self.assertEqual(call["url"], "https://sandbox-api.polar.sh/v1/checkouts/")
        self.assertEqual(call["body"]["metadata"], {"ro_install": H})        # 토큰 원본이 아니라 해시만 Polar로
        self.assertEqual(call["body"]["products"], ["prod_pro"])
        self.assertNotIn(TOKEN, json.dumps(call))
        k1 = json.loads(s[3]["body"])["key"]
        self.assertEqual(license.parse(k1, now=NOW, keys={"t1": PUB})["exp"], 1831507200 + 14 * 86400)
        k2 = json.loads(s[5]["body"])["key"]
        self.assertEqual(license.parse(k2, now=NOW, keys={"t1": PUB})["exp"], 1863129600 + 14 * 86400)
        self.assertEqual(res["mails"], 2)                                      # 백업 메일은 그대로
        self.assertEqual(sorted(res["keys"]), sorted([f"lic:{H}", "sub:sub_1"]))
        self.assertNotIn(TOKEN, json.dumps(res["keys"]))                      # KV에도 해시만

    def test_web_purchase_without_app_still_mails_and_keeps_nothing(self):
        res = self.flow([{"path": "/buy?plan=monthly"}, {"webhook": order()}])
        self.assertEqual(res["out"][0]["status"], 302)
        self.assertNotIn("metadata", res["polar"][0]["body"])
        self.assertEqual((res["mails"], res["keys"]), (1, []))

    def test_rejects_bad_requests(self):
        res = self.flow([
            {"path": "/buy?plan=lifetime"},
            {"path": "/buy?plan=yearly&i=not-a-hash"},
            {"path": "/license", "method": "POST", "body": "nope"},
            {"path": "/license", "method": "POST", "body": json.dumps({"install": "short"})},
            {"path": "/license", "method": "GET"},
            {"path": "/license", "method": "POST", "body": json.dumps({"install": TOKEN + "x" * 2000})},
        ])
        self.assertEqual([o["status"] for o in res["out"]], [400, 400, 400, 400, 404, 413])
        self.assertEqual(res["polar"], [])
        res = self.flow([{"path": "/buy?plan=yearly"}], POLAR_ACCESS_TOKEN="")
        self.assertEqual(res["out"][0]["status"], 503)


if __name__ == "__main__":
    unittest.main()
