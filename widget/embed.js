/**
 * Встраивание калькулятора на существующий сайт одним тегом.
 *
 *   <div id="garant-calc"></div>
 *   <script src="https://calc.garantlc.ru/embed.js"
 *           data-target="garant-calc"
 *           data-policy-url="https://garantlc.ru/policy"></script>
 *
 * Если data-target не указан, iframe вставляется на место самого тега.
 * Высота подстраивается автоматически по сообщениям из виджета.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  if (!script) return;

  var origin = new URL(script.src, window.location.href).origin;
  var params = new URLSearchParams();
  if (script.dataset.policyUrl) params.set("policy", script.dataset.policyUrl);
  if (script.dataset.policyVersion) params.set("policy_version", script.dataset.policyVersion);
  if (script.dataset.mode) params.set("mode", script.dataset.mode);

  var query = params.toString();
  var iframe = document.createElement("iframe");
  iframe.src = origin + "/widget/index.html" + (query ? "?" + query : "");
  iframe.title = "Калькулятор неустойки по 214-ФЗ";
  iframe.loading = "lazy";
  iframe.setAttribute("scrolling", "no");
  iframe.style.cssText = "width:100%;border:0;display:block;min-height:640px;overflow:hidden";

  var target = script.dataset.target ? document.getElementById(script.dataset.target) : null;
  if (target) {
    target.appendChild(iframe);
  } else if (script.parentNode) {
    script.parentNode.insertBefore(iframe, script.nextSibling);
  }

  window.addEventListener("message", function (event) {
    if (event.origin !== origin) return;
    var data = event.data;
    if (!data || data.type !== "garant-calc-height") return;
    if (event.source !== iframe.contentWindow) return;
    var height = parseInt(data.height, 10);
    if (height > 0) iframe.style.height = height + 24 + "px";
  });
})();
