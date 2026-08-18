/**
 * Связка демо-страницы с расчётным ядром.
 *
 * Подменяет сетевые вызовы виджета локальными: интерфейс остаётся тем же
 * самым файлом widget/calculator.js, но считает не сервер, а браузер.
 * Заявка никуда не уходит — только показывается состояние «отправлено».
 */
(function () {
  "use strict";

  var engine = CalcEngine.createEngine(window.CALC_LEGAL_CONFIG);
  var saved = {};
  var counter = 0;

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // --- локальный «сервер» ---------------------------------------------------

  window.CALC_LOCAL_ENGINE = function (path, payload) {
    return new Promise(function (resolve, reject) {
      // Небольшая задержка, чтобы состояние «Считаем…» было видно, как вживую.
      setTimeout(function () {
        try {
          if (path === "/api/v1/rate") { resolve(engine.rateStatus()); return; }

          if (path === "/api/v1/leads") {
            // На сайте без сервера заявку принимает не CRM, а мессенджер.
            if (typeof window.CALC_LEAD_HANDLER === "function") {
              resolve(window.CALC_LEAD_HANDLER(payload, saved[payload.calculation_id]));
              return;
            }
            resolve({ ok: true, id: "demo-lead-" + (++counter) });
            return;
          }

          var result = path.indexOf("delay") !== -1
            ? engine.calcDelay(payload)
            : engine.calcDefects(payload);

          result.calculation_id = "demo-" + (++counter);
          result.rate_status = engine.rateStatus();
          saved[result.calculation_id] = result;
          resolve(result);
        } catch (error) {
          reject(new Error(error.message));
        }
      }, 220);
    });
  };

  // --- печатная форма расчёта ----------------------------------------------

  function rows(items, render) { return items.map(render).join(""); }

  function sheetHtml(result) {
    var title = result.mode === "delay"
      ? "Расчёт неустойки за нарушение срока передачи объекта долевого строительства"
      : "Расчёт стоимости устранения недостатков и неустойки";
    var period = result.period || {};
    var parts = ["<h1>" + escapeHtml(title) + "</h1>"];

    parts.push('<p class="sheet__sub">' + (period.start_display
      ? "Период просрочки: " + escapeHtml(period.start_display) + " — " +
        escapeHtml(period.end_display) + ", засчитано " + escapeHtml(period.days_display)
      : "Период просрочки отсутствует") + "</p>");

    if (result.warnings && result.warnings.length) {
      parts.push('<div class="sheet__warn"><b>Внимание.</b> ' +
        result.warnings.map(escapeHtml).join("<br>") +
        "<br>Проверьте юридические параметры расчёта перед подачей документа в суд.</div>");
    }

    if (result.segments && result.segments.length) {
      parts.push("<h2>Расчёт по периодам</h2><table><thead><tr>" +
        "<th style='width:5%'>№</th><th style='width:21%'>Период</th><th style='width:8%'>Дней</th>" +
        "<th style='width:11%'>Ставка</th><th>Расчёт</th><th style='width:16%'>Сумма, ₽</th>" +
        "</tr></thead><tbody>" +
        rows(result.segments, function (segment, index) {
          var capped = segment.rate_before_cap
            ? "<br><span class='sheet__note'>ставка ограничена с " +
              escapeHtml(segment.rate_before_cap) + "% — " + escapeHtml(segment.cap_basis || "") + "</span>"
            : "";
          return "<tr><td class='center'>" + (index + 1) + "</td>" +
            "<td class='center'>" + escapeHtml(segment.start_display) + " — " + escapeHtml(segment.end_display) + "</td>" +
            "<td class='center'>" + segment.days + "</td>" +
            "<td class='center'>" + escapeHtml(segment.rate_display) + capped + "</td>" +
            "<td>" + escapeHtml(segment.formula) + "</td>" +
            "<td class='num'>" + escapeHtml(segment.amount_display) + "</td></tr>";
        }) + "</tbody></table>");
      parts.push('<p class="sheet__note">Порядок определения ставки: ' +
        escapeHtml(result.rate_mode_title || "") + ".</p>");
    }

    if (result.excluded && result.excluded.length) {
      parts.push("<h2>Периоды, исключённые из расчёта</h2><table><thead><tr>" +
        "<th style='width:30%'>Период</th><th style='width:12%'>Дней</th><th>Основание</th>" +
        "</tr></thead><tbody>" +
        rows(result.excluded, function (item) {
          return "<tr><td class='center'>" + escapeHtml(item.start_display) + " — " +
            escapeHtml(item.end_display) + "</td><td class='center'>" + item.days + "</td><td>" +
            escapeHtml(item.basis) + "</td></tr>";
        }) + "</tbody></table>");
    }

    parts.push("<h2>Состав требований</h2><table><thead><tr>" +
      "<th>Требование</th><th style='width:30%'>Основание</th><th style='width:18%'>Сумма, ₽</th>" +
      "</tr></thead><tbody>" +
      rows(result.lines || [], function (line) {
        var note = line.note ? "<br><span class='sheet__note'>" + escapeHtml(line.note) + "</span>" : "";
        return "<tr><td>" + escapeHtml(line.title) + note + "</td><td>" +
          escapeHtml(line.basis || "") + "</td><td class='num'>" +
          escapeHtml(line.amount_display) + "</td></tr>";
      }) +
      "<tr class='total'><td colspan='2'>ИТОГО к взысканию</td><td class='num'>" +
      escapeHtml(result.total_display) + " ₽</td></tr></tbody></table>");

    (result.notes || []).forEach(function (note) {
      parts.push('<p class="sheet__note">' + escapeHtml(note) + "</p>");
    });

    if (result.disclaimer) {
      parts.push('<p class="sheet__legal">' + escapeHtml(result.disclaimer) + "</p>");
    }
    parts.push('<p class="sheet__meta">Расчёт сформирован автоматически. Версия юридического конфига: ' +
      escapeHtml(String(result.config_version)) +
      ". Документ является черновиком и требует проверки юристом.</p>");

    return parts.join("");
  }

  window.CALC_LOCAL_PRINT = function (calculationId) {
    var result = saved[calculationId];
    if (!result) return;
    document.getElementById("sheet-body").innerHTML = sheetHtml(result);
    var backdrop = document.getElementById("sheet-backdrop");
    backdrop.hidden = false;
    document.getElementById("sheet-close").focus();
  };

  // --- готовые примеры ------------------------------------------------------

  var PRESETS = {
    long: {
      mode: "delay",
      fields: { "d-price": "8500000", "d-due": "2021-12-30", "d-actual": "2025-09-15" },
      transferred: true,
      advanced: { "a-moral": "50000", "a-duty": "13974" }
    },
    ongoing: {
      mode: "delay",
      fields: { "d-price": "12300000", "d-due": "2024-06-30" },
      transferred: false,
      advanced: { "a-moral": "100000" },
      rateMode: "per_segment"
    },
    defects: {
      mode: "defects",
      fields: { "f-repair": "487000", "f-expertise": "45000", "f-demand": "2025-07-01" },
      transferred: false,
      advanced: { "a-moral": "30000" }
    },
    entity: {
      mode: "delay",
      fields: { "d-price": "24000000", "d-due": "2025-08-01", "d-actual": "2026-04-20" },
      transferred: true,
      party: "legal",
      advanced: {}
    }
  };

  function setValue(id, value) {
    var node = document.getElementById(id);
    if (!node) return;
    node.value = value;
    node.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function setChecked(id, checked) {
    var node = document.getElementById(id);
    if (!node || node.checked === checked) return;
    node.checked = checked;
    node.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function applyPreset(key) {
    var preset = PRESETS[key];
    if (!preset) return;

    // Сброс на первый шаг: щёлкаем «назад», пока мастер не вернётся к началу.
    for (var i = 0; i < 5; i++) {
      var back = document.querySelector('.step[data-active="true"] [data-back]');
      if (!back) break;
      back.click();
    }

    setChecked("mode-" + preset.mode, true);
    document.querySelector('.step[data-step="1"] [data-next]').click();

    Object.keys(preset.fields).forEach(function (id) { setValue(id, preset.fields[id]); });
    if (preset.party) setValue("d-party", preset.party);
    document.querySelector('.step[data-step="2"] [data-next]').click();

    setChecked(preset.mode === "delay" ? "d-transferred" : "f-satisfied", preset.transferred);
    Object.keys(preset.fields).forEach(function (id) { setValue(id, preset.fields[id]); });

    if (preset.rateMode) setValue("a-rate-mode", preset.rateMode);
    document.getElementById("a-rate-mode").dispatchEvent(new Event("change", { bubbles: true }));
    Object.keys(preset.advanced).forEach(function (id) { setValue(id, preset.advanced[id]); });

    document.getElementById("btn-calc").click();
  }

  function init() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-preset]"), function (button) {
      button.addEventListener("click", function () { applyPreset(button.dataset.preset); });
    });

    var backdrop = document.getElementById("sheet-backdrop");
    document.getElementById("sheet-close").addEventListener("click", function () {
      backdrop.hidden = true;
    });
    backdrop.addEventListener("click", function (event) {
      if (event.target === backdrop) backdrop.hidden = true;
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") backdrop.hidden = true;
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
