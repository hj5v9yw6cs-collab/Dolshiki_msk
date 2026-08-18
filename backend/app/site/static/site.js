/**
 * Публичный сайт: тема, форма заявки, высота встроенного калькулятора.
 * Заявка уходит в тот же кабинет, что и заявки из калькулятора.
 */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // --- тема ------------------------------------------------------------------

  var toggle = $("theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var explicit = document.documentElement.getAttribute("data-theme");
      var isDark = explicit
        ? explicit === "dark"
        : window.matchMedia("(prefers-color-scheme: dark)").matches;
      var next = isDark ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("calc-theme", next); } catch (e) {}

      // Калькулятор — отдельный документ и сам о смене темы не узнает.
      var embedded = document.getElementById("calc-frame");
      if (embedded && embedded.contentWindow) {
        embedded.contentWindow.postMessage({ type: "garant-calc-theme", theme: next }, "*");
      }
    });
  }

  // --- высота встроенного калькулятора --------------------------------------

  var frame = $("calc-frame");
  if (frame) {
    window.addEventListener("message", function (event) {
      if (event.source !== frame.contentWindow) return;
      var data = event.data;
      if (!data || data.type !== "garant-calc-height") return;
      var height = parseInt(data.height, 10);
      if (height > 0) frame.style.height = height + 24 + "px";
    });
  }

  // --- форма заявки ----------------------------------------------------------

  var form = $("lead-form");
  if (!form) return;

  function setError(id, message) {
    var node = document.querySelector('[data-error-for="' + id + '"]');
    if (node) node.textContent = message;
    return false;
  }

  function clearErrors() {
    Array.prototype.forEach.call(form.querySelectorAll("[data-error-for]"), function (node) {
      node.textContent = "";
    });
    $("lead-status").innerHTML = "";
  }

  function digits(value) { return String(value || "").replace(/[^\d]/g, ""); }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    clearErrors();

    var name = $("l-name").value.trim();
    var phone = $("l-phone").value.trim();
    var ok = true;
    if (name.length < 2) ok = setError("l-name", "Укажите, как к вам обращаться");
    if (digits(phone).length < 10) ok = setError("l-phone", "Укажите телефон");
    if (!$("l-consent").checked) ok = setError("l-consent", "Без согласия мы не можем принять заявку");
    if (!ok) return;

    var button = $("lead-submit");
    button.disabled = true;
    button.textContent = "Отправляем…";

    fetch("/api/v1/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name,
        phone: phone,
        topic: form.dataset.topic || "neustoyka",
        region: form.dataset.region || null,
        project: $("l-project").value.trim() || null,
        consent: true,
        consent_policy_version: "1.0",
        page_url: window.location.href,
        source: "site",
        website: $("l-site").value
      })
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok) throw new Error(body.detail || "Не удалось отправить заявку");
        return body;
      });
    }).then(function () {
      form.querySelectorAll(".field, .consent, button").forEach(function (node) { node.hidden = true; });
      $("lead-status").innerHTML =
        '<div class="form-note form-note--ok"><b>Заявка отправлена.</b> ' +
        "Юрист свяжется с вами в течение рабочего дня.</div>";
    }).catch(function (error) {
      $("lead-status").innerHTML =
        '<div class="form-note form-note--error">' + esc(error.message) + "</div>";
    }).then(function () {
      button.disabled = false;
      button.textContent = "Отправить заявку";
    });
  });
})();
