(function (global) {
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (key) {
      if (attrs[key] === null || attrs[key] === undefined) {
        return;
      }
      if (key === "className") {
        node.className = attrs[key];
      } else if (key === "text") {
        node.textContent = attrs[key];
      } else {
        node.setAttribute(key, String(attrs[key]));
      }
    });
    (children || []).forEach(function (child) {
      if (child) {
        node.appendChild(child);
      }
    });
    return node;
  }

  function renderMetric(col, container) {
    var label = col.label || col.formula || "Metric";
    var box = el("div", { className: "card" }, [
      el("div", { className: "card-body" }, [
        el("div", { className: "text-muted small", text: label }),
        el("div", { className: "h3 mb-0", text: "…", id: "metric-" + col.formula }),
      ]),
    ]);
    container.appendChild(box);
    fetch("/api/formulas/" + encodeURIComponent(col.formula))
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        var node = document.getElementById("metric-" + col.formula);
        if (node) {
          node.textContent = data.value == null ? "—" : String(data.value);
        }
      })
      .catch(function () {});
  }

  function renderNotices(container) {
    var card = el("div", { className: "card" }, [
      el("div", { className: "card-header", text: "Notices" }),
      el("div", { className: "list-group list-group-flush", id: "layout-notices" }),
    ]);
    container.appendChild(card);
    fetch("/api/notices")
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        var list = document.getElementById("layout-notices");
        if (!list) {
          return;
        }
        list.textContent = "";
        (data.notices || []).slice(0, 10).forEach(function (n) {
          var item = el("div", { className: "list-group-item" }, [
            el("strong", { text: n.title }),
            el("div", { className: "small text-muted", text: n.body || "" }),
          ]);
          if (n.reminder_id) {
            var actions = el("div", { className: "mt-1" });
            var snooze = el("button", { className: "btn btn-sm btn-outline-secondary me-1", text: "Snooze 15m" });
            snooze.addEventListener("click", function () {
              fetch("/api/reminders/" + encodeURIComponent(n.reminder_id) + "/snooze", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ minutes: 15 }),
              });
            });
            actions.appendChild(snooze);
            item.appendChild(actions);
          }
          list.appendChild(item);
        });
      });
  }

  function renderText(col, container) {
    container.appendChild(el("p", { className: "mb-0", text: col.label || "" }));
  }

  function renderLayout(layout, target) {
    while (target.firstChild) {
      target.removeChild(target.firstChild);
    }
    var title = el("h2", { className: "h4", text: layout.title || layout.id });
    target.appendChild(title);
    (layout.rows || []).forEach(function (row) {
      var rowEl = el("div", { className: "row mb-3" });
      (row.cols || []).forEach(function (col) {
        var span = col.span || 12;
        var colEl = el("div", { className: "col-md-" + String(span) });
        var widget = col.widget;
        if (widget === "metric") {
          renderMetric(col, colEl);
        } else if (widget === "notices") {
          renderNotices(colEl);
        } else if (widget === "text") {
          renderText(col, colEl);
        } else if (widget === "table" && col.screen) {
          colEl.appendChild(el("a", { href: "#list/" + col.table, text: "Open " + (col.table || "list") }));
        } else {
          colEl.appendChild(el("p", { className: "text-muted", text: widget || "widget" }));
        }
        rowEl.appendChild(colEl);
      });
      target.appendChild(rowEl);
    });
  }

  global.DesktopperLayout = { render: renderLayout };
})(window);
