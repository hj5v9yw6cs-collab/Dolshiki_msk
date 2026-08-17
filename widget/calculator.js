/**
 * Виджет калькулятора неустойки по 214-ФЗ.
 *
 * Без сборки и без зависимостей: файл кладётся рядом с index.html и
 * работает как отдельная страница или внутри iframe на сайте.
 *
 * Базовый адрес API берётся из window.CALC_API_BASE, иначе — текущий домен.
 */
(function () {
  "use strict";

  var query = new URLSearchParams(window.location.search);
  var API = (window.CALC_API_BASE || "").replace(/\/$/, "");
  var POLICY_URL = window.CALC_POLICY_URL || query.get("policy") || "/policy";
  var POLICY_VERSION = window.CALC_POLICY_VERSION || query.get("policy_version") || "1.0";

  var state = { mode: "delay", calculationId: null };

  function $(id) { return document.getElementById(id); }
  function on(el, event, handler) { if (el) el.addEventListener(event, handler); }

  // --- ввод сумм -----------------------------------------------------------

  function digitsOnly(value) {
    return String(value == null ? "" : value).replace(/[^\d]/g, "");
  }

  function groupDigits(digits) {
    return digits.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }

  /** '8 500 000' -> '8500000'; пустая строка -> null */
  function readMoney(id) {
    var digits = digitsOnly($(id) && $(id).value);
    return digits ? digits : null;
  }

  function readRate(id) {
    var raw = ($(id) && $(id).value || "").replace(",", ".").replace(/[^\d.]/g, "");
    return raw ? raw : null;
  }

  function attachMoneyFormatting(input) {
    on(input, "input", function () {
      var caretFromEnd = input.value.length - input.selectionStart;
      input.value = groupDigits(digitsOnly(input.value));
      var position = Math.max(0, input.value.length - caretFromEnd);
      try { input.setSelectionRange(position, position); } catch (e) { /* не критично */ }
    });
  }

  // --- ошибки полей --------------------------------------------------------

  function clearErrors(form) {
    var nodes = form.querySelectorAll("[data-error-for]");
    for (var i = 0; i < nodes.length; i++) nodes[i].textContent = "";
    $("form-error").innerHTML = "";
  }

  function setError(fieldId, message) {
    var node = document.querySelector('[data-error-for="' + fieldId + '"]');
    if (node) node.textContent = message;
  }

  function banner(target, kind, title, text) {
    var html =
      '<div class="banner banner--' + kind + '">' +
      (title ? "<strong>" + escapeHtml(title) + "</strong>" : "") +
      escapeHtml(text) +
      "</div>";
    $(target).innerHTML = html;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // --- запросы -------------------------------------------------------------

  function request(path, options) {
    return fetch(API + path, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok) {
          var detail = body && body.detail;
          if (Array.isArray(detail)) detail = detail.map(function (d) { return d.msg; }).join("; ");
          throw new Error(detail || "Сервис временно недоступен. Попробуйте позже.");
        }
        return body;
      });
    });
  }

  function postJson(path, payload) {
    return request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  }

  // --- вкладки -------------------------------------------------------------

  function switchMode(mode) {
    state.mode = mode;
    var tabs = document.querySelectorAll(".calc__tab");
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].setAttribute("aria-selected", String(tabs[i].dataset.mode === mode));
    }
    $("form-delay").hidden = mode !== "delay";
    $("form-defects").hidden = mode !== "defects";
    $("result").hidden = true;
    $("form-error").innerHTML = "";
  }

  // --- сбор данных ---------------------------------------------------------

  function expenses(prefix) {
    var items = [];
    var duty = readMoney(prefix + "-duty");
    var lawyer = readMoney(prefix + "-lawyer");
    if (duty) items.push({ title: "Госпошлина", amount: duty, code: "duty" });
    if (lawyer) items.push({ title: "Расходы на представителя", amount: lawyer, code: "lawyer" });
    return items;
  }

  function commonExtras(prefix) {
    var mode = $(prefix + "-rate-mode").value;
    return {
      rate_mode: mode,
      manual_rate: mode === "manual" ? readRate(prefix + "-manual-rate") : null,
      claim_date: mode === "on_claim_date" ? ($(prefix + "-claim-date").value || null) : null,
      moral_harm: readMoney(prefix + "-moral") || "0",
      include_consumer_penalty: $(prefix + "-penalty").checked,
      expenses: expenses(prefix)
    };
  }

  function collectDelay() {
    var errors = 0;
    var price = readMoney("d-price");
    var due = $("d-due").value;
    if (!price) { setError("d-price", "Укажите цену договора"); errors++; }
    if (!due) { setError("d-due", "Укажите срок передачи по договору"); errors++; }

    var actual = null;
    if ($("d-transferred").checked) {
      actual = $("d-actual").value;
      if (!actual) { setError("d-actual", "Укажите дату передачи"); errors++; }
      else if (due && actual < due) {
        setError("d-actual", "Передача раньше срока — просрочки нет");
      }
    }
    if (errors) return null;

    var payload = {
      contract_price: price,
      due_date: due,
      actual_date: actual,
      is_individual: $("d-party").value === "individual",
      source: "widget"
    };
    var extras = commonExtras("d");
    for (var key in extras) if (extras[key] !== null) payload[key] = extras[key];
    return payload;
  }

  function collectDefects() {
    var errors = 0;
    var repair = readMoney("f-repair");
    var demand = $("f-demand").value;
    if (!repair) { setError("f-repair", "Укажите стоимость устранения"); errors++; }
    if (!demand) { setError("f-demand", "Укажите дату вручения требования"); errors++; }

    var satisfied = null;
    if ($("f-satisfied").checked) {
      satisfied = $("f-satisfied-date").value;
      if (!satisfied) { setError("f-satisfied-date", "Укажите дату удовлетворения"); errors++; }
    }
    if (errors) return null;

    var payload = {
      repair_cost: repair,
      demand_served_date: demand,
      satisfied_date: satisfied,
      expertise_cost: readMoney("f-expertise") || "0",
      include_repair_cost_in_total: $("f-include-repair").checked,
      source: "widget"
    };
    var extras = commonExtras("f");
    for (var key in extras) if (extras[key] !== null) payload[key] = extras[key];
    return payload;
  }

  // --- вывод результата ----------------------------------------------------

  function renderSegments(segments) {
    var block = $("r-segments-block");
    block.hidden = segments.length === 0;
    $("r-segments").innerHTML = segments.map(function (segment) {
      var capped = segment.rate_before_cap
        ? '<span class="sub">ограничена с ' + escapeHtml(segment.rate_before_cap) + "% — " +
          escapeHtml(segment.cap_basis || "") + "</span>"
        : "";
      return "<tr>" +
        "<td>" + escapeHtml(segment.start_display) + " — " + escapeHtml(segment.end_display) + "</td>" +
        "<td>" + segment.days + "</td>" +
        "<td>" + escapeHtml(segment.rate_display) + capped + "</td>" +
        "<td>" + escapeHtml(segment.formula) + "</td>" +
        '<td class="num">' + escapeHtml(segment.amount_display) + "</td>" +
        "</tr>";
    }).join("");
  }

  function renderExcluded(excluded) {
    $("r-excluded-block").hidden = excluded.length === 0;
    $("r-excluded").innerHTML = excluded.map(function (item) {
      return "<tr>" +
        "<td>" + escapeHtml(item.start_display) + " — " + escapeHtml(item.end_display) + "</td>" +
        "<td>" + item.days + "</td>" +
        "<td>" + escapeHtml(item.basis) + "</td>" +
        "</tr>";
    }).join("");
  }

  function renderLines(lines, totalDisplay) {
    var rows = lines.map(function (line) {
      var note = line.note ? '<span class="sub">' + escapeHtml(line.note) + "</span>" : "";
      return "<tr>" +
        "<td>" + escapeHtml(line.title) + note + "</td>" +
        "<td>" + escapeHtml(line.basis || "") + "</td>" +
        '<td class="num">' + escapeHtml(line.amount_display) + "</td>" +
        "</tr>";
    });
    rows.push(
      '<tr class="total"><td colspan="2">Итого</td><td class="num">' +
      escapeHtml(totalDisplay) + "</td></tr>"
    );
    $("r-lines").innerHTML = rows.join("");
  }

  function renderWarnings(result) {
    var blocks = [];
    if (result.warnings && result.warnings.length) {
      blocks.push(
        '<div class="banner banner--warn"><strong>Юридические параметры не подтверждены</strong>' +
        result.warnings.map(escapeHtml).join("<br>") +
        "<br>Расчёт предварительный, перед подачей документов его проверит юрист.</div>"
      );
    }
    // Если предупреждение о ставке уже висит над формой, не дублируем его.
    var rate = result.rate_status;
    if (rate && rate.is_stale && rate.warning && !$("rate-banner").innerHTML) {
      blocks.push('<div class="banner banner--warn"><strong>Ставка ЦБ из локальной копии</strong>' +
        escapeHtml(rate.warning) + "</div>");
    }
    $("r-warnings").innerHTML = blocks.join("");
  }

  function renderResult(result) {
    state.calculationId = result.calculation_id || null;

    $("r-total").textContent = result.total_display + " ₽";
    var period = result.period || {};
    $("r-period").textContent = period.start_display
      ? "Период просрочки: " + period.start_display + " — " + period.end_display +
        ", засчитано " + period.days_display
      : "Просрочка не начислена";

    renderWarnings(result);
    renderSegments(result.segments || []);
    renderExcluded(result.excluded || []);
    renderLines(result.lines || [], result.total_display);

    $("r-rate-mode").textContent = result.rate_mode_title
      ? "Порядок определения ставки: " + result.rate_mode_title + "."
      : "";
    $("r-notes").innerHTML = (result.notes || [])
      .map(function (note) { return "<li>" + escapeHtml(note) + "</li>"; }).join("");
    $("r-disclaimer").textContent = result.disclaimer || "";

    $("result").hidden = false;
    $("lead").hidden = true;
    $("lead-status").innerHTML = "";
    $("btn-print").disabled = !state.calculationId;
    notifyHeight();
    $("result").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // --- отправка форм -------------------------------------------------------

  function submitCalculation(event, form, collect, path) {
    event.preventDefault();
    clearErrors(form);
    var payload = collect();
    if (!payload) { notifyHeight(); return; }

    var button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = "Считаем…";

    postJson(path, payload)
      .then(renderResult)
      .catch(function (error) {
        banner("form-error", "error", "Не удалось рассчитать", error.message);
        $("result").hidden = true;
      })
      .then(function () {
        button.disabled = false;
        button.textContent = "Рассчитать";
        notifyHeight();
      });
  }

  function submitLead(event) {
    event.preventDefault();
    var form = $("form-lead");
    clearErrors(form);

    var errors = 0;
    var name = $("l-name").value.trim();
    var phone = $("l-phone").value.trim();
    if (name.length < 2) { setError("l-name", "Укажите имя"); errors++; }
    if (digitsOnly(phone).length < 10) { setError("l-phone", "Укажите телефон"); errors++; }
    if (!$("l-consent").checked) {
      setError("l-consent", "Без согласия мы не можем принять заявку");
      errors++;
    }
    if (errors) { notifyHeight(); return; }

    var button = $("btn-lead-submit");
    button.disabled = true;
    button.textContent = "Отправляем…";

    postJson("/api/v1/leads", {
      name: name,
      phone: phone,
      topic: state.mode === "delay" ? "neustoyka" : "defects",
      region: $("l-region").value,
      project: $("l-project").value.trim() || null,
      comment: $("l-comment").value.trim() || null,
      calculation_id: state.calculationId,
      consent: true,
      consent_policy_version: POLICY_VERSION,
      page_url: window.location.href,
      source: "calculator",
      website: $("l-website").value
    })
      .then(function () {
        $("form-lead").hidden = true;
        banner("lead-status", "ok", "Заявка отправлена",
          "Юрист свяжется с вами и разберёт расчёт. Обычно перезваниваем в течение рабочего дня.");
      })
      .catch(function (error) {
        banner("lead-status", "error", "Не удалось отправить заявку", error.message);
      })
      .then(function () {
        button.disabled = false;
        button.textContent = "Отправить заявку";
        notifyHeight();
      });
  }

  // --- состояние ставки ----------------------------------------------------

  function loadRateStatus() {
    request("/api/v1/rate", {})
      .then(function (status) {
        if (status.is_stale && status.warning) {
          banner("rate-banner", "warn", "Ключевая ставка требует проверки", status.warning);
        } else {
          $("rate-banner").innerHTML = "";
        }
      })
      .catch(function () { /* виджет должен работать и без этого запроса */ });
  }

  // --- высота во встроенном режиме ----------------------------------------

  function notifyHeight() {
    if (window.parent === window) return;
    var height = document.documentElement.scrollHeight;
    window.parent.postMessage({ type: "garant-calc-height", height: height }, "*");
  }

  // --- инициализация -------------------------------------------------------

  function init() {
    var tabs = document.querySelectorAll(".calc__tab");
    for (var i = 0; i < tabs.length; i++) {
      on(tabs[i], "click", function (event) { switchMode(event.currentTarget.dataset.mode); });
    }

    var moneyInputs = document.querySelectorAll('input[inputmode="numeric"]');
    for (var j = 0; j < moneyInputs.length; j++) attachMoneyFormatting(moneyInputs[j]);

    on($("d-transferred"), "change", function () {
      $("d-actual-wrap").hidden = !this.checked;
      notifyHeight();
    });
    on($("f-satisfied"), "change", function () {
      $("f-satisfied-wrap").hidden = !this.checked;
      notifyHeight();
    });

    var rateSelects = document.querySelectorAll("[data-rate-mode]");
    for (var k = 0; k < rateSelects.length; k++) {
      on(rateSelects[k], "change", function (event) {
        var form = event.currentTarget.closest("form");
        var conditionals = form.querySelectorAll("[data-show-for]");
        for (var m = 0; m < conditionals.length; m++) {
          conditionals[m].hidden = conditionals[m].dataset.showFor !== event.currentTarget.value;
        }
        notifyHeight();
      });
    }

    on($("form-delay"), "submit", function (event) {
      submitCalculation(event, $("form-delay"), collectDelay, "/api/v1/calc/delay");
    });
    on($("form-defects"), "submit", function (event) {
      submitCalculation(event, $("form-defects"), collectDefects, "/api/v1/calc/defects");
    });

    on($("btn-lead"), "click", function () {
      $("lead").hidden = false;
      $("l-name").focus();
      notifyHeight();
    });
    on($("btn-print"), "click", function () {
      if (!state.calculationId) return;
      window.open(API + "/api/v1/calc/" + state.calculationId + "/print", "_blank", "noopener");
    });
    on($("form-lead"), "submit", submitLead);

    var policyLink = $("l-policy-link");
    if (policyLink) policyLink.setAttribute("href", POLICY_URL);

    if (query.get("mode") === "defects") switchMode("defects");

    loadRateStatus();
    notifyHeight();
    window.addEventListener("resize", notifyHeight);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
