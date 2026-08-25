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

  function clear(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function renderMetric(col, container) {
    var label = col.label || col.formula || "Metric";
    var valueId = "metric-" + col.formula;
    var box = el("div", { className: "card" }, [
      el("div", { className: "card-body" }, [
        el("div", { className: "text-muted small", text: label }),
        el("div", { className: "h3 mb-0", text: "…", id: valueId }),
      ]),
    ]);
    container.appendChild(box);
    fetch("/api/formulas/" + encodeURIComponent(col.formula))
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        var node = document.getElementById(valueId);
        if (node) {
          node.textContent = data.value == null ? "—" : String(data.value);
        }
      })
      .catch(function () {});
  }

  function renderNotices(container, withActions) {
    var listId = "layout-notices-" + String(Math.random()).slice(2);
    var card = el("div", { className: "card" }, [
      el("div", { className: "card-header", text: "Notices" }),
      el("div", { className: "list-group list-group-flush", id: listId }),
    ]);
    container.appendChild(card);
    fetch("/api/notices")
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        var list = document.getElementById(listId);
        if (!list) {
          return;
        }
        clear(list);
        (data.notices || []).slice(0, 10).forEach(function (n) {
          var item = el("div", { className: "list-group-item" }, [
            el("strong", { text: n.title }),
            el("div", { className: "small text-muted", text: n.body || "" }),
          ]);
          if (withActions && n.reminder_id) {
            var snooze = el("button", {
              className: "btn btn-sm btn-outline-secondary mt-1",
              text: "Snooze 15m",
            });
            snooze.addEventListener("click", function () {
              fetch("/api/reminders/" + encodeURIComponent(n.reminder_id) + "/snooze", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ minutes: 15 }),
              });
            });
            item.appendChild(snooze);
          }
          list.appendChild(item);
        });
      });
  }

  function renderReminders(container) {
    var listId = "layout-reminders-" + String(Math.random()).slice(2);
    var card = el("div", { className: "card" }, [
      el("div", { className: "card-header", text: "Upcoming reminders" }),
      el("div", { className: "list-group list-group-flush", id: listId }),
    ]);
    container.appendChild(card);
    fetch("/api/reminders")
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        var list = document.getElementById(listId);
        if (!list) {
          return;
        }
        clear(list);
        (data.reminders || [])
          .filter(function (r) {
            return r.enabled !== false;
          })
          .slice(0, 10)
          .forEach(function (r) {
            list.appendChild(
              el("div", { className: "list-group-item" }, [
                el("strong", { text: r.title || r.id }),
                el("div", {
                  className: "small text-muted",
                  text: (r.schedule_summary || "") + (r.next_run_at ? " · " + r.next_run_at : ""),
                }),
              ])
            );
          });
      });
  }

  function renderText(col, container) {
    container.appendChild(el("p", { className: "mb-0", text: col.label || "" }));
  }

  function renderTableLink(col, container) {
    var table = col.table || col.screen;
    if (!table) {
      container.appendChild(el("p", { className: "text-muted", text: "table widget needs table" }));
      return;
    }
    container.appendChild(
      el("a", { className: "btn btn-outline-primary", href: "#list/" + table, text: "Open " + table })
    );
  }

  function renderKanban(col, container) {
    var table = col.table;
    var column = col.column;
    var titleCol = col.title_column || "title";
    if (!table || !column) {
      container.appendChild(el("p", { className: "text-muted", text: "kanban needs table and column" }));
      return;
    }
    var wrap = el("div", { className: "d-flex gap-2 flex-wrap" });
    container.appendChild(wrap);
    fetch("/api/tables/" + encodeURIComponent(table) + "?limit=200")
      .then(function (res) {
        return res.json();
      })
      .then(function (rows) {
        var groups = {};
        (rows || []).forEach(function (row) {
          var key = row[column] == null ? "—" : String(row[column]);
          groups[key] = groups[key] || [];
          groups[key].push(row);
        });
        Object.keys(groups).forEach(function (key) {
          var colEl = el("div", { className: "border rounded p-2", style: "min-width:10rem" }, [
            el("div", { className: "fw-semibold mb-2", text: key }),
          ]);
          groups[key].forEach(function (row) {
            colEl.appendChild(
              el("div", { className: "card card-body p-2 mb-2 small", text: row[titleCol] || "#" + row.id })
            );
          });
          wrap.appendChild(colEl);
        });
      });
  }

  function renderCalendar(col, container) {
    var table = col.table;
    var dateCol = col.column;
    if (!table || !dateCol) {
      container.appendChild(el("p", { className: "text-muted", text: "calendar needs table and column" }));
      return;
    }
    var list = el("ul", { className: "list-group" });
    container.appendChild(list);
    fetch("/api/tables/" + encodeURIComponent(table) + "?limit=200")
      .then(function (res) {
        return res.json();
      })
      .then(function (rows) {
        (rows || [])
          .slice()
          .sort(function (a, b) {
            return String(a[dateCol] || "").localeCompare(String(b[dateCol] || ""));
          })
          .forEach(function (row) {
            list.appendChild(
              el("li", { className: "list-group-item d-flex justify-content-between" }, [
                el("span", { text: row[(col.title_column || "title")] || "#" + row.id }),
                el("span", { className: "text-muted small", text: row[dateCol] || "" }),
              ])
            );
          });
      });
  }

  function renderLayout(layout, target) {
    clear(target);
    target.appendChild(el("h2", { className: "h4", text: layout.title || layout.id }));
    (layout.rows || []).forEach(function (row) {
      var rowEl = el("div", { className: "row mb-3" });
      (row.cols || []).forEach(function (col) {
        var span = col.span || 12;
        var colEl = el("div", { className: "col-md-" + String(span) });
        var widget = col.widget;
        if (widget === "metric") {
          renderMetric(col, colEl);
        } else if (widget === "notices") {
          renderNotices(colEl, true);
        } else if (widget === "reminders") {
          renderReminders(colEl);
        } else if (widget === "text") {
          renderText(col, colEl);
        } else if (widget === "table" || widget === "form") {
          renderTableLink(col, colEl);
        } else if (widget === "kanban") {
          renderKanban(col, colEl);
        } else if (widget === "calendar") {
          renderCalendar(col, colEl);
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
