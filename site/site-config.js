// Values that come from accounts we have not opened yet. Fill them in before the sales launch (docs/SITE-PLAN.md P4·P5).
// Empty value = the page shows a "coming soon" state instead of a broken link.
window.RO_SITE = {
  checkout: {
    yearly: "https://buy.polar.sh/polar_cl_wAHSgJJpSs01cUeVPL8Wnw4QbIvw1GByW2fne2L7r38",
    monthly: "https://buy.polar.sh/polar_cl_Gr2zKkigE4Yq9qOaYuNCWqIBKvcBOKIDtghji2oWmfn",
  },
  portal: "https://polar.sh/robot/portal",
  support: "support@getropet.com",
};

(function () {
  const cfg = window.RO_SITE;
  const ok = (u) => typeof u === "string" && /^https:\/\//.test(u);
  function apply() {
    document.querySelectorAll("[data-checkout]").forEach((a) => {
      const url = cfg.checkout[a.dataset.checkout];
      if (!ok(url)) return;   // stays "Coming soon"
      a.href = url;
      a.removeAttribute("aria-disabled");
      a.textContent = a.dataset.label || a.textContent;
    });
    document.querySelectorAll("[data-portal]").forEach((el) => {
      if (ok(cfg.portal)) { el.href = cfg.portal; el.hidden = false; }
    });
    document.querySelectorAll("[data-support]").forEach((el) => {
      if (cfg.support) { el.href = "mailto:" + cfg.support; el.textContent = cfg.support; }
    });
  }
  window.RO_SITE_APPLY = apply;   // tests fill the config and call this again
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", apply);
  else apply();
})();
