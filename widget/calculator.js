/**
 * Виджет калькулятора неустойки по 214-ФЗ — пошаговый мастер.
 *
 * Без сборки и без зависимостей: файл кладётся рядом с index.html и
 * работает как отдельная страница или внутри iframe на сайте.
 *
 * Настройки: window.CALC_API_BASE, window.CALC_POLICY_URL,
 * window.CALC_POLICY_VERSION либо те же значения в query-параметрах.
 */
(function () {
  "use strict";

  var query = new URLSearchParams(window.location.search);
  var API = (window.CALC_API_BASE || "").replace(/\/$/, "");
  var POLICY_URL = window.CALC_POLICY_URL || query.get("policy") || "/policy";
  var POLICY_VERSION = window.CALC_POLICY_VERSION || query.get("policy_version") || "1.0";

  var LAST_STEP = 4;
  var state = { mode: null, step: 1, calculationId: null, rateBannerShown: false };

  function $(id) { return document.getElementById(id); }
  function all(selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); }
  function on(el, event, handler) { if (el) el.addEventListener(event, handler); }

  function icon(name) { return '<svg><use href="#i-' + name + '"/></svg>'; }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // --- тема ----------------------------------------------------------------

  function currentTheme() {
    var explicit = document.documentElement.getAttribute("data-theme");
    if (explicit) return explicit;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark" : "light";
  }

  function toggleTheme() {
    var next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("calc-theme", next); } catch (e) { /* приватный режим */ }
  }

  // --- ввод сумм -----------------------------------------------------------

  function digitsOnly(value) {
    return String(value == null ? "" : value).replace(/[^\d]/g, "");
  }

  function groupDigits(digits) {
    return digits.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }

  /** '8 500 000' -> '8500000'; пустое поле -> null */
  function readMoney(id) {
    var digits = digitsOnly($(id) && $(id).value);
    return digits ? digits : null;
  }

  function readRate(id) {
    var raw = (($(id) && $(id).value) || "").replace(",", ".").replace(/[^\d.]/g, "");
    return raw ? raw : null;
  }

  function attachMoneyFormatting(input) {
    on(input, "input", function () {
      var fromEnd = input.value.length - input.selectionStart;
      input.value = groupDigits(digitsOnly(input.value));
      var position = Math.max(0, input.value.length - fromEnd);
      try { input.setSelectionRange(position, position); } catch (e) { /* не критично */ }
    });
  }

  // --- сообщения -----------------------------------------------------------

  function clearErrors() {
    all("[data-error-for]").forEach(function (node) { node.textContent = ""; });
  }

  function setError(fieldId, message) {
    var node = document.querySelector('[data-error-for="' + fieldId + '"]');
    if (node) node.textContent = message;
    return false;
  }

  function noteHtml(kind, title, text) {
    var symbol = kind === "ok" ? "ok" : "alert";
    return '<div class="note note--' + kind + '">' + icon(symbol) +
      '<div class="note__body">' + (title ? "<strong>" + escapeHtml(title) + "</strong>" : "") +
      escapeHtml(text) + "</div></div>";
  }

  function showNote(target, kind, title, text) {
    $(target).innerHTML = noteHtml(kind, title, text);
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

  /**
   * Единственная точка обращения к бэкенду.
   *
   * Если на странице объявлен window.CALC_LOCAL_ENGINE, запросы уходят в него
   * вместо сети. Так работает автономная демо-версия: интерфейс тот же самый,
   * а расчёт выполняется на месте. В боевом виджете хук не объявлен.
   */
  function callApi(path, payload) {
    if (typeof window.CALC_LOCAL_ENGINE === "function") {
      return window.CALC_LOCAL_ENGINE(path, payload);
    }
    if (payload === undefined) return request(path, {});
    return request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  }

  function postJson(path, payload) { return callApi(path, payload); }

  // --- навигация по шагам --------------------------------------------------

  function applyModeVisibility() {
    all("[data-mode-panel]").forEach(function (panel) {
      panel.hidden = panel.dataset.modePanel !== state.mode;
    });

    var isDelay = state.mode === "delay";
    $("s2-title").textContent = isDelay ? "Суммы по договору" : "Суммы по недостаткам";
    $("s2-hint").textContent = isDelay
      ? "Цену возьмите из договора участия в долевом строительстве."
      : "Цифры возьмите из заключения эксперта.";
    $("s3-title").textContent = isDelay ? "Сроки передачи" : "Сроки по требованию";
    $("s3-hint").textContent = isDelay
      ? "По этим датам считается период просрочки."
      : "Просрочка считается после истечения срока на удовлетворение требования.";

    var firstOption = $("a-rate-mode").options[0];
    firstOption.textContent = isDelay
      ? "На день исполнения обязательства по договору"
      : "На дату окончания срока на удовлетворение требования";
  }

  function renderSteps() {
    all(".step").forEach(function (section) {
      section.dataset.active = String(Number(section.dataset.step) === state.step);
    });

    $("steps-fill").style.width = (state.step / LAST_STEP * 100) + "%";
    all("#steps-list li").forEach(function (item) {
      var index = Number(item.dataset.step);
      item.dataset.state = index === state.step ? "current" : (index < state.step ? "done" : "");
    });

    notifyHeight();
  }

  function goTo(step) {
    state.step = Math.min(LAST_STEP, Math.max(1, step));
    renderSteps();
    if (window.parent === window) {
      $("calc").scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      window.parent.postMessage({ type: "garant-calc-scroll" }, "*");
    }
  }

  // --- валидация шагов -----------------------------------------------------

  function validateStep(step) {
    clearErrors();

    if (step === 1) {
      if (!state.mode) {
        showNote("global-note", "error", "", "Выберите, с какой ситуацией вы пришли.");
        return false;
      }
      $("global-note").innerHTML = "";
      return true;
    }

    if (step === 2) {
      if (state.mode === "delay") {
        return readMoney("d-price") ? true : setError("d-price", "Укажите цену договора");
      }
      return readMoney("f-repair") ? true : setError("f-repair", "Укажите стоимость устранения");
    }

    if (step === 3) {
      var ok = true;
      if (state.mode === "delay") {
        if (!$("d-due").value) ok = setError("d-due", "Укажите срок передачи по договору");
        if ($("d-transferred").checked) {
          if (!$("d-actual").value) ok = setError("d-actual", "Укажите дату передачи");
          else if ($("d-due").value && $("d-actual").value < $("d-due").value) {
            setError("d-actual", "Передача раньше срока — просрочки нет");
          }
        }
      } else {
        if (!$("f-demand").value) ok = setError("f-demand", "Укажите дату вручения требования");
        if ($("f-satisfied").checked && !$("f-satisfied-date").value) {
          ok = setError("f-satisfied-date", "Укажите дату удовлетворения");
        }
      }
      return ok;
    }

    return true;
  }

  // --- сбор данных ---------------------------------------------------------

  function expenses() {
    var items = [];
    var duty = readMoney("a-duty");
    var lawyer = readMoney("a-lawyer");
    if (duty) items.push({ title: "Госпошлина", amount: duty, code: "duty" });
    if (lawyer) items.push({ title: "Расходы на представителя", amount: lawyer, code: "lawyer" });
    return items;
  }

  function advanced() {
    var mode = $("a-rate-mode").value;
    var payload = {
      rate_mode: mode,
      moral_harm: readMoney("a-moral") || "0",
      include_consumer_penalty: $("a-penalty").checked,
      expenses: expenses(),
      source: "widget"
    };
    if (mode === "manual") payload.manual_rate = readRate("a-manual-rate");
    if (mode === "on_claim_date") payload.claim_date = $("a-claim-date").value || null;
    return payload;
  }

  function buildPayload() {
    var payload = advanced();
    if (state.mode === "delay") {
      payload.contract_price = readMoney("d-price");
      payload.due_date = $("d-due").value;
      payload.actual_date = $("d-transferred").checked ? $("d-actual").value : null;
      payload.is_individual = $("d-party").value === "individual";
    } else {
      payload.repair_cost = readMoney("f-repair");
      payload.demand_served_date = $("f-demand").value;
      payload.satisfied_date = $("f-satisfied").checked ? $("f-satisfied-date").value : null;
      payload.expertise_cost = readMoney("f-expertise") || "0";
      payload.include_repair_cost_in_total = $("a-include-repair").checked;
    }
    return payload;
  }

  // --- вывод результата ----------------------------------------------------

  function cell(label, value, extraClass) {
    return '<td data-label="' + escapeHtml(label) + '"' +
      (extraClass ? ' class="' + extraClass + '"' : "") + ">" + value + "</td>";
  }

  function renderSegments(segments) {
    $("r-segments-block").hidden = segments.length === 0;
    $("r-segments").innerHTML = segments.map(function (segment) {
      var capped = segment.rate_before_cap
        ? '<span class="sub">ограничена с ' + escapeHtml(segment.rate_before_cap) + "% — " +
          escapeHtml(segment.cap_basis || "") + "</span>"
        : "";
      return "<tr>" +
        cell("Период", escapeHtml(segment.start_display) + " — " + escapeHtml(segment.end_display)) +
        cell("Дней", segment.days) +
        cell("Ставка", escapeHtml(segment.rate_display) + capped) +
        cell("Расчёт", '<span class="formula">' + escapeHtml(segment.formula) + "</span>") +
        cell("Сумма, ₽", escapeHtml(segment.amount_display), "num") +
        "</tr>";
    }).join("");
  }

  function renderExcluded(excluded) {
    $("r-excluded-block").hidden = excluded.length === 0;
    $("r-excluded").innerHTML = excluded.map(function (item) {
      return "<tr>" +
        cell("Период", escapeHtml(item.start_display) + " — " + escapeHtml(item.end_display)) +
        cell("Дней", item.days) +
        cell("Основание", escapeHtml(item.basis)) +
        "</tr>";
    }).join("");
  }

  function renderLines(lines, totalDisplay) {
    var rows = lines.map(function (line) {
      var note = line.note ? '<span class="sub">' + escapeHtml(line.note) + "</span>" : "";
      return "<tr>" +
        cell("Требование", escapeHtml(line.title) + note) +
        cell("Основание", escapeHtml(line.basis || "")) +
        cell("Сумма, ₽", escapeHtml(line.amount_display), "num") +
        "</tr>";
    });
    rows.push(
      '<tr class="grand">' + cell("", "Итого") + cell("", "") +
      cell("Сумма, ₽", escapeHtml(totalDisplay), "num") + "</tr>"
    );
    $("r-lines").innerHTML = rows.join("");
  }

  function renderWarnings(result) {
    var blocks = [];
    if (result.warnings && result.warnings.length) {
      blocks.push(
        '<div class="note note--warn">' + icon("alert") +
        '<div class="note__body"><strong>Юридические параметры не подтверждены</strong>' +
        result.warnings.map(escapeHtml).join("<br>") +
        "<br>Расчёт предварительный: перед подачей документов его проверит юрист.</div></div>"
      );
    }
    var rate = result.rate_status;
    if (rate && rate.is_stale && rate.warning && !state.rateBannerShown) {
      blocks.push(noteHtml("warn", "Ставка ЦБ из локальной копии", rate.warning));
    }
    $("r-warnings").innerHTML = blocks.join("");
  }

  function renderResult(result) {
    state.calculationId = result.calculation_id || null;

    $("r-total").textContent = result.total_display + " ₽";
    var period = result.period || {};
    $("r-period").textContent = period.start_display
      ? "Период просрочки: " + period.start_display + " — " + period.end_display +
        " · засчитано " + period.days_display
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

    $("form-lead").hidden = false;
    $("lead-status").innerHTML = "";
    $("btn-print").disabled = !state.calculationId;
    goTo(4);
  }

  function calculate() {
    if (!validateStep(3)) { notifyHeight(); return; }

    var button = $("btn-calc");
    button.disabled = true;
    button.innerHTML = "Считаем…";

    var path = state.mode === "delay" ? "/api/v1/calc/delay" : "/api/v1/calc/defects";
    postJson(path, buildPayload())
      .then(renderResult)
      .catch(function (error) {
        showNote("global-note", "error", "Не удалось рассчитать", error.message);
      })
      .then(function () {
        button.disabled = false;
        button.innerHTML = "Рассчитать " + icon("right");
        notifyHeight();
      });
  }

  // --- заявка --------------------------------------------------------------

  function submitLead(event) {
    event.preventDefault();
    clearErrors();

    var name = $("l-name").value.trim();
    var phone = $("l-phone").value.trim();
    var ok = true;
    if (name.length < 2) ok = setError("l-name", "Укажите имя");
    if (digitsOnly(phone).length < 10) ok = setError("l-phone", "Укажите телефон");
    if (!$("l-consent").checked) ok = setError("l-consent", "Без согласия мы не можем принять заявку");
    if (!ok) { notifyHeight(); return; }

    var button = $("btn-lead");
    button.disabled = true;
    button.textContent = "Отправляем…";

    postJson("/api/v1/leads", {
      name: name,
      phone: phone,
      topic: state.mode === "delay" ? "neustoyka" : "defects",
      region: $("l-region").value,
      project: $("l-project").value.trim() || null,
      calculation_id: state.calculationId,
      consent: true,
      consent_policy_version: POLICY_VERSION,
      page_url: window.location.href,
      source: "calculator",
      website: $("l-website").value
    })
      .then(function () {
        $("form-lead").hidden = true;
        showNote("lead-status", "ok", "Заявка отправлена",
          "Юрист свяжется с вами и разберёт расчёт. Обычно перезваниваем в течение рабочего дня.");
      })
      .catch(function (error) {
        showNote("lead-status", "error", "Не удалось отправить заявку", error.message);
      })
      .then(function () {
        button.disabled = false;
        button.textContent = "Отправить заявку";
        notifyHeight();
      });
  }

  // --- состояние ставки ----------------------------------------------------

  function loadRateStatus() {
    callApi("/api/v1/rate")
      .then(function (status) {
        if (status.is_stale && status.warning) {
          state.rateBannerShown = true;
          showNote("global-note", "warn", "Ключевая ставка требует проверки", status.warning);
          notifyHeight();
        }
      })
      .catch(function () { /* виджет должен работать и без этого запроса */ });
  }

  // --- высота во встроенном режиме ----------------------------------------

  var lastHeight = 0;
  function notifyHeight() {
    if (window.parent === window) return;
    var height = Math.ceil(document.documentElement.getBoundingClientRect().height);
    if (height === lastHeight) return;
    lastHeight = height;
    window.parent.postMessage({ type: "garant-calc-height", height: height }, "*");
  }

  // --- инициализация -------------------------------------------------------

  function init() {
    on($("theme-toggle"), "click", toggleTheme);

    all('input[inputmode="numeric"]').forEach(attachMoneyFormatting);

    all('input[name="mode"]').forEach(function (input) {
      on(input, "change", function () {
        state.mode = input.value;
        $("global-note").innerHTML = "";
        applyModeVisibility();
        notifyHeight();
      });
    });

    all("[data-next]").forEach(function (button) {
      on(button, "click", function () {
        if (validateStep(state.step)) goTo(state.step + 1);
        else notifyHeight();
      });
    });
    all("[data-back]").forEach(function (button) {
      on(button, "click", function () { goTo(state.step - 1); });
    });
    on($("btn-calc"), "click", calculate);

    on($("d-transferred"), "change", function () {
      $("d-actual-wrap").hidden = !this.checked;
      notifyHeight();
    });
    on($("f-satisfied"), "change", function () {
      $("f-satisfied-wrap").hidden = !this.checked;
      notifyHeight();
    });

    on($("a-rate-mode"), "change", function () {
      var value = this.value;
      all("[data-show-for]").forEach(function (node) {
        node.hidden = node.dataset.showFor !== value;
      });
      notifyHeight();
    });

    // Enter в поле продвигает мастер, а не отправляет форму раньше времени.
    all(".step input").forEach(function (input) {
      on(input, "keydown", function (event) {
        if (event.key !== "Enter" || input.closest("#form-lead")) return;
        event.preventDefault();
        if (state.step === 3) calculate();
        else if (validateStep(state.step)) goTo(state.step + 1);
      });
    });

    on($("form-lead"), "submit", submitLead);
    on($("btn-print"), "click", function () {
      if (!state.calculationId) return;
      if (typeof window.CALC_LOCAL_PRINT === "function") {
        window.CALC_LOCAL_PRINT(state.calculationId);
        return;
      }
      window.open(API + "/api/v1/calc/" + state.calculationId + "/print", "_blank", "noopener");
    });

    var policyLink = $("l-policy-link");
    if (policyLink) policyLink.setAttribute("href", POLICY_URL);

    var preset = query.get("mode");
    if (preset === "delay" || preset === "defects") {
      var input = document.querySelector('input[name="mode"][value="' + preset + '"]');
      if (input) { input.checked = true; state.mode = preset; }
    }
    applyModeVisibility();
    renderSteps();
    loadRateStatus();

    window.addEventListener("resize", notifyHeight);
    if (window.ResizeObserver) {
      new ResizeObserver(notifyHeight).observe(document.documentElement);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
