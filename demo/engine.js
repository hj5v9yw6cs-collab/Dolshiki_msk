/**
 * Расчётное ядро для автономной демо-версии калькулятора.
 *
 * Это ПОРТ серверного ядра (backend/app/core/calculator) на JavaScript.
 * Нужен ровно для одного: чтобы демо-страницу можно было открыть без
 * бэкенда и потыкать вживую. Боевой виджет считает на сервере — здесь
 * повторена та же механика, чтобы демо показывало настоящие цифры.
 *
 * Совпадение с сервером проверяется скриптом demo/parity_check.py: он
 * прогоняет обе реализации по набору случаев и сравнивает результаты
 * до копейки. При правке ядра на сервере — правьте и здесь, затем
 * перезапустите проверку.
 *
 * Деньги считаются в копейках через BigInt: точная рациональная
 * арифметика без плавающей точки, округление до копеек — банковское,
 * как в Decimal.ROUND_HALF_EVEN.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.CalcEngine = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var DAY_MS = 86400000;

  // --- даты как целые номера дней -----------------------------------------

  function toDay(iso) {
    var parts = String(iso).slice(0, 10).split("-");
    return Math.floor(Date.UTC(+parts[0], +parts[1] - 1, +parts[2]) / DAY_MS);
  }

  function fromDay(day) {
    return new Date(day * DAY_MS).toISOString().slice(0, 10);
  }

  function displayDay(day) {
    var d = new Date(day * DAY_MS);
    var pad = function (n) { return n < 10 ? "0" + n : String(n); };
    return pad(d.getUTCDate()) + "." + pad(d.getUTCMonth() + 1) + "." + d.getUTCFullYear();
  }

  function todayDay() {
    var now = new Date();
    return Math.floor(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) / DAY_MS);
  }

  function daysIn(range) { return range.end - range.start + 1; }

  function makeRange(start, end) {
    return start > end ? null : { start: start, end: end };
  }

  /** Вычитает из base пересечения с cuts. */
  function subtract(base, cuts) {
    var result = [base];
    cuts.slice().sort(function (a, b) { return a.start - b.start; }).forEach(function (cut) {
      var next = [];
      result.forEach(function (segment) {
        if (segment.start > cut.end || cut.start > segment.end) { next.push(segment); return; }
        var left = makeRange(segment.start, Math.min(segment.end, cut.start - 1));
        var right = makeRange(Math.max(segment.start, cut.end + 1), segment.end);
        if (left) next.push(left);
        if (right) next.push(right);
      });
      result = next;
    });
    return result;
  }

  /** Режет segment по датам boundaries; граница — первый день нового куска. */
  function splitAt(segment, boundaries) {
    var points = boundaries
      .filter(function (b) { return b > segment.start && b <= segment.end; })
      .sort(function (a, b) { return a - b; });
    if (!points.length) return [segment];

    var pieces = [];
    var cursor = segment.start;
    points.forEach(function (point) {
      var piece = makeRange(cursor, point - 1);
      if (piece) pieces.push(piece);
      cursor = point;
    });
    var tail = makeRange(cursor, segment.end);
    if (tail) pieces.push(tail);
    return pieces;
  }

  // --- деньги в копейках (BigInt) -----------------------------------------

  /** Банковское округление дроби num/den до целого. */
  function divHalfEven(num, den) {
    var negative = num < 0n;
    if (negative) num = -num;
    var quotient = num / den;
    var doubled = (num % den) * 2n;
    if (doubled > den) quotient += 1n;
    else if (doubled === den && quotient % 2n === 1n) quotient += 1n;
    return negative ? -quotient : quotient;
  }

  /** '8500000' (рубли) -> 850000000n (копейки) */
  function rublesToKopecks(value) {
    var digits = String(value == null ? "0" : value).replace(/[^\d]/g, "");
    return BigInt(digits || "0") * 100n;
  }

  /** Число с двумя знаками -> целое, умноженное на 100. '8.5' -> 850 */
  function scale2(value) {
    var text = String(value).replace(",", ".");
    var parts = text.split(".");
    var whole = parts[0] || "0";
    var fraction = (parts[1] || "").padEnd(2, "0").slice(0, 2);
    var sign = whole.startsWith("-") ? -1 : 1;
    return sign * (Math.abs(parseInt(whole, 10)) * 100 + parseInt(fraction, 10));
  }

  /** Сырое значение как у сервера: 1208333n -> '12083.33' */
  function rawMoney(kopecks) {
    var negative = kopecks < 0n;
    if (negative) kopecks = -kopecks;
    return (negative ? "-" : "") + (kopecks / 100n).toString() + "." +
      (kopecks % 100n).toString().padStart(2, "0");
  }

  function formatMoney(kopecks) {
    var negative = kopecks < 0n;
    if (negative) kopecks = -kopecks;
    var whole = (kopecks / 100n).toString();
    var cents = (kopecks % 100n).toString().padStart(2, "0");
    var groups = [];
    while (whole.length > 3) {
      groups.unshift(whole.slice(-3));
      whole = whole.slice(0, -3);
    }
    groups.unshift(whole);
    return (negative ? "-" : "") + groups.join(" ") + "," + cents;
  }

  /** 850 -> '8,5'; 2100 -> '21' */
  function formatScaled(value) {
    var whole = Math.trunc(value / 100);
    var fraction = Math.abs(value % 100);
    if (fraction === 0) return String(whole);
    var text = String(fraction).padStart(2, "0").replace(/0+$/, "");
    return whole + "," + text;
  }

  function pluralDays(count) {
    if (count % 100 >= 11 && count % 100 <= 14) return "дней";
    var last = count % 10;
    if (last === 1) return "день";
    if (last >= 2 && last <= 4) return "дня";
    return "дней";
  }

  // --- конфиг ---------------------------------------------------------------

  function prepareConfig(raw) {
    var rates = (raw.cbr_rates.items || [])
      .map(function (item) { return { from: toDay(item.from), rate: scale2(item.rate) }; })
      .sort(function (a, b) { return a.from - b.from; });

    var named = function (items) {
      return (items || []).map(function (item) {
        return {
          start: toDay(item.from),
          end: toDay(item.to),
          basis: item.basis || "",
          note: item.note || "",
          maxRate: item.max_rate == null ? null : scale2(item.max_rate),
          review: item.requires_lawyer_review !== false
        };
      }).sort(function (a, b) { return a.start - b.start; });
    };

    var work = raw.working_days || {};
    var toDaySet = function (list) {
      var set = {};
      (list || []).forEach(function (value) { set[toDay(value)] = true; });
      return set;
    };

    return {
      version: raw.version || 0,
      disclaimer: raw.disclaimer || "",
      workdays: {
        apply: work.apply_article_193 === true,
        weekend: work.weekend_weekdays || [5, 6],
        holidays: (work.holidays_every_year || []).reduce(function (acc, value) {
          acc[value] = true; return acc;
        }, {}),
        extraNonWorking: toDaySet(work.extra_non_working),
        workingExceptions: toDaySet(work.working_exceptions),
        basis: work.basis || "",
        review: work.requires_lawyer_review !== false
      },
      dayCount: {
        mode: (raw.day_count_rule || {}).mode || "inclusive_both_ends",
        offset: (raw.day_count_rule || {}).start_offset_days,
        review: (raw.day_count_rule || {}).requires_lawyer_review !== false
      },
      rates: rates,
      ratesReview: raw.cbr_rates.requires_lawyer_review !== false,
      ratesSource: raw.cbr_rates.source || "",
      moratoriums: named(raw.moratoriums),
      rateCaps: named(raw.rate_caps),
      delay: {
        divisor: BigInt((raw.delay_penalty || {}).divisor || 300),
        individual: BigInt((raw.delay_penalty || {}).individual_multiplier || 2),
        legalEntity: BigInt((raw.delay_penalty || {}).legal_entity_multiplier || 1),
        basis: (raw.delay_penalty || {}).basis || "",
        defaultRateMode: (raw.delay_penalty || {}).default_rate_mode || "on_obligation_date",
        review: (raw.delay_penalty || {}).requires_lawyer_review !== false
      },
      defects: {
        divisor: BigInt((raw.defects_penalty || {}).divisor || 150),
        multiplier: BigInt((raw.defects_penalty || {}).multiplier || 1),
        responseDays: (raw.defects_penalty || {}).response_period_days,
        capAtRepair: (raw.defects_penalty || {}).cap_at_repair_cost !== false,
        applyMoratoriums: (raw.defects_penalty || {}).apply_moratoriums !== false,
        basis: (raw.defects_penalty || {}).basis || "",
        review: (raw.defects_penalty || {}).requires_lawyer_review !== false
      },
      penalty: {
        percent: scale2((raw.consumer_penalty || {}).percent || 0),
        base: (raw.consumer_penalty || {}).base || "neustoyka_and_moral_harm",
        basis: (raw.consumer_penalty || {}).basis || "",
        note: (raw.consumer_penalty || {}).note || "",
        review: (raw.consumer_penalty || {}).requires_lawyer_review !== false
      }
    };
  }

  /** Номер дня недели: 0 — понедельник, как в Python. */
  function weekdayOf(day) {
    return (((day % 7) + 7) % 7 + 3) % 7;
  }

  function monthDay(day) {
    var d = new Date(day * DAY_MS);
    var pad = function (n) { return n < 10 ? "0" + n : String(n); };
    return pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate());
  }

  var RATE_MODE_TITLES = {
    on_obligation_date: "ставка на день исполнения обязательства по договору",
    on_actual_date: "ставка на дату фактической передачи объекта",
    on_claim_date: "ставка на дату подачи иска",
    manual: "ставка введена вручную",
    per_segment: "по каждому периоду — своя действовавшая ставка"
  };

  var REVIEW_TITLES = {
    day_count: "правило подсчёта дней просрочки",
    rates: "история ключевой ставки ЦБ",
    delay_penalty: "формула неустойки за просрочку передачи",
    defects_penalty: "формула неустойки по недостаткам",
    consumer_penalty: "размер штрафа в пользу потребителя",
    workdays: "перенос срока с нерабочего дня (ст. 193 ГК РФ)"
  };

  function CalcError(message) {
    var error = new Error(message);
    error.isCalcError = true;
    return error;
  }

  function createEngine(rawConfig) {
    var config = prepareConfig(rawConfig);

    function isNonWorking(day) {
      var rules = config.workdays;
      if (rules.workingExceptions[day]) return false;
      if (rules.extraNonWorking[day]) return true;
      if (rules.weekend.indexOf(weekdayOf(day)) !== -1) return true;
      return rules.holidays[monthDay(day)] === true;
    }

    /** Перенос срока с нерабочего дня — ст. 193 ГК РФ. */
    function shiftDueDate(due) {
      if (!config.workdays.apply) return { day: due, note: null };
      var shifted = due;
      for (var i = 0; i < 30; i++) {
        if (!isNonWorking(shifted)) break;
        shifted += 1;
      }
      if (shifted === due) return { day: due, note: null };
      return {
        day: shifted,
        note: "Срок передачи по договору (" + displayDay(due) + ") выпал на нерабочий день и перенесён на "
          + displayDay(shifted) + " — " + config.workdays.basis + "."
      };
    }

    function rateOn(day) {
      var applicable = null;
      for (var i = 0; i < config.rates.length; i++) {
        if (config.rates[i].from <= day) applicable = config.rates[i];
        else break;
      }
      if (!applicable) {
        throw CalcError(
          "В конфиге нет ключевой ставки на " + fromDay(day) +
          ": самая ранняя запись — " + fromDay(config.rates[0].from) + "."
        );
      }
      return applicable.rate;
    }

    function capFor(day) {
      for (var i = 0; i < config.rateCaps.length; i++) {
        var cap = config.rateCaps[i];
        if (cap.maxRate != null && day >= cap.start && day <= cap.end) return cap;
      }
      return null;
    }

    function effectiveRate(determinationDay, manualRate, rateMode) {
      var base;
      if (rateMode === "manual") {
        if (manualRate == null || manualRate === "") throw CalcError("Ставка не передана.");
        base = scale2(manualRate);
      } else {
        base = rateOn(determinationDay);
      }
      var cap = capFor(determinationDay);
      if (cap && base > cap.maxRate) {
        return { rate: cap.maxRate, before: base, basis: cap.basis };
      }
      return { rate: base, before: null, basis: null };
    }

    function delayPeriod(startFrom, endRaw) {
      var start = startFrom + config.dayCount.offset;
      var end = config.dayCount.mode === "exclusive_end" ? endRaw - 1 : endRaw;
      return makeRange(start, end);
    }

    function excludedPeriods(period) {
      var result = [];
      config.moratoriums.forEach(function (moratorium) {
        if (moratorium.start > period.end || period.start > moratorium.end) return;
        var overlap = makeRange(
          Math.max(period.start, moratorium.start),
          Math.min(period.end, moratorium.end)
        );
        if (overlap) {
          result.push({
            start: fromDay(overlap.start), end: fromDay(overlap.end),
            start_display: displayDay(overlap.start), end_display: displayDay(overlap.end),
            days: daysIn(overlap), days_display: daysIn(overlap) + " " + pluralDays(daysIn(overlap)),
            basis: moratorium.basis, note: moratorium.note
          });
        }
      });
      return result;
    }

    function buildRanges(period, applyMoratoriums, rateMode) {
      var pieces = applyMoratoriums
        ? subtract(period, config.moratoriums.map(function (m) { return { start: m.start, end: m.end }; }))
        : [period];
      if (rateMode !== "per_segment") return pieces;

      var boundaries = config.rates.map(function (entry) { return entry.from; });
      var result = [];
      pieces.forEach(function (piece) {
        result = result.concat(splitAt(piece, boundaries));
      });
      return result;
    }

    function determinationDay(rateMode, obligationDay, actualDay, claimDay, segmentStart) {
      if (rateMode === "on_actual_date") return actualDay;
      if (rateMode === "on_claim_date") {
        if (claimDay == null) throw CalcError("Для режима «ставка на дату подачи иска» нужно указать дату подачи.");
        return claimDay;
      }
      if (rateMode === "per_segment") return segmentStart;
      return obligationDay;
    }

    function segmentOf(range, baseKopecks, rateInfo, sourceDay, divisor, multiplier) {
      // Точная дробь: база × дни × ставка × множитель / (10000 × делитель)
      var numerator = baseKopecks * BigInt(daysIn(range)) * BigInt(rateInfo.rate) * multiplier;
      var amount = divHalfEven(numerator, 10000n * divisor);
      var days = daysIn(range);
      var multiplierPart = multiplier === 1n ? "" : " × " + multiplier.toString();
      return {
        start: fromDay(range.start), end: fromDay(range.end),
        start_display: displayDay(range.start), end_display: displayDay(range.end),
        days: days, days_display: days + " " + pluralDays(days),
        rate: formatScaled(rateInfo.rate), rate_display: formatScaled(rateInfo.rate) + "%",
        rate_source_date: fromDay(sourceDay), rate_source_date_display: displayDay(sourceDay),
        rate_before_cap: rateInfo.before == null ? null : formatScaled(rateInfo.before),
        cap_basis: rateInfo.basis,
        multiplier: multiplier.toString(), divisor: divisor.toString(),
        base_amount: rawMoney(baseKopecks), amount_kop: amount,
        amount: rawMoney(amount), amount_display: formatMoney(amount),
        formula: formatMoney(baseKopecks) + " × " + days + " " + pluralDays(days) +
          " × " + formatScaled(rateInfo.rate) + "% / " + divisor.toString() + multiplierPart +
          " = " + formatMoney(amount) + " ₽"
      };
    }

    function penaltyBase(neustoyka, moral, claim) {
      if (config.penalty.base === "neustoyka_only") return neustoyka;
      if (config.penalty.base === "claim_and_neustoyka_and_moral_harm") return neustoyka + moral + claim;
      return neustoyka + moral;
    }

    function extraLines(neustoyka, moralInput, claim, includePenalty, expenses) {
      var lines = [];
      var used = [];
      var moral = rublesToKopecks(moralInput);

      if (moral > 0n) {
        lines.push({
          code: "moral_harm", title: "Компенсация морального вреда", amount_kop: moral,
          basis: "ст. 15 Закона РФ «О защите прав потребителей»",
          note: "Размер определяется судом; указан заявляемый."
        });
      }

      if (includePenalty && config.penalty.percent > 0) {
        var base = penaltyBase(neustoyka, moral, claim);
        var amount = divHalfEven(base * BigInt(config.penalty.percent), 10000n);
        if (amount > 0n) {
          lines.push({
            code: "consumer_penalty",
            title: "Штраф " + formatScaled(config.penalty.percent) + "% в пользу потребителя",
            amount_kop: amount, basis: config.penalty.basis, note: config.penalty.note
          });
          used.push("consumer_penalty");
        }
      }

      (expenses || []).forEach(function (expense) {
        var amount = rublesToKopecks(expense.amount);
        if (amount > 0n) {
          lines.push({
            code: expense.code || "expense", title: expense.title,
            amount_kop: amount, basis: "судебные расходы", note: ""
          });
        }
      });

      return { lines: lines, used: used };
    }

    function warningsFor(used) {
      var flags = {
        day_count: config.dayCount.review, rates: config.ratesReview,
        delay_penalty: config.delay.review, defects_penalty: config.defects.review,
        consumer_penalty: config.penalty.review,
        workdays: config.workdays.review
      };
      return used.filter(function (key) { return flags[key]; }).map(function (key) {
        return "Параметр «" + REVIEW_TITLES[key] + "» не подтверждён юристом (requires_lawyer_review).";
      });
    }

    function finish(payload) {
      var total = payload.lines.reduce(function (sum, line) { return sum + line.amount_kop; }, 0n);
      return {
        mode: payload.mode,
        period: payload.period,
        // amount_kop — служебное BigInt-поле, наружу не отдаём: результат
        // должен оставаться сериализуемым в JSON.
        segments: payload.segments.map(function (segment) {
          var copy = {};
          Object.keys(segment).forEach(function (key) {
            if (key !== "amount_kop") copy[key] = segment[key];
          });
          return copy;
        }),
        excluded: payload.excluded,
        lines: payload.lines.map(function (line) {
          return {
            code: line.code, title: line.title, amount: rawMoney(line.amount_kop),
            amount_display: formatMoney(line.amount_kop), basis: line.basis || "", note: line.note || ""
          };
        }),
        total: rawMoney(total), total_display: formatMoney(total),
        rate_mode: payload.rateMode, rate_mode_title: RATE_MODE_TITLES[payload.rateMode] || "",
        warnings: warningsFor(payload.used), notes: payload.notes,
        disclaimer: config.disclaimer, config_version: config.version
      };
    }

    function emptyPeriod() {
      return { start: null, end: null, start_display: null, end_display: null, days: 0, days_display: "0 дней" };
    }

    function periodInfo(period, countedDays) {
      return {
        start: fromDay(period.start), end: fromDay(period.end),
        start_display: displayDay(period.start), end_display: displayDay(period.end),
        days: countedDays, days_display: countedDays + " " + pluralDays(countedDays)
      };
    }

    // --- Режим 1: просрочка передачи ---------------------------------------

    function calcDelay(input, today) {
      today = today == null ? todayDay() : today;
      var price = rublesToKopecks(input.contract_price);
      if (price <= 0n) throw CalcError("Цена договора должна быть больше нуля.");

      var dueDay = toDay(input.due_date);
      var actualDay = input.actual_date ? toDay(input.actual_date) : null;
      if (actualDay != null && actualDay > today) {
        throw CalcError("Дата фактической передачи не может быть в будущем.");
      }

      var rateMode = input.rate_mode || config.delay.defaultRateMode;
      if (!RATE_MODE_TITLES[rateMode]) throw CalcError("Неизвестный режим определения ставки: " + rateMode);

      var endRaw = actualDay == null ? today : actualDay;
      var shift = shiftDueDate(dueDay);
      dueDay = shift.day;
      var period = delayPeriod(dueDay, endRaw);
      var multiplier = input.is_individual === false ? config.delay.legalEntity : config.delay.individual;
      var used = ["day_count", "rates", "delay_penalty", "workdays"];

      if (!period) {
        var none = extraLines(0n, input.moral_harm, 0n, input.include_consumer_penalty !== false, input.expenses);
        return finish({
          mode: "delay", period: emptyPeriod(), segments: [], excluded: [],
          lines: none.lines, rateMode: rateMode, used: used.concat(none.used),
          notes: (shift.note ? [shift.note] : [])
            .concat(["Просрочка отсутствует: объект передан в срок или ранее срока по договору."])
        });
      }

      var excluded = excludedPeriods(period);
      var segments = buildRanges(period, true, rateMode).map(function (range) {
        var sourceDay = determinationDay(rateMode, dueDay, endRaw, input.claim_date ? toDay(input.claim_date) : null, range.start);
        return segmentOf(range, price, effectiveRate(sourceDay, input.manual_rate, rateMode),
          sourceDay, config.delay.divisor, multiplier);
      });

      var neustoyka = segments.reduce(function (sum, segment) { return sum + segment.amount_kop; }, 0n);
      var lines = [{
        code: "neustoyka", title: "Неустойка за нарушение срока передачи объекта",
        amount_kop: neustoyka, basis: config.delay.basis, note: ""
      }];
      var extras = extraLines(neustoyka, input.moral_harm, 0n, input.include_consumer_penalty !== false, input.expenses);
      lines = lines.concat(extras.lines);

      var notes = [];
      if (shift.note) notes.push(shift.note);
      if (actualDay == null) notes.push("Объект не передан: расчёт выполнен по " + displayDay(today) + ".");
      if (excluded.length) notes.push("Из расчёта исключены мораторные периоды — см. отдельную таблицу с основаниями.");

      var counted = segments.reduce(function (sum, segment) { return sum + segment.days; }, 0);
      return finish({
        mode: "delay", period: periodInfo(period, counted), segments: segments, excluded: excluded,
        lines: lines, rateMode: rateMode, used: used.concat(extras.used), notes: notes
      });
    }

    // --- Режим 2: недостатки отделки ---------------------------------------

    function calcDefects(input, today) {
      today = today == null ? todayDay() : today;
      var repair = rublesToKopecks(input.repair_cost);
      if (repair <= 0n) throw CalcError("Стоимость устранения недостатков должна быть больше нуля.");

      var servedDay = toDay(input.demand_served_date);
      var satisfiedDay = input.satisfied_date ? toDay(input.satisfied_date) : null;
      if (satisfiedDay != null && satisfiedDay > today) {
        throw CalcError("Дата удовлетворения требования не может быть в будущем.");
      }

      var rateMode = input.rate_mode || config.delay.defaultRateMode;
      if (!RATE_MODE_TITLES[rateMode]) throw CalcError("Неизвестный режим определения ставки: " + rateMode);

      var deadlineShift = shiftDueDate(servedDay + config.defects.responseDays);
      var deadline = deadlineShift.day;
      var endRaw = satisfiedDay == null ? today : satisfiedDay;
      var period = delayPeriod(deadline, endRaw);
      var used = ["day_count", "rates", "defects_penalty", "workdays"];

      var excluded = [];
      var segments = [];
      var neustoyka = 0n;
      var capped = false;

      if (period) {
        if (config.defects.applyMoratoriums) excluded = excludedPeriods(period);
        segments = buildRanges(period, config.defects.applyMoratoriums, rateMode).map(function (range) {
          var sourceDay = determinationDay(rateMode, deadline, endRaw, input.claim_date ? toDay(input.claim_date) : null, range.start);
          return segmentOf(range, repair, effectiveRate(sourceDay, input.manual_rate, rateMode),
            sourceDay, config.defects.divisor, config.defects.multiplier);
        });
        neustoyka = segments.reduce(function (sum, segment) { return sum + segment.amount_kop; }, 0n);
        if (config.defects.capAtRepair && neustoyka > repair) {
          neustoyka = repair;
          capped = true;
        }
      }

      var lines = [];
      var claim = 0n;
      if (input.include_repair_cost_in_total !== false) {
        claim = repair;
        lines.push({
          code: "repair_cost", title: "Стоимость устранения недостатков",
          amount_kop: claim, basis: "ст. 7 214-ФЗ, заключение эксперта", note: ""
        });
      }
      lines.push({
        code: "neustoyka", title: "Неустойка за просрочку удовлетворения требования",
        amount_kop: neustoyka, basis: config.defects.basis,
        note: capped ? "Ограничена стоимостью устранения недостатков." : ""
      });

      var expertise = rublesToKopecks(input.expertise_cost);
      if (expertise > 0n) {
        lines.push({
          code: "expertise", title: "Расходы на досудебную экспертизу",
          amount_kop: expertise, basis: "судебные издержки", note: ""
        });
      }

      var extras = extraLines(neustoyka, input.moral_harm, claim, input.include_consumer_penalty !== false, input.expenses);
      lines = lines.concat(extras.lines);

      var notes = [];
      if (deadlineShift.note) notes.push(deadlineShift.note);
      if (satisfiedDay == null) notes.push("Требование не удовлетворено: расчёт выполнен по " + displayDay(today) + ".");
      notes.push("Срок на удовлетворение требования — " + config.defects.responseDays +
        " дн., просрочка исчисляется с " + displayDay(deadline + config.dayCount.offset) + ".");
      if (capped) notes.push("Неустойка ограничена стоимостью устранения недостатков (правило из конфига).");
      if (excluded.length) notes.push("Из расчёта исключены мораторные периоды — см. таблицу с основаниями.");

      var counted = segments.reduce(function (sum, segment) { return sum + segment.days; }, 0);
      return finish({
        mode: "defects",
        period: period ? periodInfo(period, counted) : emptyPeriod(),
        segments: segments, excluded: excluded, lines: lines,
        rateMode: rateMode, used: used.concat(extras.used), notes: notes
      });
    }

    function rateStatus() {
      var latest = config.rates[config.rates.length - 1];
      return {
        rate: latest.rate / 100,
        effective_from: fromDay(latest.from),
        auto_sync: false,
        is_stale: true,
        source: config.ratesSource,
        requires_lawyer_review: config.ratesReview,
        warning: "Демо-версия: ставка взята из встроенной копии конфига и не синхронизируется с cbr.ru."
      };
    }

    return {
      calcDelay: calcDelay, calcDefects: calcDefects, rateStatus: rateStatus,
      config: config, toDay: toDay, todayDay: todayDay
    };
  }

  return {
    createEngine: createEngine,
    formatMoney: formatMoney,
    rawMoney: rawMoney,
    toDay: toDay,
    fromDay: fromDay
  };
});
