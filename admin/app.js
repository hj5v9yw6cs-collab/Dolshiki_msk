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

    html += '<div class="card"><h2>Документы</h2>' +
      '<label class="drop" id="drop">' +
      '<div class="drop__title">Перетащите файлы или нажмите, чтобы выбрать</div>' +
      '<div class="drop__hint">Договор, платёжки, акт, экспертиза, паспорт. До 25 МБ на файл</div>' +
      '<input type="file" id="file-input" multiple>' +
      "</label>" +
      '<div id="upload-status"></div>' +
      '<div class="docs" id="docs"></div></div>';

    html += '<div class="card"><h2>Комплектность</h2><div id="checklist"></div></div>';

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

    var drop = $("drop");
    var input = $("file-input");
    on(input, "change", function () {
      uploadFiles(data.id, input.files);
      input.value = "";
    });
    ["dragenter", "dragover"].forEach(function (name) {
      on(drop, name, function (event) {
        event.preventDefault();
        drop.dataset.over = "true";
      });
    });
    ["dragleave", "drop"].forEach(function (name) {
      on(drop, name, function (event) {
        event.preventDefault();
        drop.dataset.over = "false";
      });
    });
    on(drop, "drop", function (event) {
      uploadFiles(data.id, event.dataTransfer.files);
    });

    loadDocuments(data.id);
  }

  function renderDocuments(caseId, data) {
    var typeOptions = (state.docTypes || []).map(function (type) {
      return { value: type.code, title: type.title };
    });

    $("docs").innerHTML = data.items.length ? data.items.map(function (doc) {
      var extracted = Object.keys(doc.extracted || {});
      var chip = doc.needs_review
        ? '<span class="pill pill--soon">проверьте тип</span>' : "";
      var scan = doc.is_scan
        ? '<span class="pill">скан без текста</span>' : "";

      var extra = "";
      if (extracted.length && !doc.extracted_applied) {
        extra = '<div class="doc__extract"><span>Нашли в документе: <b>' +
          extracted.map(function (key) { return esc(FIELD_TITLES[key] || key); }).join(", ") +
          '</b></span><button type="button" class="btn btn--outline btn--sm" data-apply="' +
          esc(doc.id) + '">Перенести в карточку</button></div>';
      } else if (doc.extracted_applied) {
        extra = '<div class="doc__extract">Реквизиты перенесены в карточку</div>';
      }

      return '<div class="doc" data-review="' + doc.needs_review + '">' +
        "<div>" +
        '<div class="doc__name">' + esc(doc.stored_name) + " " + chip + " " + scan + "</div>" +
        '<div class="doc__meta">' + esc(doc.folder_title) + " · " + esc(doc.size_display) +
        " · " + esc(doc.uploaded_by) + " · " + esc(ruDateTime(doc.created_at)) + "</div>" +
        '<div class="doc__why">' + esc(doc.signals || "") + "</div>" +
        "</div>" +
        '<div class="doc__actions">' +
        '<select data-doctype="' + esc(doc.id) + '">' + typeOptions.map(function (option) {
          return '<option value="' + esc(option.value) + '"' +
            (option.value === doc.doc_type ? " selected" : "") + ">" + esc(option.title) + "</option>";
        }).join("") + "</select>" +
        (previewable(doc.stored_name)
          ? '<button type="button" class="btn btn--outline btn--sm" data-preview="' +
            esc(doc.id) + '">Смотреть</button>'
          : "") +
        '<a class="btn btn--outline btn--sm" href="/api/v1/documents/' + esc(doc.id) +
        '/file" data-download="' + esc(doc.id) + '">Скачать</a>' +
        '<button type="button" class="btn btn--quiet btn--sm" data-delete="' + esc(doc.id) +
        '">Удалить</button>' +
        "</div>" + extra + "</div>";
    }).join("") : '<div class="check__why">Документов пока нет</div>';

    var checklist = data.checklist;
    $("checklist").innerHTML =
      '<div class="check__summary" data-ready="' + checklist.ready + '">' +
      (checklist.ready
        ? "Комплект собран — можно двигаться дальше"
        : "Не хватает документов: " + checklist.missing_required + " из " + checklist.required_total) +
      "</div>" +
      '<div class="check">' + checklist.items.map(function (item) {
        return '<div class="check__item" data-present="' + item.present +
          '" data-optional="' + item.optional + '"><span class="check__mark"></span><div>' +
          esc(item.title) + (item.optional ? " <span class=\"check__why\">(если есть)</span>" : "") +
          '<div class="check__why">' + esc(item.why) + "</div></div></div>";
      }).join("") + "</div>";

    all("[data-doctype]").forEach(function (select) {
      on(select, "change", function () {
        api("/api/v1/documents/" + select.dataset.doctype, {
          method: "PATCH", body: { doc_type: select.value }
        }).then(function () {
          toast("ok", "Тип документа обновлён");
          loadDocuments(caseId);
        }).catch(function (error) { toast("error", error.message); });
      });
    });

    all("[data-delete]").forEach(function (button) {
      on(button, "click", function () {
        if (!window.confirm("Удалить документ? Файл будет стёрт с диска.")) return;
        api("/api/v1/documents/" + button.dataset.delete, { method: "DELETE" })
          .then(function () { toast("ok", "Документ удалён"); loadDocuments(caseId); })
          .catch(function (error) { toast("error", error.message); });
      });
    });

    all("[data-apply]").forEach(function (button) {
      on(button, "click", function () {
        api("/api/v1/documents/" + button.dataset.apply + "/apply", { method: "POST" })
          .then(function () { toast("ok", "Реквизиты перенесены"); openCase(caseId); })
          .catch(function (error) { toast("error", error.message); });
      });
    });

    // Скачивание идёт с токеном, поэтому обычная ссылка не подходит.
    all("[data-preview]").forEach(function (button) {
      on(button, "click", function () { previewDocument(button.dataset.preview); });
    });

    all("[data-download]").forEach(function (link) {
      on(link, "click", function (event) {
        event.preventDefault();
        downloadDocument(link.dataset.download);
      });
    });
  }

  // Открывается то, что браузер умеет показать сам. Word и Excel он не
  // показывает, поэтому для них кнопки просмотра нет — только скачивание.
  var PREVIEWABLE = [".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif"];

  function previewable(name) {
    var lower = String(name || "").toLowerCase();
    return PREVIEWABLE.some(function (suffix) { return lower.slice(-suffix.length) === suffix; });
  }

  function previewDocument(documentId) {
    var box = document.createElement("div");
    box.className = "modal";
    box.innerHTML =
      '<div class="modal__box modal__box--wide">' +
      '<h2 class="modal__title" id="preview-title">Документ</h2>' +
      '<div class="preview" id="preview-body">Загружаем…</div>' +
      '<div class="modal__actions">' +
      '<button type="button" class="btn btn--outline" data-close>Закрыть</button>' +
      "</div></div>";
    $("modal-root").appendChild(box);

    var url = null;
    var close = function () {
      // Ссылку на blob нужно отпустить руками, иначе файл клиента висит
      // в памяти вкладки до перезагрузки страницы.
      if (url) URL.revokeObjectURL(url);
      box.remove();
    };
    on(box.querySelector("[data-close]"), "click", close);
    on(box, "click", function (event) { if (event.target === box) close(); });

    fetch("/api/v1/documents/" + documentId + "/file", {
      headers: { Authorization: "Bearer " + token() }
    }).then(function (response) {
      if (!response.ok) throw new Error("Файл недоступен");
      return response.blob();
    }).then(function (blob) {
      url = URL.createObjectURL(blob);
      var body = box.querySelector("#preview-body");
      body.innerHTML = blob.type.indexOf("image/") === 0
        ? '<img src="' + url + '" alt="">'
        : '<iframe src="' + url + '" title="Документ"></iframe>';
    }).catch(function (error) {
      box.querySelector("#preview-body").innerHTML =
        '<div class="note-box note-box--error">' + esc(error.message) + "</div>";
    });
  }

  function downloadDocument(documentId) {
    fetch("/api/v1/documents/" + documentId + "/file", {
      headers: { Authorization: "Bearer " + token() }
    }).then(function (response) {
      if (!response.ok) throw new Error("Файл недоступен");
      var name = "document";
      var disposition = response.headers.get("content-disposition") || "";
      var match = disposition.match(/filename="?([^"]+)"?/);
      if (match) name = decodeURIComponent(match[1]);
      return response.blob().then(function (blob) {
        var url = URL.createObjectURL(blob);
        var link = document.createElement("a");
        link.href = url;
        link.download = name;
        link.click();
        URL.revokeObjectURL(url);
      });
    }).catch(function (error) { toast("error", error.message); });
  }

  function loadDocuments(caseId) {
    return api("/api/v1/cases/" + caseId + "/documents")
      .then(function (data) { renderDocuments(caseId, data); })
      .catch(function (error) { toast("error", error.message); });
  }

  function uploadFiles(caseId, files) {
    if (!files || !files.length) return;
    var status = $("upload-status");
    var queue = Array.prototype.slice.call(files);
    var done = 0;
    var failed = [];

    status.innerHTML = '<div class="note-box">Загружаем 0 из ' + queue.length + "…</div>";

    function next() {
      if (!queue.length) {
        status.innerHTML = failed.length
          ? '<div class="note-box note-box--error">Не удалось загрузить: ' +
            failed.map(esc).join("; ") + "</div>"
          : "";
        loadDocuments(caseId);
        return;
      }
      var file = queue.shift();
      var form = new FormData();
      form.append("file", file);

      fetch("/api/v1/cases/" + caseId + "/documents", {
        method: "POST",
        headers: { Authorization: "Bearer " + token() },
        body: form
      }).then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (body) {
          if (!response.ok) throw new Error(body.detail || "Ошибка загрузки");
          return body;
        });
      }).then(function () {
        done += 1;
      }).catch(function (error) {
        failed.push(file.name + " — " + error.message);
      }).then(function () {
        status.innerHTML = '<div class="note-box">Загружаем ' + (done + failed.length) +
          " из " + (done + failed.length + queue.length) + "…</div>";
        next();
      });
    }

    next();
  }

  var FIELD_TITLES = {
    contract_number: "номер ДДУ",
    contract_date: "дата ДДУ",
    contract_price: "цена ДДУ",
    apartment: "квартира",
    due_date: "срок передачи"
  };

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

  // --- смена пароля ----------------------------------------------------------

  function passwordModal() {
    var box = document.createElement("div");
    box.className = "modal";
    box.innerHTML =
      '<div class="modal__box">' +
      '<h2 class="modal__title">Смена пароля</h2>' +
      '<p class="modal__sub">Нужен текущий пароль. Остальные ваши входы закроются — ' +
      "на других устройствах придётся войти заново.</p>" +
      '<div class="grid2">' +
      field("Текущий пароль", "current_password", "", "password") +
      field("Новый пароль", "new_password", "", "password") +
      field("Новый пароль ещё раз", "repeat", "", "password") +
      "</div>" +
      '<div id="modal-error"></div>' +
      '<div class="modal__actions">' +
      '<button type="button" class="btn btn--outline" data-close>Отмена</button>' +
      '<button type="button" class="btn btn--solid" data-save>Сменить</button>' +
      "</div></div>";

    $("modal-root").appendChild(box);

    var close = function () { box.remove(); };
    var fail = function (text) {
      box.querySelector("#modal-error").innerHTML =
        '<div class="note-box note-box--error">' + esc(text) + "</div>";
    };
    var value = function (name) {
      return box.querySelector('[data-field="' + name + '"]').value;
    };

    on(box.querySelector("[data-close]"), "click", close);
    on(box, "click", function (event) { if (event.target === box) close(); });

    on(box.querySelector("[data-save]"), "click", function () {
      if (value("new_password") !== value("repeat")) {
        fail("Новые пароли не совпали.");
        return;
      }
      api("/api/v1/auth/password", {
        method: "POST",
        body: { current_password: value("current_password"), new_password: value("new_password") }
      })
        .then(function () {
          close();
          toast("ok", "Пароль изменён");
        })
        .catch(function (error) { fail(error.message); });
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
      return Promise.all([api("/api/v1/meta"), api("/api/v1/documents/meta")]);
    }).then(function (results) {
      var meta = results[0];
      state.docTypes = results[1].types;
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

    on($("change-password"), "click", passwordModal);

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

    on($("btn-export"), "click", function () {
      var params = currentFilters();
      fetch("/api/v1/cases.xlsx" + (params ? "?" + params : ""), {
        headers: { Authorization: "Bearer " + token() }
      }).then(function (response) {
        if (!response.ok) throw new Error("Не удалось выгрузить реестр");
        return response.blob();
      }).then(function (blob) {
        var url = URL.createObjectURL(blob);
        var link = document.createElement("a");
        link.href = url;
        link.download = "reestr-del.xlsx";
        link.click();
        URL.revokeObjectURL(url);
        toast("ok", "Реестр выгружен");
      }).catch(function (error) { toast("error", error.message); });
    });

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
