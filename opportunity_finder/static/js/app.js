/* Amazon UK Opportunity Finder — progressive enhancement only.
   Every action also works without JavaScript; this adds the live estimate,
   confirm dialogs, bulk selection, toasts and small conveniences. */
(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (value === null || value === undefined || value === false) return;
      if (key === "class") node.className = value;
      else node.setAttribute(key, value === true ? "" : value);
    });
    children.flat().forEach((child) => {
      if (child === null || child === undefined || child === false) return;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    });
    return node;
  }

  /* ------------------------------------------------------------ toasts */
  function dismiss(toastEl) {
    toastEl.classList.add("hide");
    setTimeout(() => toastEl.remove(), 260);
  }

  function initToasts() {
    $$(".toast").forEach((t) => {
      const x = $(".toast-x", t);
      if (x) x.addEventListener("click", () => dismiss(t));
      if (!t.classList.contains("bad") && !t.classList.contains("warn")) setTimeout(() => dismiss(t), 6000);
    });
  }

  function toast(message, tone = "info") {
    const box = $(".toasts");
    if (!box) return;
    const x = el("button", { type: "button", class: "toast-x", "aria-label": "Dismiss message" }, "×");
    const t = el("div", { class: `toast ${tone}`, role: tone === "bad" ? "alert" : "status" }, el("p", {}, message), x);
    x.addEventListener("click", () => dismiss(t));
    box.append(t);
    setTimeout(() => dismiss(t), 6000);
  }

  /* --------------------------------------------------- confirm dialogs */
  function initConfirm() {
    const modal = $("#confirm-modal");
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-confirm]");
      if (!button || !button.form) return;
      if (button.dataset.confirmed === "1") return;
      event.preventDefault();
      const form = button.form;
      const proceed = () => {
        const field = form.querySelector('input[name="confirm"]');
        if (field) field.value = "yes";
        button.dataset.confirmed = "1";
        if (form.requestSubmit) form.requestSubmit(button);
        else button.click();
        setTimeout(() => { button.dataset.confirmed = ""; }, 1000);
      };
      if (!modal || typeof modal.showModal !== "function") {
        if (window.confirm(button.dataset.confirm)) proceed();
        return;
      }
      $("#confirm-text").textContent = button.dataset.confirm;
      $("#confirm-ok").textContent = button.dataset.confirmLabel || "Confirm";
      modal.returnValue = "";
      modal.addEventListener("close", () => { if (modal.returnValue === "confirm") proceed(); }, { once: true });
      modal.showModal();
      $("#confirm-ok").focus();
    });
  }

  /* ---------------------------------------------------- loading states */
  function initLoading() {
    document.addEventListener("submit", (event) => {
      const button = event.submitter;
      if (!button || !button.hasAttribute("data-loading") || event.defaultPrevented) return;
      setTimeout(() => button.classList.add("is-loading"), 0);
      setTimeout(() => button.classList.remove("is-loading"), 8000); // downloads don't navigate away
    });
    $$("a[data-loading]").forEach((link) => link.addEventListener("click", () => {
      link.classList.add("is-loading");
      setTimeout(() => link.classList.remove("is-loading"), 2500);
    }));
  }

  /* ---------------------------------------------------- bulk selection */
  function initBulk() {
    const form = $("[data-bulk]");
    if (!form) return;
    const boxes = $$('input[name="ids"]', form);
    const all = $("[data-select-all]", form);
    const bar = $("[data-bulkbar]", form);
    const label = $("[data-selected-count]", form);
    const update = () => {
      const n = boxes.filter((b) => b.checked).length;
      bar.classList.toggle("active", n > 0);
      label.textContent = n ? `${n} selected` : "Select products to act on several at once";
      if (all) {
        all.checked = n > 0 && n === boxes.length;
        all.indeterminate = n > 0 && n < boxes.length;
      }
    };
    boxes.forEach((b) => b.addEventListener("change", update));
    if (all) all.addEventListener("change", () => { boxes.forEach((b) => { b.checked = all.checked; }); update(); });
    form.addEventListener("submit", (event) => {
      if (!boxes.some((b) => b.checked)) {
        event.preventDefault();
        toast("Select at least one product first.", "warn");
      }
    });
    update();
  }

  /* ------------------------------------------------- price candidates */
  function initCandidates() {
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-set-field]");
      if (!button) return;
      const input = document.getElementById(`f-${button.dataset.setField}`);
      if (!input) return;
      input.value = button.dataset.value;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      $$(`[data-set-field="${button.dataset.setField}"]`).forEach((b) => b.classList.toggle("on", b === button));
      input.focus();
    });
  }

  /* ------------------------------------------------------ live preview */
  const HEADINGS = {
    qualified: "Why it qualifies",
    rejected: "Why it would be rejected",
    incomplete: "Still needed",
    needs_verification: "Check before buying",
    high_risk: "Why the risk is high",
  };

  function kvRow(label, value, extraClass) {
    return [el("dt", { class: extraClass || null }, label), el("dd", { class: extraClass || null }, value)];
  }

  function renderPreview(body, data) {
    const badge = el("span", { class: `badge ${data.tone} lg` }, el("span", { class: "sym", "aria-hidden": "true" }, data.symbol), data.status_label);
    const score = data.score === null
      ? el("span", { class: "score none" }, "No score yet")
      : el("span", { class: "score", title: "Opportunity Score" }, el("b", {}, data.score), el("small", {}, "/100"));
    const riskBadge = el("span", { class: `badge ${{ LOW: "ok", MEDIUM: "warn", HIGH: "bad" }[data.risk.level]}` }, `${data.risk.level.charAt(0)}${data.risk.level.slice(1).toLowerCase()} risk`);

    const profitValue = el("span", { class: data.profit.net_negative ? "neg" : null }, data.profit.net);
    const dl = el("dl", { class: "kv" },
      kvRow("Referral fee", data.fees.referral),
      kvRow(`FBA fee${data.fees.tier ? ` · ${data.fees.tier}` : ""}`, data.fees.fba),
      kvRow("Surcharges, DSF & VAT", data.fees.other),
      kvRow("Total Amazon fees", data.fees.total),
      [el("dt", { class: "total" }, "Net profit / unit"), el("dd", { class: "total" }, profitValue)],
    );
    const dl2 = el("dl", { class: "kv mt-sm" },
      kvRow("ROI", data.profit.roi),
      kvRow("Net margin", data.profit.margin),
      kvRow("Capture rate", data.profit.capture),
      kvRow("Conservative units / month", data.profit.units),
      kvRow("Conservative profit / month", data.profit.conservative),
      kvRow("Theoretical profit / month", data.profit.theoretical),
      kvRow("Max sourcing price for your rules", data.profit.max_sourcing),
    );

    const parts = [el("div", { class: "status-line" }, badge, score), el("div", { class: "row tight" }, riskBadge), dl, dl2];
    if (data.summary.length) {
      parts.push(el("h3", { class: "section-title" }, HEADINGS[data.status] || "Details"));
      parts.push(el("ul", { class: "reasons" }, data.summary.map((line) => el("li", {}, line))));
    }
    if (data.fees.warnings.length) {
      parts.push(el("div", { class: "notice warn mt-sm small" }, el("div", {}, data.fees.warnings.join(" "))));
    }
    const errorCount = Object.keys(data.errors || {}).length;
    if (errorCount) {
      parts.push(el("p", { class: "msg error" }, `${errorCount} field${errorCount === 1 ? "" : "s"} can't be read yet — they are left out of this estimate.`));
    }
    body.replaceChildren(...parts);
  }

  function initLivePreview() {
    const form = $("[data-product-form]");
    const panel = $("[data-live-preview]");
    if (!form || !panel || !window.fetch) return;
    const body = $("[data-live-body]", panel);
    let timer = null;
    let seq = 0;
    const run = async () => {
      const mine = ++seq;
      panel.classList.add("loading");
      try {
        const response = await fetch("/api/preview", {
          method: "POST", body: new FormData(form), credentials: "same-origin", headers: { "X-CSRF-Token": csrf() },
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (mine === seq) renderPreview(body, data);
      } catch (err) {
        if (mine === seq) body.replaceChildren(el("p", { class: "muted small" }, "The live estimate isn't available right now — you can still save the product."));
      } finally {
        if (mine === seq) panel.classList.remove("loading");
      }
    };
    const schedule = () => { clearTimeout(timer); timer = setTimeout(run, 350); };
    form.addEventListener("input", schedule);
    form.addEventListener("change", schedule);
    run();
  }

  /* ---------------------------------------------------- unsaved changes */
  function initDirtyWarning() {
    const form = $("[data-product-form]");
    if (!form) return;
    let dirty = false;
    form.addEventListener("input", (event) => { if (event.isTrusted) dirty = true; });
    form.addEventListener("submit", () => { dirty = false; });
    window.addEventListener("beforeunload", (event) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    });
  }

  /* ------------------------------------------------------------ uploads */
  function initDropzones() {
    $$(".drop").forEach((zone) => {
      const input = $("input[type=file]", zone);
      const name = $(".file-name", zone);
      if (!input) return;
      const show = () => {
        const file = input.files && input.files[0];
        zone.classList.toggle("has", Boolean(file));
        if (name) name.textContent = file ? `${file.name} · ${Math.max(1, Math.round(file.size / 1024))} KB` : "";
      };
      input.addEventListener("change", show);
      ["dragenter", "dragover"].forEach((type) => zone.addEventListener(type, () => zone.classList.add("drag")));
      ["dragleave", "drop"].forEach((type) => zone.addEventListener(type, () => zone.classList.remove("drag")));
      show();
    });
  }

  /* ----------------------------------------------- import row filtering */
  function initRowFilter() {
    const group = $("[data-row-filter]");
    if (!group) return;
    const rows = $$("[data-action-row]");
    group.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-filter]");
      if (!button) return;
      const filter = button.dataset.filter;
      $$("button[data-filter]", group).forEach((b) => {
        b.classList.toggle("on", b === button);
        b.setAttribute("aria-pressed", String(b === button));
      });
      rows.forEach((row) => { row.hidden = filter !== "all" && row.dataset.actionRow !== filter; });
    });
  }

  /* ------------------------------------------- brand research progress */
  function initResearchProgress() {
    const card = $("[data-research-progress]");
    if (!card || card.hidden || !window.fetch) return;
    const set = (key, value) => $$(`[data-p="${key}"]`, card).forEach((el) => { el.textContent = value; });
    const poll = async () => {
      try {
        const response = await fetch(card.dataset.url, { credentials: "same-origin" });
        if (!response.ok) throw new Error(String(response.status));
        const data = await response.json();
        set("status_label", data.status_label);
        set("message", data.message);
        set("done", data.done);
        set("total", data.total);
        Object.entries(data.counts).forEach(([k, v]) => set(`counts.${k}`, v));
        const bar = $("[data-p-bar]", card);
        if (bar) bar.style.width = `${data.percent}%`;
        if (data.finished) {
          window.location.reload();
          return;
        }
      } catch (err) {
        set("message", "Checking progress… (the analysis keeps running)");
      }
      setTimeout(poll, 2000);
    };
    setTimeout(poll, 1500);
  }

  /* ----------------------------------------- auto-refresh import preview */
  function initAutoSubmit() {
    $$("[data-autosubmit]").forEach((control) => control.addEventListener("change", () => {
      const form = control.form;
      const refresh = form && form.querySelector("[data-refresh]");
      if (!refresh) return;
      refresh.classList.add("is-loading");
      if (form.requestSubmit) form.requestSubmit(refresh);
      else refresh.click();
    }));
  }

  /* -------------------------------------------------------------- focus */
  function initFocus() {
    const target = $("[data-error-summary]") || $("[data-focus-me]");
    if (!target) return;
    target.scrollIntoView({ block: "center" });
    target.focus({ preventScroll: true });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initToasts();
    initConfirm();
    initLoading();
    initBulk();
    initCandidates();
    initLivePreview();
    initDirtyWarning();
    initDropzones();
    initRowFilter();
    initAutoSubmit();
    initResearchProgress();
    initFocus();
  });

  window.AOF = { toast };
})();
