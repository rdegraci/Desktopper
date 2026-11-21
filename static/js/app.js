(function () {
  var schema = null;
  var globalTimer = null;
  var listTimer = null;
  var pendingDelete = null;
  var focusedTarget = null;

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

  function tableRole(name) {
    var table = tableDef(name);
    if (table && table.role === "lookup") {
      return "lookup";
    }
    return "primary";
  }

  function listScreens() {
    var screens = (schema && schema.screens) || [];
    return screens.filter(function (s) {
      return s && s.type === "list" && s.table;
    });
  }

  function navListScreens() {
    return listScreens().filter(function (s) {
      return s.nav !== false && tableRole(s.table) !== "lookup";
    });
  }

  function lookupNavScreens() {
    return listScreens().filter(function (s) {
      return s.nav !== false && tableRole(s.table) === "lookup";
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
    if (parts[0] === "layout" && parts[1]) {
      return { kind: "layout", id: parts[1], query: query };
    }
    return { kind: "home", query: query };
  }

  function go(hash) {
    location.hash = hash;
  }

  function setFocusedTarget(target) {
    focusedTarget = target;
  }

  function buildUiContext() {
    var loc = parseHash();
    var ctx = {
      route: location.hash || "",
      screen_id: null,
      screen_type: null,
      table: null,
      focused: null,
      visible_columns: [],
      related_block: null,
      scope_id: null,
    };
    if (loc.kind === "list") {
      var listScreen = listScreens().filter(function (s) {
        return s.table === loc.table;
      })[0];
      ctx.screen_type = "list";
      ctx.table = loc.table;
      ctx.screen_id = listScreen ? listScreen.id : null;
      ctx.scope_id = loc.query.scope || null;
      if (listScreen && listScreen.columns && listScreen.columns.length) {
        ctx.visible_columns = listScreen.columns.slice();
      } else {
        var table = tableDef(loc.table);
        ctx.visible_columns = visibleColumns(table).map(function (c) {
          return c.name;
        });
      }
    } else if (loc.kind === "form") {
      var formScreen = formScreenFor(loc.table);
      ctx.screen_type = "form";
      ctx.table = loc.table;
      ctx.screen_id = formScreen ? formScreen.id : null;
      if (formScreen && formScreen.groups && formScreen.groups.length) {
        formScreen.groups.forEach(function (group) {
          (group.columns || []).forEach(function (name) {
            if (ctx.visible_columns.indexOf(name) < 0) {
              ctx.visible_columns.push(name);
            }
          });
        });
      } else {
        var formTable = tableDef(loc.table);
        ctx.visible_columns = visibleColumns(formTable).map(function (c) {
          return c.name;
        });
      }
    } else if (loc.kind === "layout") {
      ctx.screen_type = "layout";
      (schema.screens || []).forEach(function (s) {
        if (s && s.type === "layout" && s.layout_id === loc.id) {
          ctx.screen_id = s.id;
        }
      });
    }
    ctx.focused = focusedTarget;
    return ctx;
  }

  function opsUrlForContext(ctx) {
    var params = new URLSearchParams();
    if (ctx.screen_id) {
      params.set("screen", ctx.screen_id);
    }
    if (ctx.route) {
      params.set("route", ctx.route);
    }
    var qs = params.toString();
    return qs ? "/ops?" + qs : "/ops";
  }

  function opsPrefillForContext(ctx) {
    if (!ctx.focused || ctx.focused.kind !== "column") {
      return "";
    }
    var label = ctx.focused.name;
    var screenTitle = ctx.table || "this screen";
    if (ctx.screen_id && schema && schema.screens) {
      schema.screens.forEach(function (s) {
        if (s && s.id === ctx.screen_id) {
          screenTitle = s.title || s.id;
        }
      });
    }
    return "Change " + label + " on " + screenTitle + ":";
  }

  function prepareOpsLink(link) {
    var ctx = buildUiContext();
    try {
      sessionStorage.setItem("desktopper_ui_context", JSON.stringify(ctx));
      var prefill = opsPrefillForContext(ctx);
      if (prefill) {
        sessionStorage.setItem("desktopper_ops_prefill", prefill);
      } else {
        sessionStorage.removeItem("desktopper_ops_prefill");
      }
    } catch (e) {}
    if (link) {
      link.href = opsUrlForContext(ctx);
    }
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
      nav.appendChild(viewNavButton("#list/" + screen.table, screen.title || screen.table));
    });
    (schema.screens || []).forEach(function (screen) {
      if (screen && screen.type === "layout" && screen.layout_id) {
        nav.appendChild(
          viewNavButton("#layout/" + screen.layout_id, screen.title || screen.layout_id)
        );
      }
    });
    var lookups = lookupNavScreens();
    if (lookups.length) {
      var drop = el("div", { className: "dropdown" });
      var toggle = el("button", {
        type: "button",
        className: "btn btn-sm btn-outline-primary dropdown-toggle nav-view-btn",
        text: "Lookups",
      });
      toggle.setAttribute("data-bs-toggle", "dropdown");
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute(
        "data-nav-hashes",
        lookups
          .map(function (screen) {
            return "#list/" + screen.table;
          })
          .join(" ")
      );
      drop.appendChild(toggle);
      var menu = el("ul", { className: "dropdown-menu" });
      lookups.forEach(function (screen) {
        var li = document.createElement("li");
        var a = el("a", {
          className: "dropdown-item",
          href: "#list/" + screen.table,
          text: screen.title || screen.table,
        });
        li.appendChild(a);
        menu.appendChild(li);
      });
      drop.appendChild(menu);
      nav.appendChild(drop);
    }
    markActiveNav();
  }

  // Anchors styled as buttons keep native hash navigation (and
  // open-in-new-tab) while reading as view switches, not inline links.
  function viewNavButton(hash, label) {
    var a = el("a", {
      className: "btn btn-sm btn-outline-primary nav-view-btn",
      href: hash,
      role: "button",
      text: label,
    });
    a.setAttribute("data-nav-hashes", hash);
    return a;
  }

  function currentViewHash() {
    var loc = parseHash();
    if (loc.kind === "list" || loc.kind === "form") {
      return "#list/" + loc.table;
    }
    if (loc.kind === "layout") {
      return "#layout/" + loc.id;
    }
    return "";
  }

  function markActiveNav() {
    var nav = document.getElementById("nav-screens");
    if (!nav) {
      return;
    }
    var current = currentViewHash();
    var buttons = nav.querySelectorAll(".nav-view-btn");
    Array.prototype.forEach.call(buttons, function (btn) {
      var hashes = (btn.getAttribute("data-nav-hashes") || "").split(" ");
      var on = !!current && hashes.indexOf(current) >= 0;
      btn.classList.toggle("btn-primary", on);
      btn.classList.toggle("btn-outline-primary", !on);
      btn.classList.toggle("active", on);
      if (on) {
        btn.setAttribute("aria-current", "page");
      } else {
        btn.removeAttribute("aria-current");
      }
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

  function drawList(tableName, query) {
    var main = document.getElementById("main");
    var table = tableDef(tableName);
    var screen = listScreens().filter(function (s) {
      return s.table === tableName;
    })[0];
    query = query || {};
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
      openNewModal(tableName, function () {
        load(search.value);
      });
    });
    header.appendChild(neu);
    main.appendChild(header);

    var scopes = screen.scopes || [];
    var activeScope = query.scope || "";
    var scopeDef = null;
    scopes.forEach(function (s) {
      if (s && s.id === activeScope) {
        scopeDef = s;
      }
    });
    if (scopes.length) {
      var bar = el("div", {
        className: "btn-group mb-3 flex-wrap",
        role: "group",
      });
      function scopeBtn(id, label, selected) {
        var btn = el("button", {
          className: "btn btn-sm " + (selected ? "btn-primary" : "btn-outline-primary"),
          type: "button",
          text: label,
        });
        btn.addEventListener("click", function () {
          if (!id) {
            go("#list/" + tableName);
            return;
          }
          go("#list/" + tableName + "?scope=" + encodeURIComponent(id));
        });
        return btn;
      }
      bar.appendChild(scopeBtn("", "All", !activeScope));
      scopes.forEach(function (s) {
        if (!s || !s.id) {
          return;
        }
        bar.appendChild(scopeBtn(s.id, s.label || s.id, s.id === activeScope));
      });
      main.appendChild(bar);
    }

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
      var th = el("th", { text: (col && col.label) || cname });
      th.style.cursor = "pointer";
      th.title = "Target this column in Ops";
      th.addEventListener("click", function (ev) {
        ev.stopPropagation();
        setFocusedTarget({ kind: "column", name: cname, table: tableName });
      });
      hr.appendChild(th);
    });
    hr.appendChild(el("th", { className: "text-end", text: "Actions" }));
    thead.appendChild(hr);
    tbl.appendChild(thead);
    var tbody = document.createElement("tbody");
    tbl.appendChild(tbody);
    wrap.appendChild(tbl);
    main.appendChild(wrap);
    var emptyBox = el("p", {
      className: "text-muted empty-state mb-0",
      hidden: "hidden",
    });
    main.appendChild(emptyBox);

    function listEmptyMessage(q, rowCount) {
      if (rowCount) {
        return "";
      }
      if (q) {
        return "No matches.";
      }
      if (scopeDef) {
        return (
          "Nothing in " + (scopeDef.label || scopeDef.id || "this filter") + "."
        );
      }
      if (screen.empty) {
        return screen.empty;
      }
      return "No " + (screen.title || tableName) + " yet.";
    }

    function showListEmpty(msg) {
      if (msg) {
        emptyBox.textContent = msg;
        emptyBox.hidden = false;
        wrap.hidden = true;
      } else {
        emptyBox.textContent = "";
        emptyBox.hidden = true;
        wrap.hidden = false;
      }
    }

    function load(q) {
      var params = [];
      if (q) {
        params.push("q=" + encodeURIComponent(q));
      }
      if (scopeDef && scopeDef.column) {
        var sval = scopeDef.value;
        if (typeof sval === "boolean") {
          sval = sval ? "1" : "0";
        }
        params.push(
          encodeURIComponent(scopeDef.column) +
            "=" +
            encodeURIComponent(String(sval))
        );
      }
      var path = "/api/tables/" + encodeURIComponent(tableName);
      if (params.length) {
        path += "?" + params.join("&");
      }
      api(path)
        .then(function (rows) {
          tbody.textContent = "";
          rows = rows || [];
          showListEmpty(listEmptyMessage(q, rows.length));
          rows.forEach(function (row) {
            var tr = document.createElement("tr");
            colNames.forEach(function (cname) {
              var td = document.createElement("td");
              var val = row[cname];
              td.textContent = val == null ? "" : String(val);
              tr.appendChild(td);
            });
            var actions = el("td", { className: "text-end text-nowrap" });
            var editBtn = el("button", {
              className: "btn btn-sm btn-outline-secondary me-1 row-edit",
              type: "button",
              text: "Edit",
            });
            editBtn.addEventListener("click", function (ev) {
              ev.stopPropagation();
              openEditModal(tableName, row.id, reloadList);
            });
            var destroyBtn = el("button", {
              className: "btn btn-sm btn-outline-danger row-destroy",
              type: "button",
              text: "Destroy",
            });
            destroyBtn.addEventListener("click", function (ev) {
              ev.stopPropagation();
              confirmDelete(tableName, row.id, reloadList);
            });
            actions.appendChild(editBtn);
            actions.appendChild(destroyBtn);
            tr.appendChild(actions);
            tr.addEventListener("click", function () {
              openDetailsModal(tableName, row.id);
            });
            tbody.appendChild(tr);
          });
        })
        .catch(function (err) {
          showError(err.message);
        });
    }

    function reloadList() {
      load(search.value);
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

  function fieldId(col, idPrefix) {
    return (idPrefix || "f-") + col.name;
  }

  function widgetInput(col, value, options, idPrefix) {
    var widget = col.widget || "text";
    var name = col.name;
    var fid = fieldId(col, idPrefix);
    if (widget === "textarea") {
      var ta = el("textarea", { className: "form-control", id: fid, name: name });
      ta.value = value == null ? "" : String(value);
      return ta;
    }
    if (widget === "select" || widget === "fk") {
      var sel = el("select", { className: "form-select", id: fid, name: name });
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
        id: fid,
        name: name,
      });
      chk.checked = value === 1 || value === true;
      return chk;
    }
    var type = widget === "number" ? "number" : "text";
    var inp = el("input", {
      className: "form-control",
      type: type,
      id: fid,
      name: name,
    });
    inp.value = value == null ? "" : String(value);
    return inp;
  }

  function readField(col, idPrefix) {
    var node = document.getElementById(fieldId(col, idPrefix));
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

  function belongsToEntries(table, query) {
    var entries = [];
    var key;
    query = query || {};
    for (key in query) {
      if (!Object.prototype.hasOwnProperty.call(query, key)) {
        continue;
      }
      var col = ((table && table.columns) || []).filter(function (c) {
        return c.name === key && c.widget === "fk" && c.fk && c.fk.table;
      })[0];
      if (!col) {
        continue;
      }
      var id = Number(query[key]);
      if (!id) {
        continue;
      }
      entries.push({ col: col, id: id });
    }
    return entries;
  }

  function drawBelongsTo(box, table, query) {
    if (!box) {
      return Promise.resolve();
    }
    box.textContent = "";
    var entries = belongsToEntries(table, query);
    if (!entries.length) {
      box.hidden = true;
      return Promise.resolve();
    }
    box.hidden = false;
    return Promise.all(
      entries.map(function (entry) {
        var target = entry.col.fk.table;
        var display = entry.col.fk.display;
        return api(
          "/api/tables/" + encodeURIComponent(target) + "/" + entry.id
        ).then(
          function (parent) {
            var label =
              parent && parent[display] != null
                ? parent[display]
                : String(entry.id);
            var row = el("p", { className: "mb-1 belongs-to" });
            row.appendChild(
              document.createTextNode((entry.col.label || entry.col.name) + ": ")
            );
            var link = el("a", {
              className: "belongs-to-link",
              href: "#form/" + target + "/" + entry.id,
              text: String(label),
            });
            row.appendChild(link);
            return row;
          },
          function () {
            var row = el("p", { className: "mb-1 belongs-to" });
            row.appendChild(
              document.createTextNode((entry.col.label || entry.col.name) + ": ")
            );
            var link = el("a", {
              className: "belongs-to-link",
              href: "#form/" + target + "/" + entry.id,
              text: String(entry.id),
            });
            row.appendChild(link);
            return row;
          }
        );
      })
    ).then(function (nodes) {
      nodes.forEach(function (node) {
        if (node) {
          box.appendChild(node);
        }
      });
    });
  }

  function relatedFieldCols(childTable, rel) {
    return visibleColumns(childTable).filter(function (c) {
      return c.name !== rel.fk;
    });
  }

  function relatedListCols(childTable, rel) {
    if (rel.columns && rel.columns.length) {
      return rel.columns.filter(function (name) {
        return name !== rel.fk;
      });
    }
    return relatedFieldCols(childTable, rel).map(function (c) {
      return c.name;
    });
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
      var relTitle = el("h2", { className: "h5", text: rel.title || rel.table });
      relTitle.style.cursor = "pointer";
      relTitle.title = "Target this related list in Ops";
      relTitle.addEventListener("click", function () {
        setFocusedTarget({
          kind: "related",
          table: rel.table,
          fk: rel.fk,
        });
      });
      header.appendChild(relTitle);
      var add = el("button", {
        className: "btn btn-sm btn-outline-primary",
        type: "button",
        text: "Add",
      });
      header.appendChild(add);
      section.appendChild(header);

      var inline = el("div", { className: "border rounded p-3 mb-3", hidden: "hidden" });
      inline.setAttribute("data-inline-related", rel.table);
      section.appendChild(inline);

      var tbl = el("table", { className: "table table-sm" });
      var thead = document.createElement("thead");
      var hr = document.createElement("tr");
      var colNames = relatedListCols(childTable, rel);
      var fieldCols = relatedFieldCols(childTable, rel);
      var idPrefix = "rel-" + rel.table + "-";
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
      var emptyBox = el("p", {
        className: "text-muted empty-state mb-0",
        hidden: "hidden",
      });
      section.appendChild(emptyBox);
      container.appendChild(section);

      function relatedEmptyMessage() {
        if (rel.empty) {
          return rel.empty;
        }
        return "No " + (rel.title || rel.table) + " yet. Add one.";
      }

      function showRelatedEmpty(isEmpty) {
        if (isEmpty) {
          emptyBox.textContent = relatedEmptyMessage();
          emptyBox.hidden = false;
          tbl.hidden = true;
        } else {
          emptyBox.textContent = "";
          emptyBox.hidden = true;
          tbl.hidden = false;
        }
      }

      var fkNames = {};
      fieldCols.forEach(function (c) {
        if (c.widget === "fk" && c.fk && c.fk.table) {
          fkNames[c.name] = c.fk.table;
        }
      });
      colNames.forEach(function (cname) {
        var col = (childTable.columns || []).filter(function (c) {
          return c.name === cname;
        })[0];
        if (col && col.widget === "fk" && col.fk && col.fk.table) {
          fkNames[cname] = col.fk.table;
        }
      });
      var optLoads = Object.keys(fkNames).map(function (cname) {
        return api(
          "/api/tables/" + encodeURIComponent(fkNames[cname]) + "/options"
        ).then(function (opts) {
          return { name: cname, options: opts };
        });
      });

      function paintRows(labels) {
        return api(
          "/api/tables/" +
            encodeURIComponent(rel.table) +
            "?" +
            encodeURIComponent(rel.fk) +
            "=" +
            encodeURIComponent(String(parentId))
        ).then(function (rows) {
          tbody.textContent = "";
          rows = rows || [];
          showRelatedEmpty(!rows.length);
          rows.forEach(function (row) {
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
      }

      function hideInline() {
        inline.hidden = true;
        inline.textContent = "";
      }

      function showInline(fkMap) {
        inline.textContent = "";
        inline.hidden = false;
        var form = el("form", { className: "related-inline-form" });
        fieldCols.forEach(function (col) {
          var group = el("div", { className: "mb-2" });
          var label = el("label", {
            className: "form-label",
            text: col.label || col.name,
          });
          label.setAttribute("for", fieldId(col, idPrefix));
          group.appendChild(label);
          var opts = fkMap[col.name];
          if (col.widget === "checkbox") {
            var wrap = el("div", { className: "form-check" });
            wrap.appendChild(widgetInput(col, null, opts, idPrefix));
            group.appendChild(wrap);
          } else {
            group.appendChild(widgetInput(col, null, opts, idPrefix));
          }
          form.appendChild(group);
        });
        var actions = el("div", { className: "d-flex gap-2" });
        var save = el("button", {
          className: "btn btn-sm btn-primary",
          type: "submit",
          text: "Save",
        });
        var cancel = el("button", {
          className: "btn btn-sm btn-secondary",
          type: "button",
          text: "Cancel",
        });
        cancel.addEventListener("click", function () {
          hideInline();
        });
        actions.appendChild(save);
        actions.appendChild(cancel);
        form.appendChild(actions);
        form.addEventListener("submit", function (ev) {
          ev.preventDefault();
          showError("");
          var body = {};
          body[rel.fk] = parentId;
          fieldCols.forEach(function (col) {
            body[col.name] = readField(col, idPrefix);
          });
          fetch("/api/tables/" + encodeURIComponent(rel.table), {
            method: "POST",
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
            .then(function () {
              hideInline();
              return paintRows(labelMaps);
            })
            .catch(function (err) {
              showError(err.message);
            });
        });
        inline.appendChild(form);
      }

      var labelMaps = {};
      Promise.all(optLoads)
        .then(function (pairs) {
          var fkMap = {};
          pairs.forEach(function (p) {
            fkMap[p.name] = p.options;
            var map = {};
            (p.options || []).forEach(function (item) {
              map[String(item.id)] = item.label;
            });
            labelMaps[p.name] = map;
          });
          add.addEventListener("click", function () {
            if (!inline.hidden) {
              hideInline();
              return;
            }
            showInline(fkMap);
          });
          return paintRows(labelMaps);
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

  // Shared by the full-page form and the New modal so both show the same
  // fields, groups, and widgets for a table.
  function appendFormFields(form, tableName, screen, cols, row, fkMap, idPrefix) {
    var grouped = {};
    var groups = (screen && screen.groups) || [];
    groups.forEach(function (g) {
      if (!g || !g.id || !g.columns) {
        return;
      }
      (g.columns || []).forEach(function (cname) {
        grouped[cname] = true;
      });
    });

    function appendField(parent, col) {
      var box = el("div", { className: "mb-3" });
      var label = el("label", {
        className: "form-label",
        text: col.label || col.name,
      });
      label.setAttribute("for", fieldId(col, idPrefix));
      label.style.cursor = "pointer";
      label.title = "Target this field in Ops";
      label.addEventListener("click", function (ev) {
        ev.preventDefault();
        setFocusedTarget({
          kind: "column",
          name: col.name,
          table: tableName,
        });
      });
      box.appendChild(label);
      var opts = fkMap[col.name];
      var val = row ? row[col.name] : null;
      if (col.widget === "checkbox") {
        var wrap = el("div", { className: "form-check" });
        wrap.appendChild(widgetInput(col, val, opts, idPrefix));
        box.appendChild(wrap);
      } else {
        box.appendChild(widgetInput(col, val, opts, idPrefix));
      }
      parent.appendChild(box);
    }

    function colByName(name) {
      var i;
      for (i = 0; i < cols.length; i++) {
        if (cols[i].name === name) {
          return cols[i];
        }
      }
      return null;
    }

    if (groups.length) {
      groups.forEach(function (g) {
        if (!g || !g.columns || !g.columns.length) {
          return;
        }
        var section = el("fieldset", { className: "mb-4 field-group" });
        section.appendChild(
          el("legend", {
            className: "h6 field-group-label",
            text: g.label || g.id,
          })
        );
        var any = false;
        (g.columns || []).forEach(function (cname) {
          var col = colByName(cname);
          if (!col) {
            return;
          }
          any = true;
          appendField(section, col);
        });
        if (any) {
          form.appendChild(section);
        }
      });
      cols.forEach(function (col) {
        if (!grouped[col.name]) {
          appendField(form, col);
        }
      });
    } else {
      cols.forEach(function (col) {
        appendField(form, col);
      });
    }
  }

  function fkOptionLoads(cols) {
    return cols
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
  }

  function postJson(path, method, body) {
    return fetch(path, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) {
          throw new Error((data && data.error) || res.statusText);
        }
        return data;
      });
    });
  }

  var NEW_MODAL_PREFIX = "new-";
  var newModalSeq = 0;

  // `defaults` pre-fills fields, e.g. the status a kanban board starts new
  // rows in; fields without a default stay empty as on the create form.
  function openNewModal(tableName, onCreated, defaults) {
    openRecordModal(tableName, null, onCreated, defaults);
  }

  function openEditModal(tableName, rowId, onSaved) {
    openRecordModal(tableName, rowId, onSaved, null);
  }

  // One modal serves create (rowId null, POST) and edit (PUT to the row).
  function openRecordModal(tableName, rowId, onSaved, defaults) {
    var modalEl = document.getElementById("new-modal");
    var form = document.getElementById("new-modal-form");
    var titleEl = document.getElementById("new-modal-title");
    var errEl = document.getElementById("new-modal-error");
    var okBtn = document.getElementById("new-modal-ok");
    var table = tableDef(tableName);
    if (!modalEl || !form || !table || !window.bootstrap) {
      go("#form/" + tableName + (rowId ? "/" + rowId : ""));
      return;
    }
    var screen = formScreenFor(tableName);
    var cols = visibleColumns(table);
    var title = (screen && screen.title) || table.label || tableName;
    titleEl.textContent = (rowId ? "Edit " : "New ") + title;
    form.textContent = "";
    form.setAttribute("data-table", tableName);
    errEl.textContent = "";
    errEl.hidden = true;
    okBtn.disabled = true;
    // A slow option load from an earlier open must not paint into this one.
    var seq = ++newModalSeq;

    function modalError(msg) {
      errEl.textContent = msg || "";
      errEl.hidden = !msg;
    }

    var rowPath = "/api/tables/" + encodeURIComponent(tableName);
    if (rowId) {
      rowPath += "/" + rowId;
    }
    var rowLoad = rowId ? api(rowPath) : Promise.resolve(defaults || null);

    Promise.all([Promise.all(fkOptionLoads(cols)), rowLoad])
      .then(function (results) {
        if (seq !== newModalSeq) {
          return;
        }
        var fkMap = {};
        results[0].forEach(function (p) {
          fkMap[p.name] = p.options;
        });
        appendFormFields(form, tableName, screen, cols, results[1], fkMap, NEW_MODAL_PREFIX);
        okBtn.disabled = false;
      })
      .catch(function (err) {
        modalError(err.message);
      });

    function submit(ev) {
      ev.preventDefault();
      if (okBtn.disabled) {
        return;
      }
      modalError("");
      var body = {};
      cols.forEach(function (col) {
        body[col.name] = readField(col, NEW_MODAL_PREFIX);
      });
      okBtn.disabled = true;
      postJson(rowPath, rowId ? "PUT" : "POST", body)
        .then(function (data) {
          window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
          if (onSaved) {
            onSaved(data);
          }
        })
        .catch(function (err) {
          modalError(err.message);
        })
        .then(function () {
          okBtn.disabled = false;
        });
    }
    // Assigned, not added, so reopening the modal replaces the previous
    // table's handlers instead of stacking them.
    form.onsubmit = submit;
    okBtn.onclick = submit;
    window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }

  var detailsModalSeq = 0;

  function detailsText(col, value, fkOptions) {
    if (value == null || value === "") {
      return null;
    }
    if (col.widget === "checkbox") {
      return value === 1 || value === true ? "Yes" : "No";
    }
    if (col.widget === "fk" && fkOptions) {
      var hit = fkOptions.filter(function (item) {
        return String(item.id) === String(value);
      })[0];
      if (hit && hit.label != null) {
        return String(hit.label);
      }
    }
    return String(value);
  }

  // Read-only view of one row. Ok only dismisses; nothing is saved.
  function openDetailsModal(tableName, rowId) {
    var modalEl = document.getElementById("details-modal");
    var body = document.getElementById("details-modal-body");
    var titleEl = document.getElementById("details-modal-title");
    var errEl = document.getElementById("details-modal-error");
    var table = tableDef(tableName);
    if (!modalEl || !body || !table || !window.bootstrap) {
      go("#form/" + tableName + "/" + rowId);
      return;
    }
    var screen = formScreenFor(tableName);
    var cols = visibleColumns(table);
    titleEl.textContent = (screen && screen.title) || table.label || tableName;
    body.textContent = "";
    errEl.textContent = "";
    errEl.hidden = true;
    var seq = ++detailsModalSeq;
    var rowPath = "/api/tables/" + encodeURIComponent(tableName) + "/" + rowId;

    Promise.all([Promise.all(fkOptionLoads(cols)), api(rowPath)])
      .then(function (results) {
        if (seq !== detailsModalSeq) {
          return;
        }
        var fkMap = {};
        results[0].forEach(function (p) {
          fkMap[p.name] = p.options;
        });
        var row = results[1] || {};
        cols.forEach(function (col) {
          var text = detailsText(col, row[col.name], fkMap[col.name]);
          body.appendChild(
            el("dt", { className: "col-sm-4", text: col.label || col.name })
          );
          var dd = el("dd", {
            className: "col-sm-8 text-break" + (text == null ? " text-muted" : ""),
            text: text == null ? "\u2014" : text,
          });
          dd.style.whiteSpace = "pre-wrap";
          body.appendChild(dd);
        });
      })
      .catch(function (err) {
        if (seq !== detailsModalSeq) {
          return;
        }
        errEl.textContent = err.message || "";
        errEl.hidden = !err.message;
      });
    window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }

  // layout.js loads first and calls this at click time, so Home widgets can
  // reuse the same create modal as list screens.
  window.DesktopperApp = { openNewModal: openNewModal };

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
    var belongsBox = el("div", { className: "belongs-to-box mb-3" });
    main.appendChild(belongsBox);
    var form = el("form", { id: "record-form" });
    var related = (screen && screen.related) || [];
    var after = parentReturn(tableName, query);
    var cols = visibleColumns(table).filter(function (c) {
      return query[c.name] === undefined;
    });
    var fkLoads = fkOptionLoads(cols);

    function paint(row, fkMap) {
      form.textContent = "";
      appendFormFields(form, tableName, screen, cols, row, fkMap);
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
        postJson(path, method, body)
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

    Promise.all([drawBelongsTo(belongsBox, table, query), Promise.all(fkLoads)])
      .then(function (results) {
        var pairs = results[1] || [];
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

  function refreshNotices() {
    var badge = document.getElementById("notices-badge");
    if (!badge) {
      return;
    }
    fetch("/api/notices?unread=1")
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        var count = (data.notices || []).length;
        if (count > 0) {
          badge.hidden = false;
          badge.textContent = String(count);
        } else {
          badge.hidden = true;
        }
      })
      .catch(function () {});
  }

  function drawLayout(layoutId) {
    var layouts = (schema && schema.layouts) || [];
    var layout = null;
    var i;
    for (i = 0; i < layouts.length; i++) {
      if (layouts[i] && layouts[i].id === layoutId) {
        layout = layouts[i];
        break;
      }
    }
    drawEmpty(false);
    var main = document.getElementById("main");
    if (!main || !layout) {
      showError("Layout not found.");
      return;
    }
    while (main.firstChild) {
      main.removeChild(main.firstChild);
    }
    if (window.DesktopperLayout) {
      window.DesktopperLayout.render(layout, main, schema);
    }
    main.hidden = false;
  }

  function route() {
    showError("");
    markActiveNav();
    var empty = listScreens().length === 0;
    if (empty) {
      drawEmpty(true);
      return;
    }
    var loc = parseHash();
    if (loc.kind === "list") {
      drawList(loc.table, loc.query);
      return;
    }
    if (loc.kind === "form") {
      drawForm(loc.table, loc.id, loc.query);
      return;
    }
    if (loc.kind === "layout") {
      drawLayout(loc.id);
      return;
    }
    var homeId = schema && schema.app && schema.app.home;
    if (homeId) {
      var screens = schema.screens || [];
      var i;
      for (i = 0; i < screens.length; i++) {
        if (
          screens[i].id === homeId &&
          screens[i].type === "layout" &&
          screens[i].layout_id
        ) {
          go("#layout/" + screens[i].layout_id);
          return;
        }
        if (screens[i].id === homeId && screens[i].type === "list" && screens[i].table) {
          go("#list/" + screens[i].table);
          return;
        }
      }
    }
    var first = navListScreens()[0] || listScreens()[0];
    go("#list/" + first.table);
  }

  function drawImportPanel() {
    var panel = document.getElementById("import-panel");
    var select = document.getElementById("import-profile");
    if (!panel || !select) {
      return;
    }
    var profiles = (schema && schema.import_profiles) || [];
    while (select.firstChild) {
      select.removeChild(select.firstChild);
    }
    if (!profiles.length) {
      panel.hidden = true;
      return;
    }
    profiles.forEach(function (profile) {
      var opt = document.createElement("option");
      opt.value = profile.id;
      opt.textContent = profile.label || profile.id;
      select.appendChild(opt);
    });
    panel.hidden = false;
  }

  function bindImport() {
    var fileInput = document.getElementById("import-file");
    var statusEl = document.getElementById("import-status");
    if (!fileInput) {
      return;
    }
    fileInput.addEventListener("change", function () {
      var file = fileInput.files && fileInput.files[0];
      var select = document.getElementById("import-profile");
      if (!file || !select || !select.value) {
        return;
      }
      if (statusEl) {
        statusEl.textContent = "Importing…";
      }
      var form = new FormData();
      form.append("file", file);
      fetch("/api/import/" + encodeURIComponent(select.value), {
        method: "POST",
        body: form,
        credentials: "same-origin",
      })
        .then(function (res) {
          return res.json().then(function (body) {
            return { ok: res.ok, body: body };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            throw new Error((result.body && result.body.error) || "Import failed.");
          }
          if (statusEl) {
            statusEl.textContent =
              "Imported " +
              String(result.body.ok || 0) +
              " rows, " +
              String(result.body.fail || 0) +
              " failed.";
          }
          route();
        })
        .catch(function (err) {
          if (statusEl) {
            statusEl.textContent = err.message || "Import failed.";
          }
        });
      fileInput.value = "";
    });
  }

  function bindLogin() {
    var toggle = document.getElementById("login-toggle");
    var panel = document.getElementById("login-panel");
    var form = document.getElementById("login-form");
    var errEl = document.getElementById("login-error");
    var logoutBtn = document.getElementById("logout-btn");
    var sessionUserEl = document.getElementById("session-user");
    var searchFormEl = document.getElementById("global-search-form");
    var opsLinkEl = document.getElementById("ops-link");

    function setNavElVisible(el, visible) {
      if (!el) {
        return;
      }
      el.hidden = !visible;
      el.classList.toggle("d-none", !visible);
    }

    function setSignedInNav(signedIn) {
      setNavElVisible(searchFormEl, signedIn);
      setNavElVisible(opsLinkEl, signedIn);
    }

    var signedIn = false;

    function applySessionState(user) {
      signedIn = !!(user && user.name);
      if (toggle) {
        toggle.textContent = signedIn ? "Logout" : "Login";
      }
      if (panel && signedIn) {
        panel.hidden = true;
      }
      if (sessionUserEl) {
        if (!signedIn) {
          sessionUserEl.hidden = true;
          sessionUserEl.textContent = "";
        } else {
          sessionUserEl.textContent = "Signed in as " + String(user.name);
          sessionUserEl.hidden = false;
        }
      }
      setSignedInNav(signedIn);
      if (logoutBtn) {
        logoutBtn.hidden = !signedIn;
      }
    }

    function loadSession() {
      fetch("/api/session", { credentials: "same-origin" })
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          applySessionState(data.user || null);
        })
        .catch(function () {
          applySessionState(null);
        });
    }

    function showLoginErr(msg) {
      if (!errEl) {
        return;
      }
      if (!msg) {
        errEl.hidden = true;
        errEl.textContent = "";
        return;
      }
      errEl.hidden = false;
      errEl.textContent = msg;
    }

    if (toggle && panel) {
      toggle.addEventListener("click", function () {
        if (signedIn) {
          signOut();
          return;
        }
        panel.hidden = !panel.hidden;
      });
    }

    if (form) {
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        showLoginErr("");
        var name = document.getElementById("login-name");
        var password = document.getElementById("login-password");
        fetch("/api/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            name: name ? name.value : "",
            password: password ? password.value : "",
          }),
        })
          .then(function (res) {
            return res.json().then(function (body) {
              return { ok: res.ok, body: body };
            });
          })
          .then(function (result) {
            if (!result.ok) {
              showLoginErr((result.body && result.body.error) || "Login failed.");
              return;
            }
            if (panel) {
              panel.hidden = true;
            }
            applySessionState(result.body && result.body.user);
          })
          .catch(function () {
            showLoginErr("Login failed.");
          });
      });
    }

    function signOut() {
      fetch("/api/logout", { method: "POST", credentials: "same-origin" }).then(function () {
        applySessionState(null);
      });
    }

    if (logoutBtn) {
      logoutBtn.addEventListener("click", signOut);
    }

    loadSession();

    if (opsLinkEl) {
      opsLinkEl.addEventListener("click", function () {
        prepareOpsLink(opsLinkEl);
      });
    }
  }

  function boot() {
    bindLogin();
    bindImport();
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
            if (typeof info.after === "function") {
              info.after();
              return;
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
        drawImportPanel();
        route();
        refreshNotices();
        setInterval(refreshNotices, 30000);
      })
      .catch(function (err) {
        showError(err.message);
      });
    window.addEventListener("hashchange", route);
  }

  boot();
})();
