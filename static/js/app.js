(function () {
  var schema = null;
  var globalTimer = null;
  var listTimer = null;
  var pendingDelete = null;

  function el(tag, attrs) {
    var node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (key) {
      var val = attrs[key];
      if (val === null || val === undefined) {
        return;
      }
      if (key === "className") {
        node.className = val;
      } else if (key === "text") {
        node.textContent = val;
      } else if (key === "checked") {
        node.checked = !!val;
      } else {
        node.setAttribute(key, String(val));
      }
    });
    return node;
  }

  function showError(msg) {
    var box = document.getElementById("error");
    if (!box) {
      return;
    }
    if (!msg) {
      box.hidden = true;
      box.textContent = "";
      return;
    }
    box.hidden = false;
    box.textContent = msg;
  }

  function tableDef(name) {
    if (!schema || !schema.tables) {
      return null;
    }
    return schema.tables[name] || null;
  }

  function visibleColumns(table) {
    var cols = (table && table.columns) || [];
    return cols.filter(function (c) {
      if (!c || !c.name) {
        return false;
      }
      if (c.hidden) {
        return false;
      }
      if (c.name === "id" || c.name === "created_at" || c.name === "updated_at") {
        return false;
      }
      return true;
    });
  }

  function listScreens() {
    var screens = (schema && schema.screens) || [];
    return screens.filter(function (s) {
      return s && s.type === "list" && s.table;
    });
  }

  function navListScreens() {
    return listScreens().filter(function (s) {
      return s.nav !== false;
    });
  }

  function formScreenFor(tableName) {
    var screens = (schema && schema.screens) || [];
    var i;
    for (i = 0; i < screens.length; i++) {
      if (screens[i].type === "form" && screens[i].table === tableName) {
        return screens[i];
      }
    }
    return null;
  }

  function parseQuery(qs) {
    var out = {};
    if (!qs) {
      return out;
    }
    qs.split("&").forEach(function (part) {
      var bits = part.split("=");
      if (!bits[0]) {
        return;
      }
      out[decodeURIComponent(bits[0])] = decodeURIComponent(
        bits.slice(1).join("=") || ""
      );
    });
    return out;
  }

  function parseHash() {
    var raw = (location.hash || "").replace(/^#/, "");
    var qs = "";
    var qi = raw.indexOf("?");
    if (qi >= 0) {
      qs = raw.slice(qi + 1);
      raw = raw.slice(0, qi);
    }
    var query = parseQuery(qs);
    var parts = raw.split("/").filter(Boolean);
    if (parts[0] === "list" && parts[1]) {
      return { kind: "list", table: parts[1], query: query };
    }
    if (parts[0] === "form" && parts[1]) {
      return {
        kind: "form",
        table: parts[1],
        id: parts[2] ? Number(parts[2]) : null,
        query: query,
      };
    }
    return { kind: "home", query: query };
  }

  function go(hash) {
    location.hash = hash;
  }

  function api(path) {
    return fetch(path).then(function (res) {
      return res.json().then(function (body) {
        if (!res.ok) {
          var err = new Error((body && body.error) || res.statusText);
          throw err;
        }
        return body;
      });
    });
  }

  function drawNav() {
    var titleEl = document.getElementById("app-title");
    var title =
      schema && schema.app && schema.app.title ? schema.app.title : "Desktopper";
    if (titleEl) {
      titleEl.textContent = title;
    }
    document.title = title;
    var nav = document.getElementById("nav-screens");
    if (!nav) {
      return;
    }
    nav.textContent = "";
    navListScreens().forEach(function (screen) {
      var a = el("a", {
        className: "nav-link",
        href: "#list/" + screen.table,
        text: screen.title || screen.table,
      });
      nav.appendChild(a);
    });
  }

  function drawEmpty(show) {
    var emptyEl = document.getElementById("empty-state");
    var main = document.getElementById("main");
    if (emptyEl) {
      emptyEl.hidden = !show;
    }
    if (main) {
      main.hidden = show;
    }
  }

  function bindGlobalSearch() {
    var input = document.getElementById("global-search");
    var hitsEl = document.getElementById("global-hits");
    if (!input || !hitsEl) {
      return;
    }
    input.addEventListener("input", function () {
      if (globalTimer) {
        clearTimeout(globalTimer);
      }
      globalTimer = setTimeout(function () {
        var q = input.value || "";
        if (!q.trim()) {
          hitsEl.hidden = true;
          hitsEl.textContent = "";
          return;
        }
        api("/api/search?q=" + encodeURIComponent(q))
          .then(function (body) {
            hitsEl.textContent = "";
            var hits = (body && body.hits) || [];
            if (!hits.length) {
              hitsEl.hidden = true;
              return;
            }
            hits.forEach(function (hit) {
              var a = el("a", {
                className: "list-group-item list-group-item-action",
                href: "#form/" + hit.table + "/" + hit.id,
              });
              a.appendChild(
                document.createTextNode(
                  String(hit.label != null ? hit.label : hit.id)
                )
              );
              a.addEventListener("click", function (ev) {
                ev.preventDefault();
                hitsEl.hidden = true;
                go("#form/" + hit.table + "/" + hit.id);
              });
              hitsEl.appendChild(a);
            });
            hitsEl.hidden = false;
          })
          .catch(function (err) {
            showError(err.message);
          });
      }, 300);
    });
  }

  function drawList(tableName) {
    var main = document.getElementById("main");
    var table = tableDef(tableName);
    var screen = listScreens().filter(function (s) {
      return s.table === tableName;
    })[0];
    if (!main || !table || !screen) {
      drawEmpty(true);
      return;
    }
    drawEmpty(false);
    main.textContent = "";
    var header = el("div", { className: "d-flex justify-content-between mb-3" });
    header.appendChild(el("h1", { className: "h4", text: screen.title || tableName }));
    var neu = el("button", { className: "btn btn-primary", type: "button", text: "New" });
    neu.addEventListener("click", function () {
      go("#form/" + tableName);
    });
    header.appendChild(neu);
    main.appendChild(header);

    var search = el("input", {
      className: "form-control mb-3",
      type: "search",
      id: "list-search",
      placeholder: "Search this list",
    });
    main.appendChild(search);

    var wrap = el("div", { className: "table-responsive" });
    var tbl = el("table", { className: "table table-hover" });
    var thead = document.createElement("thead");
    var hr = document.createElement("tr");
    var colNames = screen.columns && screen.columns.length
      ? screen.columns
      : visibleColumns(table).map(function (c) {
          return c.name;
        });
    colNames.forEach(function (cname) {
      var col = (table.columns || []).filter(function (c) {
        return c.name === cname;
      })[0];
      hr.appendChild(
        el("th", { text: (col && col.label) || cname })
      );
    });
    thead.appendChild(hr);
    tbl.appendChild(thead);
    var tbody = document.createElement("tbody");
    tbl.appendChild(tbody);
    wrap.appendChild(tbl);
    main.appendChild(wrap);

    function load(q) {
      var path = "/api/tables/" + encodeURIComponent(tableName);
      if (q) {
        path += "?q=" + encodeURIComponent(q);
      }
      api(path)
        .then(function (rows) {
          tbody.textContent = "";
          (rows || []).forEach(function (row) {
            var tr = document.createElement("tr");
            colNames.forEach(function (cname) {
              var td = document.createElement("td");
              var val = row[cname];
              td.textContent = val == null ? "" : String(val);
              tr.appendChild(td);
            });
            tr.addEventListener("click", function () {
              go("#form/" + tableName + "/" + row.id);
            });
            tbody.appendChild(tr);
          });
        })
        .catch(function (err) {
          showError(err.message);
        });
    }

    search.addEventListener("input", function () {
      if (listTimer) {
        clearTimeout(listTimer);
      }
      listTimer = setTimeout(function () {
        load(search.value);
      }, 300);
    });
    load("");
  }

  function widgetInput(col, value, options) {
    var widget = col.widget || "text";
    var name = col.name;
    if (widget === "textarea") {
      var ta = el("textarea", { className: "form-control", id: "f-" + name, name: name });
      ta.value = value == null ? "" : String(value);
      return ta;
    }
    if (widget === "select" || widget === "fk") {
      var sel = el("select", { className: "form-select", id: "f-" + name, name: name });
      sel.appendChild(el("option", { value: "", text: "" }));
      if (widget === "select" && col.enum) {
        col.enum.forEach(function (item) {
          var opt = el("option", { value: item, text: item });
          if (String(value) === String(item)) {
            opt.selected = true;
          }
          sel.appendChild(opt);
        });
      }
      if (widget === "fk" && options) {
        options.forEach(function (item) {
          var opt = el("option", {
            value: String(item.id),
            text: item.label == null ? String(item.id) : String(item.label),
          });
          if (value != null && String(value) === String(item.id)) {
            opt.selected = true;
          }
          sel.appendChild(opt);
        });
      }
      return sel;
    }
    if (widget === "checkbox") {
      var chk = el("input", {
        className: "form-check-input",
        type: "checkbox",
        id: "f-" + name,
        name: name,
      });
      chk.checked = value === 1 || value === true;
      return chk;
    }
    var type = widget === "number" ? "number" : "text";
    var inp = el("input", {
      className: "form-control",
      type: type,
      id: "f-" + name,
      name: name,
    });
    inp.value = value == null ? "" : String(value);
    return inp;
  }

  function readField(col) {
    var node = document.getElementById("f-" + col.name);
    if (!node) {
      return undefined;
    }
    if (col.widget === "checkbox") {
      return node.checked ? 1 : 0;
    }
    if (col.widget === "number") {
      if (node.value === "") {
        return null;
      }
      return col.type === "INTEGER" ? parseInt(node.value, 10) : parseFloat(node.value);
    }
    if (col.widget === "fk") {
      if (node.value === "") {
        return null;
      }
      return parseInt(node.value, 10);
    }
    if (node.value === "") {
      return col.nullable === false ? "" : null;
    }
    return node.value;
  }

  function parentReturn(tableName, query) {
    var table = tableDef(tableName);
    var key;
    query = query || {};
    for (key in query) {
      if (!Object.prototype.hasOwnProperty.call(query, key)) {
        continue;
      }
      var col = ((table && table.columns) || []).filter(function (c) {
        return c.name === key && c.widget === "fk" && c.fk && c.fk.table;
      })[0];
      if (col) {
        return "#form/" + col.fk.table + "/" + query[key];
      }
    }
    return "#list/" + tableName;
  }

  function drawRelated(container, parentId, related) {
    if (!container || !parentId || !related || !related.length) {
      return;
    }
    related.forEach(function (rel) {
      if (!rel || !rel.table || !rel.fk) {
        return;
      }
      var childTable = tableDef(rel.table);
      if (!childTable) {
        return;
      }
      var section = el("div", { className: "mt-4" });
      var header = el("div", { className: "d-flex justify-content-between mb-2" });
      header.appendChild(
        el("h2", { className: "h5", text: rel.title || rel.table })
      );
      var add = el("button", {
        className: "btn btn-sm btn-outline-primary",
        type: "button",
        text: "Add",
      });
      add.addEventListener("click", function () {
        go("#form/" + rel.table + "?" + encodeURIComponent(rel.fk) + "=" + parentId);
      });
      header.appendChild(add);
      section.appendChild(header);
      var tbl = el("table", { className: "table table-sm" });
      var thead = document.createElement("thead");
      var hr = document.createElement("tr");
      var colNames =
        rel.columns && rel.columns.length
          ? rel.columns.filter(function (name) {
              return name !== rel.fk;
            })
          : visibleColumns(childTable)
              .map(function (c) {
                return c.name;
              })
              .filter(function (name) {
                return name !== rel.fk;
              });
      colNames.forEach(function (cname) {
        var col = (childTable.columns || []).filter(function (c) {
          return c.name === cname;
        })[0];
        hr.appendChild(el("th", { text: (col && col.label) || cname }));
      });
      thead.appendChild(hr);
      tbl.appendChild(thead);
      var tbody = document.createElement("tbody");
      tbl.appendChild(tbody);
      section.appendChild(tbl);
      container.appendChild(section);
      var fkCols = colNames.filter(function (cname) {
        var col = (childTable.columns || []).filter(function (c) {
          return c.name === cname;
        })[0];
        return col && col.widget === "fk" && col.fk && col.fk.table;
      });
      var optLoads = fkCols.map(function (cname) {
        var col = (childTable.columns || []).filter(function (c) {
          return c.name === cname;
        })[0];
        return api(
          "/api/tables/" + encodeURIComponent(col.fk.table) + "/options"
        ).then(function (opts) {
          return { name: cname, options: opts };
        });
      });
      Promise.all(optLoads)
        .then(function (pairs) {
          var labels = {};
          pairs.forEach(function (p) {
            var map = {};
            (p.options || []).forEach(function (item) {
              map[String(item.id)] = item.label;
            });
            labels[p.name] = map;
          });
          return api(
            "/api/tables/" +
              encodeURIComponent(rel.table) +
              "?" +
              encodeURIComponent(rel.fk) +
              "=" +
              encodeURIComponent(String(parentId))
          ).then(function (rows) {
            tbody.textContent = "";
            (rows || []).forEach(function (row) {
              var tr = document.createElement("tr");
              colNames.forEach(function (cname) {
                var td = document.createElement("td");
                var val = row[cname];
                if (labels[cname] && val != null) {
                  val = labels[cname][String(val)];
                }
                td.textContent = val == null ? "" : String(val);
                tr.appendChild(td);
              });
              tr.addEventListener("click", function () {
                go(
                  "#form/" +
                    rel.table +
                    "/" +
                    row.id +
                    "?" +
                    encodeURIComponent(rel.fk) +
                    "=" +
                    parentId
                );
              });
              tbody.appendChild(tr);
            });
          });
        })
        .catch(function (err) {
          showError(err.message);
        });
    });
  }

  function confirmDelete(tableName, rowId, after) {
    pendingDelete = { table: tableName, id: rowId, after: after };
    var body = document.getElementById("confirm-body");
    if (body) {
      body.textContent = "Delete this record?";
    }
    var modalEl = document.getElementById("confirm-modal");
    if (window.bootstrap && modalEl) {
      window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  }

  function drawForm(tableName, rowId, query) {
    var main = document.getElementById("main");
    var table = tableDef(tableName);
    var screen = formScreenFor(tableName);
    query = query || {};
    if (!main || !table) {
      drawEmpty(true);
      return;
    }
    drawEmpty(false);
    main.textContent = "";
    var title = (screen && screen.title) || table.label || tableName;
    main.appendChild(
      el("h1", { className: "h4 mb-3", text: rowId ? "Edit " + title : "New " + title })
    );
    var form = el("form", { id: "record-form" });
    var related = (screen && screen.related) || [];
    var after = parentReturn(tableName, query);
    var cols = visibleColumns(table).filter(function (c) {
      return query[c.name] === undefined;
    });
    var fkLoads = cols
      .filter(function (c) {
        return c.widget === "fk" && c.fk && c.fk.table;
      })
      .map(function (c) {
        return api("/api/tables/" + encodeURIComponent(c.fk.table) + "/options").then(
          function (opts) {
            return { name: c.name, options: opts };
          }
        );
      });

    function paint(row, fkMap) {
      form.textContent = "";
      cols.forEach(function (col) {
        var group = el("div", { className: "mb-3" });
        var label = el("label", {
          className: "form-label",
          text: col.label || col.name,
        });
        label.setAttribute("for", "f-" + col.name);
        group.appendChild(label);
        var opts = fkMap[col.name];
        var val = row ? row[col.name] : null;
        if (col.widget === "checkbox") {
          var wrap = el("div", { className: "form-check" });
          wrap.appendChild(widgetInput(col, val, opts));
          group.appendChild(wrap);
        } else {
          group.appendChild(widgetInput(col, val, opts));
        }
        form.appendChild(group);
      });
      var actions = el("div", { className: "d-flex gap-2" });
      var save = el("button", { className: "btn btn-primary", type: "submit", text: "Save" });
      actions.appendChild(save);
      if (rowId) {
        var del = el("button", {
          className: "btn btn-outline-danger",
          type: "button",
          text: "Delete",
        });
        del.addEventListener("click", function () {
          confirmDelete(tableName, rowId, after);
        });
        actions.appendChild(del);
      }
      var cancel = el("a", {
        className: "btn btn-secondary",
        href: after,
        text: "Back",
      });
      actions.appendChild(cancel);
      form.appendChild(actions);
      main.appendChild(form);
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        var body = {};
        cols.forEach(function (col) {
          body[col.name] = readField(col);
        });
        Object.keys(query).forEach(function (key) {
          var col = (table.columns || []).filter(function (c) {
            return c.name === key && c.widget === "fk";
          })[0];
          if (col) {
            body[key] = parseInt(query[key], 10);
          }
        });
        var path = "/api/tables/" + encodeURIComponent(tableName);
        var method = "POST";
        if (rowId) {
          path += "/" + rowId;
          method = "PUT";
        }
        fetch(path, {
          method: method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        })
          .then(function (res) {
            return res.json().then(function (data) {
              if (!res.ok) {
                throw new Error((data && data.error) || res.statusText);
              }
              return data;
            });
          })
          .then(function (data) {
            if (related.length && data && data.id) {
              go("#form/" + tableName + "/" + data.id);
              return;
            }
            go(after);
          })
          .catch(function (err) {
            showError(err.message);
          });
      });
      if (rowId) {
        drawRelated(main, rowId, related);
      }
    }

    Promise.all(fkLoads)
      .then(function (pairs) {
        var fkMap = {};
        pairs.forEach(function (p) {
          fkMap[p.name] = p.options;
        });
        if (rowId) {
          return api(
            "/api/tables/" + encodeURIComponent(tableName) + "/" + rowId
          ).then(function (row) {
            paint(row, fkMap);
          });
        }
        paint(null, fkMap);
      })
      .catch(function (err) {
        showError(err.message);
      });
  }

  function route() {
    showError("");
    var empty = listScreens().length === 0;
    if (empty) {
      drawEmpty(true);
      return;
    }
    var loc = parseHash();
    if (loc.kind === "list") {
      drawList(loc.table);
      return;
    }
    if (loc.kind === "form") {
      drawForm(loc.table, loc.id, loc.query);
      return;
    }
    var homeId = schema && schema.app && schema.app.home;
    if (homeId) {
      var screens = schema.screens || [];
      var i;
      for (i = 0; i < screens.length; i++) {
        if (screens[i].id === homeId && screens[i].type === "list" && screens[i].table) {
          go("#list/" + screens[i].table);
          return;
        }
      }
    }
    var first = navListScreens()[0] || listScreens()[0];
    go("#list/" + first.table);
  }

  function boot() {
    bindGlobalSearch();
    var ok = document.getElementById("confirm-ok");
    if (ok) {
      ok.addEventListener("click", function () {
        if (!pendingDelete) {
          return;
        }
        var info = pendingDelete;
        pendingDelete = null;
        fetch(
          "/api/tables/" +
            encodeURIComponent(info.table) +
            "/" +
            info.id,
          { method: "DELETE" }
        )
          .then(function (res) {
            if (!res.ok && res.status !== 204) {
              return res.json().then(function (data) {
                throw new Error((data && data.error) || res.statusText);
              });
            }
            var modalEl = document.getElementById("confirm-modal");
            if (window.bootstrap && modalEl) {
              window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
            }
            go(info.after || "#list/" + info.table);
          })
          .catch(function (err) {
            showError(err.message);
          });
      });
    }
    api("/api/schema")
      .then(function (data) {
        schema = data;
        drawNav();
        route();
      })
      .catch(function (err) {
        showError(err.message);
      });
    window.addEventListener("hashchange", route);
  }

  boot();
})();
