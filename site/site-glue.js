/**
 * Приём заявки без сервера.
 *
 * На бесплатном варианте заявки некуда складывать, поэтому калькулятор
 * готовит сообщение в WhatsApp: имя, телефон, объект и сумма расчёта.
 * Человеку остаётся нажать кнопку и отправить, юристу — прочитать.
 *
 * Переход именно по кнопке, а не автоматически: окно, открытое из
 * асинхронного кода, браузеры блокируют как всплывающее.
 *
 * Когда появится сервер, этот файл убирается из сборки и заявки начинают
 * падать в базу — интерфейс при этом не меняется.
 */
(function () {
  "use strict";

  var contact = window.SITE_CONTACT || {};
  var pending = null;

  var REGIONS = {
    msk: "Москва и область",
    kzn: "Казань и Татарстан", other: "другой регион"
  };

  function message(lead, result) {
    var lines = ["Здравствуйте! Считал на сайте по 214-ФЗ."];

    if (result) {
      lines.push((result.mode === "delay"
        ? "Неустойка за просрочку передачи: "
        : "Недостатки отделки: ") + result.total_display + " ₽.");
      var period = result.period || {};
      if (period.start_display) {
        lines.push("Период: " + period.start_display + " — " + period.end_display +
          ", засчитано " + period.days_display + ".");
      }
    }

    lines.push("");
    lines.push("Меня зовут: " + lead.name);
    lines.push("Телефон: " + lead.phone);
    if (lead.project) lines.push("Объект: " + lead.project);
    if (lead.region) lines.push("Регион: " + (REGIONS[lead.region] || lead.region));
    return lines.join("\n");
  }

  window.CALC_LEAD_HANDLER = function (lead, result) {
    var text = encodeURIComponent(message(lead, result));
    if (contact.whatsapp) {
      pending = { url: "https://wa.me/" + contact.whatsapp + "?text=" + text, label: "Открыть WhatsApp с расчётом" };
    } else if (contact.telegram) {
      pending = { url: "https://t.me/" + contact.telegram, label: "Написать в Telegram" };
    } else {
      pending = null;
    }
    return { ok: true, id: null };
  };

  window.CALC_LEAD_ACTION = function () { return pending; };

  window.CALC_LEAD_SUCCESS = {
    title: "Расчёт готов к отправке",
    text: contact.phone
      ? "Нажмите кнопку — откроется переписка с уже готовым сообщением. Или позвоните: " + contact.phone
      : "Нажмите кнопку — откроется переписка с уже готовым сообщением."
  };
})();
