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

  function kanbanEnumValues(schema, table, column) {
    var tables = schema && schema.tables;
    var tableDef = tables && tables[table];
    var cols = (tableDef && tableDef.columns) || [];
    var i;
    for (i = 0; i < cols.length; i++) {
      if (cols[i] && cols[i].name === column && Array.isArray(cols[i].enum)) {
        return cols[i].enum.slice();
      }
    }
    return null;
  }

  function renderKanban(col, container, schema) {
    var table = col.table;
    var column = col.column;
    var titleCol = col.title_column || "title";
    if (!table || !column) {
      container.appendChild(el("p", { className: "text-muted", text: "kanban needs table and column" }));
      return;
    }

    var toolbar = el("div", { className: "d-flex justify-content-end mb-2" });
    var newBtn = el("button", {
      className: "btn btn-sm btn-primary kanban-new",
      type: "button",
      text: "New",
    });
    newBtn.addEventListener("click", function () {
      var app = global.DesktopperApp;
      if (!app || !app.openNewModal) {
        location.hash = "#form/" + table;
        return;
      }
      // New rows start in the board's first status column.
      var enumValues = kanbanEnumValues(schema, table, column);
      var defaults = {};
      if (enumValues && enumValues.length) {
        defaults[column] = enumValues[0];
      }
      app.openNewModal(table, reload, defaults);
    });
    toolbar.appendChild(newBtn);
    container.appendChild(toolbar);

    var errorEl = el("p", { className: "text-danger small mb-2", text: "" });
    errorEl.hidden = true;
    container.appendChild(errorEl);

    var wrap = el("div", { className: "d-flex gap-2 flex-wrap" });
    container.appendChild(wrap);

    var NULL_KEY = "—";
    var dragged = false;
    var dragRowId = null;
    var dragFromStatus = null;

    function showError(msg) {
      if (!msg) {
        errorEl.hidden = true;
        errorEl.textContent = "";
        return;
      }
      errorEl.hidden = false;
      errorEl.textContent = msg;
    }

    function columnKeys(rows, enumValues) {
      var keys = [];
      var seen = {};
      var i;
      if (enumValues && enumValues.length) {
        for (i = 0; i < enumValues.length; i++) {
          keys.push(String(enumValues[i]));
          seen[String(enumValues[i])] = true;
        }
      }
      var hasNull = false;
      (rows || []).forEach(function (row) {
        if (row[column] == null || row[column] === "") {
          hasNull = true;
          return;
        }
        var key = String(row[column]);
        if (!seen[key]) {
          keys.push(key);
          seen[key] = true;
        }
      });
      if (hasNull) {
        keys.push(NULL_KEY);
      }
      if (!keys.length) {
        (rows || []).forEach(function (row) {
          var key = row[column] == null || row[column] === "" ? NULL_KEY : String(row[column]);
          if (!seen[key]) {
            keys.push(key);
            seen[key] = true;
          }
        });
      }
      return keys;
    }

    function paint(rows) {
      clear(wrap);
      var enumValues = kanbanEnumValues(schema, table, column);
      var groups = {};
      var keys = columnKeys(rows, enumValues);
      keys.forEach(function (key) {
        groups[key] = [];
      });
      (rows || []).forEach(function (row) {
        var key = row[column] == null || row[column] === "" ? NULL_KEY : String(row[column]);
        if (!groups[key]) {
          groups[key] = [];
          keys.push(key);
        }
        groups[key].push(row);
      });

      keys.forEach(function (key) {
        var droppable = key !== NULL_KEY;
        var colEl = el("div", {
          className: "border rounded p-2 kanban-column",
          style: "min-width:10rem; min-height:4rem",
          "data-status": key,
        }, [
          el("div", { className: "fw-semibold mb-2", text: key }),
        ]);

        if (droppable) {
          colEl.addEventListener("dragover", function (ev) {
            ev.preventDefault();
            colEl.style.outline = "2px solid #0d6efd";
          });
          colEl.addEventListener("dragleave", function () {
            colEl.style.outline = "";
          });
          colEl.addEventListener("drop", function (ev) {
            ev.preventDefault();
            colEl.style.outline = "";
            var rowId = ev.dataTransfer.getData("text/plain") || dragRowId;
            if (!rowId) {
              return;
            }
            if (dragFromStatus === key) {
              return;
            }
            var body = {};
            body[column] = key;
            showError("");
            fetch("/api/tables/" + encodeURIComponent(table) + "/" + encodeURIComponent(rowId), {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            })
              .then(function (res) {
                return res.json().then(function (data) {
                  return { ok: res.ok, status: res.status, data: data };
                });
              })
              .then(function (result) {
                if (!result.ok) {
                  showError(
                    result.status === 403
                      ? "forbidden"
                      : (result.data && result.data.error) || "Update failed."
                  );
                  return;
                }
                reload();
              })
              .catch(function () {
                showError("Update failed.");
              });
          });
        }

        (groups[key] || []).forEach(function (row) {
          var statusKey = row[column] == null || row[column] === "" ? NULL_KEY : String(row[column]);
          var card = el("div", {
            className: "card card-body p-2 mb-2 small kanban-card",
            text: row[titleCol] || "#" + row.id,
            draggable: "true",
            "data-row-id": String(row.id),
            style: "cursor:pointer",
          });
          card.addEventListener("dragstart", function (ev) {
            dragged = true;
            dragRowId = String(row.id);
            dragFromStatus = statusKey;
            ev.dataTransfer.setData("text/plain", String(row.id));
            ev.dataTransfer.effectAllowed = "move";
          });
          card.addEventListener("dragend", function () {
            setTimeout(function () {
              dragged = false;
              dragRowId = null;
              dragFromStatus = null;
            }, 0);
          });
          card.addEventListener("click", function () {
            if (dragged) {
              return;
            }
            location.hash = "#form/" + table + "/" + row.id;
          });
          colEl.appendChild(card);
        });
        wrap.appendChild(colEl);
      });
    }

    function reload() {
      fetch("/api/tables/" + encodeURIComponent(table) + "?limit=200")
        .then(function (res) {
          return res.json();
        })
        .then(function (rows) {
          paint(rows);
        })
        .catch(function () {
          showError("Could not reload board.");
        });
    }

    reload();
  }

  function calendarDateKey(value) {
    if (value == null || value === "") {
      return null;
    }
    var s = String(value).trim();
    if (/^\d{4}-\d{2}-\d{2}/.test(s)) {
      return s.slice(0, 10);
    }
    return null;
  }

  function calendarMonthMatrix(year, monthIndex) {
    // monthIndex 0-11; weeks start Monday; always six weeks
    var first = new Date(year, monthIndex, 1);
    var startOffset = (first.getDay() + 6) % 7;
    var start = new Date(year, monthIndex, 1 - startOffset);
    var weeks = [];
    var d = new Date(start.getFullYear(), start.getMonth(), start.getDate());
    var w;
    var i;
    for (w = 0; w < 6; w++) {
      var week = [];
      for (i = 0; i < 7; i++) {
        week.push({
          year: d.getFullYear(),
          month: d.getMonth(),
          day: d.getDate(),
          key:
            d.getFullYear() +
            "-" +
            String(d.getMonth() + 1).padStart(2, "0") +
            "-" +
            String(d.getDate()).padStart(2, "0"),
          inMonth: d.getMonth() === monthIndex,
        });
        d.setDate(d.getDate() + 1);
      }
      weeks.push(week);
    }
    return weeks;
  }

  function renderCalendar(col, container) {
    var table = col.table;
    var dateCol = col.column;
    var titleCol = col.title_column || "title";
    var maxPerDay = 3;
    if (!table || !dateCol) {
      container.appendChild(
        el("p", { className: "text-muted", text: "calendar needs table and column" })
      );
      return;
    }

    var now = new Date();
    var viewYear = now.getFullYear();
    var viewMonth = now.getMonth();
    var rowsCache = [];

    var header = el("div", { className: "d-flex align-items-center justify-content-between mb-2" });
    var titleEl = el("div", { className: "fw-semibold", text: "" });
    var nav = el("div", { className: "btn-group btn-group-sm" });
    var prevBtn = el("button", { type: "button", className: "btn btn-outline-secondary", text: "Prev" });
    var nextBtn = el("button", { type: "button", className: "btn btn-outline-secondary", text: "Next" });
    nav.appendChild(prevBtn);
    nav.appendChild(nextBtn);
    header.appendChild(titleEl);
    header.appendChild(nav);
    container.appendChild(header);

    var gridHost = el("div", { className: "calendar-grid-host" });
    container.appendChild(gridHost);

    var monthNames = [
      "January",
      "February",
      "March",
      "April",
      "May",
      "June",
      "July",
      "August",
      "September",
      "October",
      "November",
      "December",
    ];
    var weekdayLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

    function bucketByDate(rows) {
      var buckets = {};
      (rows || []).forEach(function (row) {
        var key = calendarDateKey(row[dateCol]);
        if (!key) {
          return;
        }
        if (!buckets[key]) {
          buckets[key] = [];
        }
        buckets[key].push(row);
      });
      return buckets;
    }

    function paint() {
      clear(gridHost);
      titleEl.textContent = monthNames[viewMonth] + " " + viewYear;
      var buckets = bucketByDate(rowsCache);
      var matrix = calendarMonthMatrix(viewYear, viewMonth);

      var grid = el("div", { className: "calendar-grid" });
      weekdayLabels.forEach(function (label) {
        grid.appendChild(el("div", { className: "calendar-weekday", text: label }));
      });

      matrix.forEach(function (week) {
        week.forEach(function (cell) {
          var dayClass = "calendar-day" + (cell.inMonth ? "" : " calendar-day-outside");
          var dayEl = el("div", { className: dayClass });
          dayEl.appendChild(
            el("div", { className: "calendar-day-num", text: String(cell.day) })
          );
          var items = buckets[cell.key] || [];
          var shown = items.slice(0, maxPerDay);
          shown.forEach(function (row) {
            var label =
              row[titleCol] != null && row[titleCol] !== ""
                ? String(row[titleCol])
                : "#" + row.id;
            var itemBtn = el("button", {
              type: "button",
              className: "calendar-item btn btn-sm btn-link text-start text-decoration-none p-0",
              text: label,
            });
            itemBtn.addEventListener("click", function (ev) {
              ev.preventDefault();
              ev.stopPropagation();
              location.hash = "#form/" + table + "/" + row.id;
            });
            dayEl.appendChild(itemBtn);
          });
          if (items.length > maxPerDay) {
            dayEl.appendChild(
              el("div", {
                className: "calendar-more small text-muted",
                text: "+" + String(items.length - maxPerDay) + " more",
              })
            );
          }
          grid.appendChild(dayEl);
        });
      });
      gridHost.appendChild(grid);
    }

    prevBtn.addEventListener("click", function () {
      viewMonth -= 1;
      if (viewMonth < 0) {
        viewMonth = 11;
        viewYear -= 1;
      }
      paint();
    });
    nextBtn.addEventListener("click", function () {
      viewMonth += 1;
      if (viewMonth > 11) {
        viewMonth = 0;
        viewYear += 1;
      }
      paint();
    });

    fetch("/api/tables/" + encodeURIComponent(table) + "?limit=200")
      .then(function (res) {
        return res.json();
      })
      .then(function (rows) {
        rowsCache = rows || [];
        paint();
      })
      .catch(function () {
        rowsCache = [];
        paint();
        gridHost.appendChild(
          el("p", { className: "text-muted small", text: "Could not load rows." })
        );
      });
  }

  function renderLayout(layout, target, schema) {
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
          renderKanban(col, colEl, schema);
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
