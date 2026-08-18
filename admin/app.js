/**
 * Рабочий кабинет: дела, заявки, карточка дела.
 *
 * Без сборки и фреймворков — на потоке в 30 дел в месяц это лишний слой.
 * Токен сессии хранится в localStorage и уходит заголовком Authorization.
 */
(function () {
  "use strict";

  var API = "";
  var TOKEN_KEY = "case-token";

  var state = { user: null, meta: null, tab: "cases", cases: [], leads: [], current: null };

  function $(id) { return document.getElementById(id); }
  function all(selector) { return Array.prototype.slice.call(document.querySelectorAll(selector)); }
  function on(el, event, handler) { if (el) el.addEventListener(event, handler); }
  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function token() { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; } }
  function setToken(value) {
    try { value ? localStorage.setItem(TOKEN_KEY, value) : localStorage.removeItem(TOKEN_KEY); }
    catch (e) { /* приватный режим */ }
  }

  function ruDate(iso) {
    if (!iso) return "—";
    var parts = String(iso).slice(0, 10).split("-");
    return parts[2] + "." + parts[1] + "." + parts[0];
  }

  function ruDateTime(iso) {
    var date = new Date(iso);
    var pad = function (n) { return n < 10 ? "0" + n : String(n); };
    return pad(date.getDate()) + "." + pad(date.getMonth() + 1) + "." + date.getFullYear() +
      " " + pad(date.getHours()) + ":" + pad(date.getMinutes());
  }

  function plural(count, one, few, many) {
    if (count % 100 >= 11 && count % 100 <= 14) return many;
    var last = count % 10;
    if (last === 1) return one;
    if (last >= 2 && last <= 4) return few;
    return many;
  }

  // --- сеть ------------------------------------------------------------------

  function api(path, options) {
    options = options || {};
    var headers = { "Content-Type": "application/json" };
    if (token()) headers.Authorization = "Bearer " + token();

    return fetch(API + path, {
      method: options.method || "GET",
      headers: headers,
      body: options.body ? JSON.stringify(options.body) : undefined
    }).then(function (response) {
      if (response.status === 401 && path.indexOf("/auth/login") === -1) {
        setToken("");
        showLogin("Сессия закончилась. Войдите заново.");
        throw new Error("Требуется вход");
      }
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok) {
          var detail = body && body.detail;
          if (Array.isArray(detail)) detail = detail.map(function (d) { return d.msg; }).join("; ");
          throw new Error(detail || "Сервис недоступен. Попробуйте позже.");
        }
        return body;
      });
    });
  }

  function toast(kind, text) {
    var node = document.createElement("div");
    node.className = "toast toast--" + kind;
    node.textContent = text;
    $("toast-root").appendChild(node);
    setTimeout(function () { node.remove(); }, 4000);
  }

  // --- экраны ----------------------------------------------------------------

  function showLogin(message) {
    $("screen-app").hidden = true;
    $("screen-login").hidden = false;
    $("login-error").innerHTML = message
      ? '<div class="note-box note-box--error">' + esc(message) + "</div>" : "";
  }

  function showApp() {
    $("screen-login").hidden = true;
    $("screen-app").hidden = false;
  }

  function switchTab(tab) {
    state.tab = tab;
    all(".tab").forEach(function (button) {
      button.setAttribute("aria-current", String(button.dataset.tab === tab));
    });
    $("view-cases").hidden = tab !== "cases";
    $("view-leads").hidden = tab !== "leads";
    $("view-case").hidden = true;
    if (tab === "cases") loadCases();
    if (tab === "leads") loadLeads();
  }

  // --- сводка ----------------------------------------------------------------

  function renderTiles(summary) {
    var tiles = [
      { label: "Активных дел", value: summary.active },
      { label: "Просрочено", value: summary.overdue.length, kind: "danger", filter: "overdue" },
      { label: "Срок на днях", value: summary.soon.length, kind: "warn" },
      { label: "Новых заявок", value: summary.new_leads, tab: "leads" }
    ];
    if (summary.money) {
      tiles.push({ label: "Присуждено", value: summary.money.awarded_display + " ₽", kind: "money" });
      tiles.push({ label: "Получено", value: summary.money.received_display + " ₽", kind: "money" });
    }

    $("tiles").innerHTML = tiles.map(function (tile) {
      var clickable = tile.filter || tile.tab ? " data-clickable" : "";
      var action = tile.filter ? ' data-filter="' + tile.filter + '"' :
        (tile.tab ? ' data-goto="' + tile.tab + '"' : "");
      return '<div class="tile' + (tile.kind ? " tile--" + tile.kind : "") + '"' + clickable + action + '>' +
        '<div class="tile__label">' + esc(tile.label) + "</div>" +
        '<div class="tile__value">' + esc(tile.value) + "</div></div>";
    }).join("");

    all("[data-filter]").forEach(function (node) {
      on(node, "click", function () { loadCases({ only_overdue: true }); });
    });
    all("[data-goto]").forEach(function (node) {
      on(node, "click", function () { switchTab(node.dataset.goto); });
    });

    $("leads-count").hidden = !summary.new_leads;
    $("leads-count").textContent = summary.new_leads;
  }

  // --- список дел ------------------------------------------------------------

  function deadlinePill(deadline) {
    if (!deadline) return '<span class="muted">—</span>';
    var days = Math.abs(deadline.days_left);
    var kind = deadline.is_overdue ? "overdue" : (deadline.is_soon ? "soon" : "");
    var when = deadline.is_overdue
      ? "просрочен на " + days + " " + plural(days, "день", "дня", "дней")
      : (deadline.days_left === 0 ? "сегодня" : "через " + days + " " + plural(days, "день", "дня", "дней"));
    return '<span class="pill' + (kind ? " pill--" + kind : "") + '">' + esc(deadline.title) + "</span>" +
      '<div class="muted">' + esc(ruDate(deadline.due_on)) + " · " + esc(when) + "</div>";
  }

  function stagePill(item) {
    var finals = ["closed", "rejected", "money"];
    var kind = finals.indexOf(item.stage) !== -1 ? "done" : "active";
    return '<span class="pill pill--' + kind + '">' + esc(item.stage_title) + "</span>";
  }

  function renderCases(items) {
    $("cases-empty").hidden = items.length > 0;
    $("cases-body").innerHTML = items.map(function (item) {
      return '<tr data-case="' + esc(item.id) + '">' +
        '<td class="strong">' + esc(item.number) + "</td>" +
        "<td><div class=\"strong\">" + esc(item.client_name) + "</div>" +
        '<div class="muted">' + esc(item.client_phone) + "</div></td>" +
        "<td>" + esc(item.project || "—") +
        (item.developer ? '<div class="muted">' + esc(item.developer) + "</div>" : "") + "</td>" +
        "<td>" + esc(item.service_title) + '<div class="muted">' + esc(item.region_title) + "</div></td>" +
        "<td>" + stagePill(item) + "</td>" +
        "<td>" + esc(item.lawyer_name || "—") + "</td>" +
        "<td>" + deadlinePill(item.deadline) + "</td>" +
        '<td class="num">' + esc(item.amount_claimed_display || "—") + "</td>" +
        "</tr>";
    }).join("");

    all("[data-case]").forEach(function (row) {
      on(row, "click", function () { openCase(row.dataset.case); });
    });
  }

  function currentFilters(extra) {
    var params = new URLSearchParams();
    if ($("f-search").value.trim()) params.set("q", $("f-search").value.trim());
    if ($("f-stage").value) params.set("stage", $("f-stage").value);
    if ($("f-lawyer").value) params.set("lawyer_id", $("f-lawyer").value);
    if ($("f-region").value) params.set("region", $("f-region").value);
    Object.keys(extra || {}).forEach(function (key) { params.set(key, extra[key]); });
    return params.toString();
  }

  function loadCases(extra) {
    $("view-case").hidden = true;
    $("view-cases").hidden = false;
    $("view-leads").hidden = true;

    return Promise.all([
      api("/api/v1/cases?" + currentFilters(extra)),
      api("/api/v1/dashboard")
    ]).then(function (results) {
      state.cases = results[0].items;
      renderCases(state.cases);
      renderTiles(results[1]);
    }).catch(function (error) { toast("error", error.message); });
  }

  // --- заявки ----------------------------------------------------------------

  function loadLeads() {
    return api("/api/v1/leads?limit=100").then(function (data) {
      state.leads = data.items;
      $("leads-empty").hidden = data.items.length > 0;
      $("leads-body").innerHTML = data.items.map(function (lead) {
        var done = lead.status === "converted";
        return "<tr>" +
          "<td>" + esc(ruDateTime(lead.created_at)) + "</td>" +
          '<td class="strong">' + esc(lead.name) + "</td>" +
          "<td>" + esc(lead.phone) + "</td>" +
          "<td>" + esc(lead.topic === "defects" ? "Недостатки отделки" : "Неустойка") + "</td>" +
          "<td>" + esc(lead.project || "—") + "</td>" +
          '<td class="num">' + esc(lead.calculation_total || "—") + "</td>" +
          "<td>" + (done
            ? '<span class="pill pill--done">Дело заведено</span>'
            : '<button type="button" class="btn btn--outline btn--sm" data-convert="' +
              esc(lead.id) + '">Завести дело</button>') + "</td>" +
          "</tr>";
      }).join("");

      all("[data-convert]").forEach(function (button) {
        on(button, "click", function () {
          button.disabled = true;
          api("/api/v1/leads/" + button.dataset.convert + "/convert", { method: "POST", body: {} })
            .then(function (created) {
              toast("ok", "Дело № " + created.number + " заведено");
              openCase(created.id);
            })
            .catch(function (error) { toast("error", error.message); button.disabled = false; });
        });
      });
    }).catch(function (error) { toast("error", error.message); });
  }

  // --- карточка дела ---------------------------------------------------------

  function field(label, name, value, type, options) {
    var input;
    if (type === "select") {
      input = '<select data-field="' + name + '">' + options.map(function (option) {
        var selected = String(option.value) === String(value == null ? "" : value) ? " selected" : "";
        return '<option value="' + esc(option.value) + '"' + selected + ">" + esc(option.title) + "</option>";
      }).join("") + "</select>";
    } else if (type === "textarea") {
      input = '<textarea data-field="' + name + '">' + esc(value || "") + "</textarea>";
    } else {
      input = '<input type="' + (type || "text") + '" data-field="' + name +
        '" value="' + esc(value == null ? "" : value) + '">';
    }
    return '<div class="field"><label>' + esc(label) + "</label>" + input + "</div>";
  }

  function optionsFrom(list, key, title) {
    return [{ value: "", title: "—" }].concat(list.map(function (item) {
      return { value: item[key], title: item[title] };
    }));
  }

  function renderCase(data) {
    state.current = data;
    var meta = state.meta;
    var money = meta.can_see_money;

    var stageOptions = meta.stages.map(function (stage) {
      return '<option value="' + esc(stage.code) + '"' +
        (stage.code === data.stage ? " selected" : "") + ">" + esc(stage.title) + "</option>";
    }).join("");

    var html =
      '<div class="case__head">' +
      "<div>" +
      '<button type="button" class="btn btn--quiet btn--sm" id="case-back" style="margin-bottom:6px">' +
      '<svg width="14" height="14"><use href="#i-left"/></svg> Все дела</button>' +
      '<h1 class="case__title">Дело № ' + esc(data.number) + " · " + esc(data.client_name) + "</h1>" +
      '<p class="case__meta">' + esc(data.service_title) + " · " + esc(data.region_title) +
      " · заведено " + esc(ruDateTime(data.created_at)) + "</p>" +
      "</div>" +
      '<div class="case__actions">' +
      '<select id="case-stage" style="width:auto">' + stageOptions + "</select>" +
      (data.calculation_id
        ? '<a class="btn btn--outline btn--sm" target="_blank" rel="noopener" href="/api/v1/calc/' +
          esc(data.calculation_id) + '/print">Расчёт для суда</a>' : "") +
      "</div></div>";

    html += '<div class="cols"><div>';

    html += '<div class="card"><h2>Клиент</h2><div class="grid2">' +
      field("ФИО", "client_name", data.client_name) +
      field("Телефон", "client_phone", data.client_phone) +
      field("Почта", "client_email", data.client_email, "email") +
      field("Регион", "region", data.region, "select", optionsFrom(meta.regions, "code", "title")) +
      "</div></div>";

    html += '<div class="card"><h2>Объект и договор</h2><div class="grid2">' +
      field("ЖК", "project", data.project) +
      field("Квартира", "apartment", data.apartment) +
      field("Застройщик", "developer_name", data.developer) +
      field("Номер ДДУ", "contract_number", data.contract_number) +
      field("Дата ДДУ", "contract_date", data.contract_date, "date") +
      field("Цена ДДУ, ₽", "contract_price", data.contract_price) +
      field("Срок передачи по договору", "due_date", data.due_date, "date") +
      field("Дата фактической передачи", "actual_transfer_date", data.actual_transfer_date, "date") +
      "</div></div>";

    html += '<div class="card"><h2>Претензия и суд</h2><div class="grid2">' +
      field("Претензия направлена", "claim_sent_on", data.claim_sent_on, "date") +
      field("Срок ответа", "claim_response_deadline", data.claim_response_deadline, "date") +
      field("Суд", "court_name", data.court_name) +
      field("Номер дела в суде", "court_case_number", data.court_case_number) +
      field("Дата заседания", "next_hearing_on", data.next_hearing_on, "date") +
      field("Срок обжалования", "appeal_deadline", data.appeal_deadline, "date") +
      "</div></div>";

    html += '<div class="card"><h2>Деньги</h2><div class="grid2">' +
      field("Заявлено, ₽", "amount_claimed", data.amount_claimed) +
      field("Присуждено, ₽", "amount_awarded", data.amount_awarded) +
      field("Получено, ₽", "amount_received", data.amount_received) +
      (money ? field("Гонорар, ₽", "fee", data.fee) : "") +
      "</div></div>";

    html += "</div><div>";

    html += '<div class="card"><h2>Ведение</h2><div class="grid2">' +
      field("Ответственный юрист", "lawyer_id", data.lawyer_id, "select",
        optionsFrom(meta.users, "id", "name")) +
      field("Тип услуги", "service_type", data.service_type, "select",
        meta.services.map(function (s) { return { value: s.code, title: s.title }; })) +
      '<div class="wide">' + field("Комментарий", "comment", data.comment, "textarea") + "</div>" +
      "</div></div>";

    html += '<div class="card"><h2>Лента дела</h2>' +
      '<div class="field" style="margin-bottom:14px">' +
      '<textarea id="note-text" placeholder="Что произошло по делу"></textarea>' +
      '<button type="button" class="btn btn--outline btn--sm" id="note-add" style="align-self:flex-start;margin-top:8px">Добавить запись</button>' +
      "</div>" +
      '<div class="feed">' + data.events.map(function (event) {
        return '<div class="feed__item" data-kind="' + esc(event.kind) + '">' +
          '<span class="feed__dot"></span><div>' +
          '<div class="feed__text">' + esc(event.text) + "</div>" +
          '<div class="feed__meta">' + esc(event.author) + " · " + esc(ruDateTime(event.created_at)) + "</div>" +
          "</div></div>";
      }).join("") + "</div></div>";

    html += "</div></div>";

    $("view-case").innerHTML = html;
    $("view-cases").hidden = true;
    $("view-leads").hidden = true;
    $("view-case").hidden = false;
    window.scrollTo({ top: 0 });

    on($("case-back"), "click", function () { loadCases(); });
    on($("case-stage"), "change", function () {
      api("/api/v1/cases/" + data.id + "/stage", { method: "POST", body: { stage: this.value } })
        .then(function (updated) { renderCase(updated); toast("ok", "Стадия обновлена"); })
        .catch(function (error) { toast("error", error.message); });
    });
    on($("note-add"), "click", function () {
      var text = $("note-text").value.trim();
      if (!text) return;
      api("/api/v1/cases/" + data.id + "/notes", { method: "POST", body: { text: text } })
        .then(function (updated) { renderCase(updated); })
        .catch(function (error) { toast("error", error.message); });
    });

    all("[data-field]").forEach(function (input) {
      on(input, "change", function () { saveField(data.id, input); });
    });
  }

  function saveField(caseId, input) {
    var name = input.dataset.field;
    var value = input.value.trim();
    var body = {};
    body[name] = value === "" ? null : value;

    api("/api/v1/cases/" + caseId, { method: "PATCH", body: body })
      .then(function (updated) {
        // Перерисовываем целиком: правка поля может изменить срок и ленту.
        renderCase(updated);
        toast("ok", "Сохранено");
      })
      .catch(function (error) {
        toast("error", error.message);
        openCase(caseId);
      });
  }

  function openCase(caseId) {
    api("/api/v1/cases/" + caseId)
      .then(renderCase)
      .catch(function (error) { toast("error", error.message); });
  }

  // --- новое дело ------------------------------------------------------------

  function newCaseModal() {
    var meta = state.meta;
    var box = document.createElement("div");
    box.className = "modal";
    box.innerHTML =
      '<div class="modal__box">' +
      '<h2 class="modal__title">Новое дело</h2>' +
      '<p class="modal__sub">Остальное заполните в карточке — сейчас нужен только клиент.</p>' +
      '<div class="grid2">' +
      field("ФИО клиента", "client_name", "") +
      field("Телефон", "client_phone", "", "tel") +
      field("Тип услуги", "service_type", "delay", "select",
        meta.services.map(function (s) { return { value: s.code, title: s.title }; })) +
      field("Регион", "region", "msk", "select",
        meta.regions.map(function (r) { return { value: r.code, title: r.title }; })) +
      field("ЖК", "project", "") +
      field("Застройщик", "developer_name", "") +
      "</div>" +
      '<div id="modal-error"></div>' +
      '<div class="modal__actions">' +
      '<button type="button" class="btn btn--outline" data-close>Отмена</button>' +
      '<button type="button" class="btn btn--solid" data-save>Завести дело</button>' +
      "</div></div>";

    $("modal-root").appendChild(box);

    var close = function () { box.remove(); };
    on(box.querySelector("[data-close]"), "click", close);
    on(box, "click", function (event) { if (event.target === box) close(); });

    on(box.querySelector("[data-save]"), "click", function () {
      var payload = {};
      Array.prototype.forEach.call(box.querySelectorAll("[data-field]"), function (input) {
        var value = input.value.trim();
        if (value) payload[input.dataset.field] = value;
      });
      if (!payload.client_name || !payload.client_phone) {
        box.querySelector("#modal-error").innerHTML =
          '<div class="note-box note-box--error">Укажите имя и телефон клиента.</div>';
        return;
      }
      api("/api/v1/cases", { method: "POST", body: payload })
        .then(function (created) {
          close();
          toast("ok", "Дело № " + created.number + " заведено");
          renderCase(created);
        })
        .catch(function (error) {
          box.querySelector("#modal-error").innerHTML =
            '<div class="note-box note-box--error">' + esc(error.message) + "</div>";
        });
    });

    box.querySelector("[data-field]").focus();
  }

  // --- запуск ----------------------------------------------------------------

  function fillFilters() {
    var meta = state.meta;
    $("f-stage").innerHTML = '<option value="">Все стадии</option>' + meta.stages.map(function (s) {
      return '<option value="' + esc(s.code) + '">' + esc(s.title) + "</option>";
    }).join("");
    $("f-lawyer").innerHTML = '<option value="">Все юристы</option>' + meta.users.map(function (u) {
      return '<option value="' + esc(u.id) + '">' + esc(u.name) + "</option>";
    }).join("");
    $("f-region").innerHTML = '<option value="">Все регионы</option>' + meta.regions.map(function (r) {
      return '<option value="' + esc(r.code) + '">' + esc(r.title) + "</option>";
    }).join("");
  }

  function start() {
    return api("/api/v1/auth/me").then(function (user) {
      state.user = user;
      $("who-name").textContent = user.name;
      $("who-role").textContent = user.role_title;
      return api("/api/v1/meta");
    }).then(function (meta) {
      state.meta = meta;
      fillFilters();
      showApp();
      switchTab("cases");
    });
  }

  function init() {
    on($("form-login"), "submit", function (event) {
      event.preventDefault();
      var button = $("login-submit");
      button.disabled = true;
      button.textContent = "Входим…";
      api("/api/v1/auth/login", {
        method: "POST",
        body: { email: $("login-email").value.trim(), password: $("login-password").value }
      }).then(function (data) {
        setToken(data.token);
        $("login-password").value = "";
        return start();
      }).catch(function (error) {
        $("login-error").innerHTML =
          '<div class="note-box note-box--error">' + esc(error.message) + "</div>";
      }).then(function () {
        button.disabled = false;
        button.textContent = "Войти";
      });
    });

    on($("logout"), "click", function () {
      api("/api/v1/auth/logout", { method: "POST" }).catch(function () { /* всё равно выходим */ });
      setToken("");
      showLogin();
    });

    on($("theme-toggle"), "click", function () {
      var explicit = document.documentElement.getAttribute("data-theme");
      var isDark = explicit
        ? explicit === "dark"
        : window.matchMedia("(prefers-color-scheme: dark)").matches;
      var next = isDark ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("calc-theme", next); } catch (e) { /* приватный режим */ }
    });

    all(".tab").forEach(function (button) {
      on(button, "click", function () { switchTab(button.dataset.tab); });
    });

    on($("btn-new-case"), "click", newCaseModal);

    var searchTimer = null;
    on($("f-search"), "input", function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () { loadCases(); }, 300);
    });
    ["f-stage", "f-lawyer", "f-region"].forEach(function (id) {
      on($(id), "change", function () { loadCases(); });
    });

    if (token()) {
      start().catch(function () { showLogin(); });
    } else {
      showLogin();
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
