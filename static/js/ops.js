(function () {
  var titleEl = document.getElementById("app-title");
  var versionEl = document.getElementById("schema-version");
  var threadEl = document.getElementById("ops-thread");
  var threadBannerEl = document.getElementById("ops-thread-banner");
  var uiContextChipEl = document.getElementById("ops-ui-context-chip");
  var uiContextLabelEl = document.getElementById("ops-ui-context-label");
  var uiContextClearBtn = document.getElementById("ops-ui-context-clear");
  var clearThreadBtn = document.getElementById("ops-thread-clear");
  var formEl = document.getElementById("intent-form");
  var textEl = document.getElementById("intent-text");
  var submitEl = document.getElementById("intent-submit");
  var busyEl = document.getElementById("intent-busy");
  var busyLabelEl = document.getElementById("intent-busy-label");
  var bootstrapHintEl = document.getElementById("intent-bootstrap-hint");
  var copyBtn = document.getElementById("copy-logs");
  var logsEl = document.getElementById("logs-text");
  var hookPreviewEl = document.getElementById("hook-preview");
  var hookPreviewText = document.getElementById("hook-preview-text");
  var hooksTbody = document.getElementById("hooks-tbody");
  var hookEditor = document.getElementById("hook-editor");
  var hookEditorTitle = document.getElementById("hook-editor-title");
  var hookCodeEl = document.getElementById("hook-code");
  var hookSaveBtn = document.getElementById("hook-save");
  var hookToggleBtn = document.getElementById("hook-toggle");
  var hookDeleteBtn = document.getElementById("hook-delete");
  var hookCancelBtn = document.getElementById("hook-cancel");
  var hookEditorError = document.getElementById("hook-editor-error");
  var confirmModalOk = document.getElementById("confirm-modal-ok");

  var currentHook = null;
  var hooksList = [];
  var schemaVersion = 0;
  var activeUiContext = null;
  var loadedSchema = null;

  function screenTitleForContext(ctx) {
    if (!ctx) {
      return "Current screen";
    }
    if (ctx.screen_id && loadedSchema && loadedSchema.screens) {
      var i;
      for (i = 0; i < loadedSchema.screens.length; i++) {
        var s = loadedSchema.screens[i];
        if (s && s.id === ctx.screen_id) {
          return s.title || s.id;
        }
      }
      return ctx.screen_id;
    }
    if (ctx.table) {
      return ctx.table;
    }
    return "Current screen";
  }

  function showUiContextChip(ctx) {
    if (!uiContextChipEl || !uiContextLabelEl) {
      return;
    }
    if (!ctx) {
      uiContextChipEl.hidden = true;
      return;
    }
    uiContextLabelEl.textContent = screenTitleForContext(ctx);
    uiContextChipEl.hidden = false;
  }

  function loadUiContextFromPage() {
    var stored = null;
    try {
      stored = JSON.parse(sessionStorage.getItem("desktopper_ui_context") || "null");
    } catch (e) {
      stored = null;
    }
    if (stored && typeof stored === "object") {
      activeUiContext = stored;
      showUiContextChip(stored);
      return;
    }
    var params = new URLSearchParams(window.location.search);
    var screenId = params.get("screen");
    var route = params.get("route");
    if (screenId || route) {
      activeUiContext = {
        route: route || "",
        screen_id: screenId,
        screen_type: null,
        table: null,
        focused: null,
        visible_columns: [],
        related_block: null,
        scope_id: null,
      };
      showUiContextChip(activeUiContext);
    }
  }

  if (uiContextClearBtn) {
    uiContextClearBtn.addEventListener("click", function () {
      activeUiContext = null;
      showUiContextChip(null);
      try {
        sessionStorage.removeItem("desktopper_ui_context");
      } catch (e) {}
    });
  }

  loadUiContextFromPage();

  function el(tag, attrs) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        if (key === "text") {
          node.textContent = attrs[key];
        } else if (key === "className") {
          node.className = attrs[key];
        } else {
          node.setAttribute(key, attrs[key]);
        }
      });
    }
    return node;
  }

  function actionBadge(action) {
    var label = "Message";
    var cls = "bg-secondary";
    if (action === "apply") {
      label = "Applied";
      cls = "bg-success";
    } else if (action === "failed") {
      label = "Failed";
      cls = "bg-danger";
    } else if (action === "propose") {
      label = "Plan";
      cls = "bg-primary";
    } else if (action === "clarify") {
      label = "Question";
      cls = "bg-info text-dark";
    }
    return el("span", { className: "badge " + cls + " me-2", text: label });
  }

  function formatValidationErrors(validation) {
    if (!validation || validation.ok || !validation.errors) {
      return "";
    }
    return validation.errors
      .map(function (err) {
        var line = err.message || err.code || "Validation error.";
        if (err.detail && err.detail.path) {
          line = err.detail.path + ": " + line;
        }
        return line;
      })
      .join("\n");
  }

  function buildHistoryFromThread(entries) {
    var history = [];
    (entries || []).forEach(function (entry) {
      if (entry.role === "user") {
        history.push({ role: "user", content: entry.text || "" });
      } else if (entry.role === "assistant") {
        history.push({
          role: "assistant",
          content: entry.message || "",
          action: entry.action,
          version: entry.version,
        });
      }
    });
    return history;
  }

  function renderThreadEntry(entry) {
    var wrap = el("div", { className: "mb-3" });
    var head = el("div", { className: "d-flex align-items-center mb-1" });
    if (entry.role === "user") {
      head.appendChild(el("strong", { text: "You" }));
    } else {
      head.appendChild(actionBadge(entry.action || "apply"));
      head.appendChild(el("strong", { text: "App" }));
    }
    wrap.appendChild(head);
    var bodyText = entry.text || entry.message || "";
    wrap.appendChild(el("div", { text: bodyText }));
    if (entry.role === "assistant" && entry.action === "clarify" && entry.open_questions && entry.open_questions.length) {
      var ul = el("ul", { className: "small mb-0 mt-2" });
      entry.open_questions.forEach(function (q) {
        ul.appendChild(el("li", { text: String(q) }));
      });
      wrap.appendChild(ul);
    }
    if (entry.role === "assistant" && entry.action === "propose") {
      var validation = entry.validation;
      if (validation && validation.ok) {
        wrap.appendChild(el("div", { className: "small text-success mt-1", text: "Would apply cleanly." }));
      } else if (validation && !validation.ok) {
        wrap.appendChild(
          el("div", {
            className: "small text-danger mt-1",
            text: formatValidationErrors(validation),
          })
        );
      }
      if (entry.proposed_diff) {
        var diffDetails = el("details", { className: "mt-2" });
        diffDetails.appendChild(el("summary", { text: "Proposed diff" }));
        diffDetails.appendChild(
          el("pre", {
            className: "bg-white border rounded p-2 small mb-0",
            text: JSON.stringify(entry.proposed_diff, null, 2),
          })
        );
        wrap.appendChild(diffDetails);
        if (validation && validation.ok) {
          var applyBtn = el("button", {
            type: "button",
            className: "btn btn-sm btn-primary mt-2",
            text: "Apply this plan",
          });
          applyBtn.addEventListener("click", function () {
            applyProposedDiff(entry.proposed_diff);
          });
          wrap.appendChild(applyBtn);
        }
      }
    }
    if (entry.role === "assistant" && entry.action === "apply" && entry.version !== undefined) {
      wrap.appendChild(
        el("div", {
          className: "small text-muted mt-1",
          text: "Schema version " + String(entry.version) + ". Refresh the App tab.",
        })
      );
    }
    if (entry.role === "assistant" && entry.action === "failed") {
      if (entry.rejected_diff) {
        var failDetails = el("details", { className: "mt-2" });
        failDetails.appendChild(el("summary", { text: "What the model returned" }));
        failDetails.appendChild(
          el("pre", {
            className: "bg-white border rounded p-2 small mb-0",
            text: JSON.stringify(entry.rejected_diff, null, 2),
          })
        );
        wrap.appendChild(failDetails);
      }
      var retryBtn = el("button", {
        type: "button",
        className: "btn btn-sm btn-outline-secondary mt-2",
        text: "Edit and retry",
      });
      retryBtn.addEventListener("click", function () {
        editAndRetry(entry);
      });
      wrap.appendChild(retryBtn);
    }
    return wrap;
  }

  function editAndRetry(entry) {
    if (!textEl) {
      return;
    }
    var prompt = "Fix this schema change: ";
    if (entry && entry.message) {
      prompt += entry.message;
    } else {
      prompt += "the previous request failed validation.";
    }
    if (entry && entry.rejected_diff) {
      prompt += " Adjust the diff so it validates.";
    }
    textEl.value = prompt;
    textEl.focus();
  }

  function renderThread(entries) {
    if (!threadEl) {
      return;
    }
    while (threadEl.firstChild) {
      threadEl.removeChild(threadEl.firstChild);
    }
    if (!entries || !entries.length) {
      threadEl.appendChild(
        el("p", {
          className: "text-muted small mb-0",
          text: "No messages yet. Describe your app below.",
        })
      );
      return;
    }
    entries.forEach(function (entry) {
      threadEl.appendChild(renderThreadEntry(entry));
    });
    threadEl.scrollTop = threadEl.scrollHeight;
  }

  function updateThreadBanner(entries) {
    if (!threadBannerEl) {
      return;
    }
    var nonEmpty = entries && entries.length > 0;
    threadBannerEl.hidden = !(schemaVersion === 0 && nonEmpty);
  }

  function applyProposedDiff(diff) {
    setBusy(true);
    fetch("/api/intent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "repl", apply_diff: diff }),
    })
      .then(function (res) {
        return res.json().then(function (body) {
          return { ok: res.ok, body: body };
        });
      })
      .then(function (result) {
        loadLogs();
        loadThread();
        if (!result.ok) {
          return;
        }
        loadReminders();
        if (result.body && result.body.version !== undefined) {
          schemaVersion = result.body.version;
          setVersion(result.body.version);
        }
        var changed = (result.body && result.body.hooks_changed) || [];
        if (changed.length) {
          showHookPreview(changed, null);
        }
        loadHooks();
        closeHookEditor();
      })
      .catch(function () {
        loadLogs();
        loadThread();
      })
      .then(function () {
        setBusy(false);
      });
  }

  function sendIntent(text) {
    setBusy(true);
    return fetch("/api/ops/thread")
      .then(function (res) {
        return res.ok ? res.json() : { entries: [] };
      })
      .then(function (data) {
        var payload = {
          text: text,
          mode: "repl",
          history: buildHistoryFromThread(data.entries || []),
        };
        if (activeUiContext) {
          payload.ui_context = activeUiContext;
        }
        return fetch("/api/intent", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      })
      .then(function (res) {
        return res.json().then(function (body) {
          return { ok: res.ok, status: res.status, body: body };
        });
      })
      .then(function (result) {
        loadLogs();
        loadThread();
        if (!result.ok) {
          return result;
        }
        loadReminders();
        var changed = (result.body && result.body.hooks_changed) || [];
        if (changed.length) {
          showHookPreview(changed, null);
          changed.forEach(function (item) {
            if (item.action === "add" || item.action === "update") {
              fetch("/api/hooks/" + encodeURIComponent(item.id))
                .then(function (res) {
                  return res.ok ? res.json() : null;
                })
                .then(function (hook) {
                  if (!hook || !hookPreviewText) {
                    return;
                  }
                  var block =
                    "\n--- " + hook.id + " ---\n" + (hook.code || "");
                  hookPreviewText.value += block;
                });
            }
          });
        }
        if (result.body && result.body.version !== undefined) {
          schemaVersion = result.body.version;
          setVersion(result.body.version);
        }
        if (textEl) {
          textEl.value = "";
        }
        loadHooks();
        closeHookEditor();
        return result;
      })
      .catch(function () {
        loadLogs();
        loadThread();
      })
      .then(function (result) {
        setBusy(false);
        return result;
      });
  }

  function loadThread() {
    return fetch("/api/ops/thread")
      .then(function (res) {
        if (!res.ok) {
          throw new Error("thread");
        }
        return res.json();
      })
      .then(function (data) {
        var entries = data.entries || [];
        renderThread(entries);
        updateThreadBanner(entries);
        return entries;
      })
      .catch(function () {
        renderThread([]);
      });
  }

  function setText(node, value) {
    if (node) {
      node.textContent = value || "";
    }
  }

  function formatDetailSummary(detail) {
    if (!detail || typeof detail !== "object") {
      return "";
    }
    var parts = [];
    if (detail.path) {
      parts.push(detail.path);
    }
    if (detail.unknown_keys && detail.unknown_keys.length) {
      parts.push("unknown keys " + detail.unknown_keys.join(", "));
    }
    if (detail.column) {
      parts.push("column " + detail.column);
    }
    if (detail.bad_type !== undefined) {
      parts.push("bad type " + String(detail.bad_type));
    }
    var line = parts.join(": ");
    if (detail.hint) {
      line = line ? line + " — " + detail.hint : detail.hint;
    }
    return line;
  }

  function formatIntentFailureMessage(body) {
    var msg = body && body.error ? body.error : "Intent failed.";
    var detailLine = formatDetailSummary(body && body.detail);
    if (detailLine) {
      return msg + " — " + detailLine;
    }
    return msg;
  }

  function showHookEditorError(msg) {
    if (!hookEditorError) {
      return;
    }
    if (!msg) {
      hookEditorError.hidden = true;
      hookEditorError.textContent = "";
      return;
    }
    hookEditorError.hidden = false;
    hookEditorError.textContent = msg;
  }

  function setVersion(version) {
    if (!versionEl) {
      return;
    }
    versionEl.textContent = "Schema version " + String(version);
  }

  function setBusy(busy) {
    if (busyEl) {
      if (busy) {
        busyEl.classList.remove("d-none");
        busyEl.classList.add("d-flex");
      } else {
        busyEl.classList.remove("d-flex");
        busyEl.classList.add("d-none");
      }
    }
    if (busyLabelEl) {
      busyLabelEl.textContent = busy ? "Working…" : "";
    }
    if (submitEl) {
      submitEl.disabled = !!busy;
    }
    if (textEl) {
      textEl.disabled = !!busy;
    }
  }

  function loadHooks() {
    return fetch("/api/hooks")
      .then(function (res) {
        if (!res.ok) {
          throw new Error("hooks");
        }
        return res.json();
      })
      .then(function (data) {
        hooksList = data.hooks || [];
        renderHooksTable();
      })
      .catch(function () {
        hooksList = [];
        renderHooksTable();
      });
  }

  function renderHooksTable() {
    if (!hooksTbody) {
      return;
    }
    hooksTbody.textContent = "";
    if (!hooksList.length) {
      var emptyRow = document.createElement("tr");
      var emptyCell = document.createElement("td");
      emptyCell.colSpan = 5;
      emptyCell.className = "text-muted";
      emptyCell.textContent = "No hooks yet. Describe one in the intent box above.";
      emptyRow.appendChild(emptyCell);
      hooksTbody.appendChild(emptyRow);
      return;
    }
    hooksList.forEach(function (hook) {
      var tr = document.createElement("tr");
      function td(text) {
        var cell = document.createElement("td");
        cell.textContent = text;
        return cell;
      }
      tr.appendChild(td(hook.id || ""));
      tr.appendChild(td(hook.table || (hook.on === "startup" ? "—" : "")));
      tr.appendChild(td(hook.on || ""));
      tr.appendChild(td(hook.enabled === false ? "no" : "yes"));
      var actionCell = document.createElement("td");
      var editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "btn btn-sm btn-outline-primary";
      editBtn.textContent = "Edit";
      editBtn.addEventListener("click", function () {
        openHookEditor(hook.id);
      });
      actionCell.appendChild(editBtn);
      tr.appendChild(actionCell);
      hooksTbody.appendChild(tr);
    });
  }

  function closeHookEditor() {
    currentHook = null;
    if (hookEditor) {
      hookEditor.hidden = true;
    }
    showHookEditorError("");
  }

  function openHookEditor(hookId) {
    showHookEditorError("");
    fetch("/api/hooks/" + encodeURIComponent(hookId))
      .then(function (res) {
        return res.json().then(function (body) {
          return { ok: res.ok, body: body };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          showHookEditorError(
            (result.body && result.body.error) || "Could not load hook."
          );
          return;
        }
        currentHook = result.body;
        if (hookEditorTitle) {
          var tableLabel =
            currentHook.on === "startup"
              ? "startup"
              : currentHook.table + " / " + currentHook.on;
          hookEditorTitle.textContent = currentHook.id + " (" + tableLabel + ")";
        }
        if (hookCodeEl) {
          hookCodeEl.value = currentHook.code || "";
        }
        if (hookToggleBtn) {
          hookToggleBtn.textContent =
            currentHook.enabled === false ? "Enable" : "Disable";
        }
        if (hookEditor) {
          hookEditor.hidden = false;
        }
      })
      .catch(function () {
        showHookEditorError("Could not load hook.");
      });
  }

  function showHookPreview(changed, sources) {
    if (!hookPreviewEl || !hookPreviewText) {
      return;
    }
    if (!changed || !changed.length) {
      hookPreviewEl.hidden = true;
      hookPreviewText.value = "";
      return;
    }
    var lines = changed.map(function (item) {
      return item.id + ": " + item.action;
    });
    if (sources && typeof sources === "object") {
      changed.forEach(function (item) {
        if (sources[item.id]) {
          lines.push("");
          lines.push("--- " + item.id + " ---");
          lines.push(sources[item.id]);
        }
      });
    }
    hookPreviewText.value = lines.join("\n");
    hookPreviewEl.hidden = false;
  }

  fetch("/api/schema")
    .then(function (res) {
      if (!res.ok) {
        return null;
      }
      return res.json();
    })
    .then(function (schema) {
      if (!schema) {
        return;
      }
      loadedSchema = schema;
      if (activeUiContext) {
        showUiContextChip(activeUiContext);
      }
      var name =
        schema.app && schema.app.title ? schema.app.title : "Desktopper";
      if (titleEl) {
        titleEl.textContent = "Ops — " + name;
      }
      document.title = "Ops — " + name;
      var ver = schema.version !== undefined ? schema.version : 0;
      schemaVersion = ver;
      setVersion(ver);
      if (bootstrapHintEl) {
        var screens = schema.screens;
        var emptySchema =
          ver === 0 || !Array.isArray(screens) || screens.length === 0;
        bootstrapHintEl.hidden = !emptySchema;
      }
      return loadThread();
    })
    .catch(function () {
      loadThread();
    });

  loadHooks();

  if (clearThreadBtn) {
    clearThreadBtn.addEventListener("click", function () {
      fetch("/api/ops/thread", { method: "DELETE" })
        .then(function (res) {
          if (!res.ok) {
            throw new Error("clear");
          }
          return loadThread();
        })
        .catch(function () {});
    });
  }

  function loadLogs() {
    fetch("/api/logs")
      .then(function (res) {
        if (!res.ok) {
          throw new Error("logs");
        }
        return res.json();
      })
      .then(function (data) {
        var text = JSON.stringify(data.events || [], null, 2);
        if (logsEl) {
          logsEl.value = text;
        }
        return text;
      });
  }

  if (formEl) {
    formEl.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (hookPreviewEl) {
        hookPreviewEl.hidden = true;
      }
      var text = textEl ? textEl.value.trim() : "";
      if (!text) {
        return;
      }
      sendIntent(text);
    });
  }

  if (hookSaveBtn) {
    hookSaveBtn.addEventListener("click", function () {
      if (!currentHook || !hookCodeEl) {
        return;
      }
      showHookEditorError("");
      fetch("/api/hooks/" + encodeURIComponent(currentHook.id), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: hookCodeEl.value }),
      })
        .then(function (res) {
          return res.json().then(function (body) {
            return { ok: res.ok, body: body };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            showHookEditorError(
              (result.body && result.body.error) || "Save failed."
            );
            return;
          }
          currentHook = result.body;
          loadHooks();
          loadLogs();
        })
        .catch(function () {
          showHookEditorError("Save failed.");
        });
    });
  }

  if (hookToggleBtn) {
    hookToggleBtn.addEventListener("click", function () {
      if (!currentHook) {
        return;
      }
      showHookEditorError("");
      var enabled = currentHook.enabled === false;
      fetch("/api/hooks/" + encodeURIComponent(currentHook.id), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: enabled }),
      })
        .then(function (res) {
          return res.json().then(function (body) {
            return { ok: res.ok, body: body };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            showHookEditorError(
              (result.body && result.body.error) || "Update failed."
            );
            return;
          }
          currentHook = result.body;
          if (hookToggleBtn) {
            hookToggleBtn.textContent =
              currentHook.enabled === false ? "Enable" : "Disable";
          }
          loadHooks();
          loadLogs();
        })
        .catch(function () {
          showHookEditorError("Update failed.");
        });
    });
  }

  if (hookDeleteBtn && confirmModalOk) {
    hookDeleteBtn.addEventListener("click", function () {
      if (!currentHook) {
        return;
      }
      var modalEl = document.getElementById("confirm-modal");
      var bodyEl = document.getElementById("confirm-modal-body");
      if (bodyEl) {
        bodyEl.textContent = "Delete hook " + currentHook.id + "?";
      }
      if (window.bootstrap && modalEl) {
        var modal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
        modal.show();
        confirmModalOk.onclick = function () {
          fetch("/api/hooks/" + encodeURIComponent(currentHook.id), {
            method: "DELETE",
          })
            .then(function (res) {
              if (!res.ok) {
                return res.json().then(function (body) {
                  throw new Error((body && body.error) || "Delete failed.");
                });
              }
            })
            .then(function () {
              modal.hide();
              closeHookEditor();
              loadHooks();
              loadLogs();
            })
            .catch(function (err) {
              showHookEditorError(err.message || "Delete failed.");
              modal.hide();
            });
        };
      }
    });
  }

  if (hookCancelBtn) {
    hookCancelBtn.addEventListener("click", closeHookEditor);
  }

  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      fetch("/api/logs")
        .then(function (res) {
          if (!res.ok) {
            throw new Error("logs");
          }
          return res.json();
        })
        .then(function (data) {
          var text = JSON.stringify(data.events || [], null, 2);
          if (logsEl) {
            logsEl.value = text;
          }
          if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(text);
          }
        })
        .catch(function () {
          if (logsEl) {
            logsEl.value = "Could not load logs.";
          }
        });
    });
  }

  var remindersTbody = document.getElementById("reminders-tbody");
  var reminderEditor = document.getElementById("reminder-editor");
  var reminderNewBtn = document.getElementById("reminder-new");
  var reminderSaveBtn = document.getElementById("reminder-save");
  var reminderDisableBtn = document.getElementById("reminder-disable");
  var reminderCancelBtn = document.getElementById("reminder-cancel");
  var reminderEditorError = document.getElementById("reminder-editor-error");
  var schedulerStatusEl = document.getElementById("scheduler-status");
  var editingReminderId = null;

  function showReminderError(msg) {
    if (!reminderEditorError) return;
    if (!msg) {
      reminderEditorError.hidden = true;
      reminderEditorError.textContent = "";
      return;
    }
    reminderEditorError.hidden = false;
    reminderEditorError.textContent = msg;
  }

  function loadReminders() {
    if (!remindersTbody) return;
    fetch("/api/reminders")
      .then(function (res) { return res.json(); })
      .then(function (data) {
        remindersTbody.textContent = "";
        (data.reminders || []).forEach(function (rem) {
          var tr = document.createElement("tr");
          function td(text) {
            var cell = document.createElement("td");
            cell.textContent = text;
            return cell;
          }
          tr.appendChild(td(rem.id || ""));
          tr.appendChild(td(rem.title || ""));
          tr.appendChild(td(rem.schedule_summary || ""));
          tr.appendChild(td(rem.next_run_at || "—"));
          tr.appendChild(td(rem.enabled === false ? "off" : "on"));
          var actionCell = document.createElement("td");
          var editBtn = document.createElement("button");
          editBtn.type = "button";
          editBtn.className = "btn btn-sm btn-link";
          editBtn.textContent = "Edit";
          editBtn.addEventListener("click", function () {
            openReminderEditor(rem);
          });
          actionCell.appendChild(editBtn);
          tr.appendChild(actionCell);
          remindersTbody.appendChild(tr);
        });
      });
  }

  function openReminderEditor(rem) {
    editingReminderId = rem ? rem.id : null;
    if (reminderEditor) reminderEditor.hidden = false;
    document.getElementById("reminder-id").value = rem ? rem.id : "";
    document.getElementById("reminder-id").disabled = !!rem;
    document.getElementById("reminder-title").value = rem ? rem.title : "";
    document.getElementById("reminder-body").value = rem ? (rem.body || "") : "";
    var schedule = (rem && rem.schedule) || { kind: "once" };
    document.getElementById("reminder-kind").value = schedule.kind || "once";
    var val = "";
    if (schedule.kind === "once") val = schedule.at || "";
    else if (schedule.kind === "daily" || schedule.kind === "weekly") val = schedule.time || "";
    else if (schedule.kind === "interval") val = String(schedule.every_seconds || 3600);
    document.getElementById("reminder-schedule-val").value = val;
    showReminderError("");
  }

  function buildReminderBody() {
    var kind = document.getElementById("reminder-kind").value;
    var val = document.getElementById("reminder-schedule-val").value.trim();
    var schedule = { kind: kind };
    if (kind === "once") schedule.at = val;
    else if (kind === "daily") schedule.time = val;
    else if (kind === "weekly") { schedule.time = val; schedule.weekday = 0; }
    else if (kind === "interval") schedule.every_seconds = parseInt(val, 10) || 3600;
    return {
      id: document.getElementById("reminder-id").value.trim(),
      title: document.getElementById("reminder-title").value.trim(),
      body: document.getElementById("reminder-body").value.trim(),
      enabled: true,
      schedule: schedule,
      action: { kind: "notify" },
    };
  }

  if (reminderNewBtn) {
    reminderNewBtn.addEventListener("click", function () { openReminderEditor(null); });
  }
  if (reminderCancelBtn) {
    reminderCancelBtn.addEventListener("click", function () {
      if (reminderEditor) reminderEditor.hidden = true;
      editingReminderId = null;
    });
  }
  if (reminderSaveBtn) {
    reminderSaveBtn.addEventListener("click", function () {
      var body = buildReminderBody();
      var url = editingReminderId ? "/api/reminders/" + encodeURIComponent(editingReminderId) : "/api/reminders";
      var method = editingReminderId ? "PATCH" : "POST";
      if (!editingReminderId && !body.id) {
        showReminderError("Id is required.");
        return;
      }
      fetch(url, {
        method: method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            if (!res.ok) throw new Error(data.error || res.statusText);
            return data;
          });
        })
        .then(function () {
          if (reminderEditor) reminderEditor.hidden = true;
          loadReminders();
        })
        .catch(function (err) { showReminderError(err.message); });
    });
  }
  if (reminderDisableBtn) {
    reminderDisableBtn.addEventListener("click", function () {
      if (!editingReminderId) return;
      fetch("/api/reminders/" + encodeURIComponent(editingReminderId) + "/dismiss", { method: "POST" })
        .then(function () {
          if (reminderEditor) reminderEditor.hidden = true;
          loadReminders();
        });
    });
  }

  function loadSchedulerStatus() {
    if (!schedulerStatusEl) return;
    fetch("/api/scheduler/status")
      .then(function (res) { return res.json(); })
      .then(function (data) {
        schedulerStatusEl.textContent = "Scheduler last tick: " + (data.last_tick_at || "never");
      });
  }

  loadReminders();
  loadSchedulerStatus();

  var syncExportBtn = document.getElementById("sync-export");
  var syncImportFile = document.getElementById("sync-import-file");
  var syncStatusEl = document.getElementById("sync-status");

  if (syncExportBtn) {
    syncExportBtn.addEventListener("click", function () {
      fetch("/api/sync/export")
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          if (syncStatusEl) {
            syncStatusEl.textContent =
              "Exported " + String(data.count || 0) + " events to " + (data.path || "sync_out");
          }
        })
        .catch(function () {
          if (syncStatusEl) {
            syncStatusEl.textContent = "Sync export failed.";
          }
        });
    });
  }

  if (syncImportFile) {
    syncImportFile.addEventListener("change", function () {
      var file = syncImportFile.files && syncImportFile.files[0];
      if (!file) {
        return;
      }
      var reader = new FileReader();
      reader.onload = function () {
        try {
          var payload = JSON.parse(String(reader.result || "{}"));
          fetch("/api/sync/import", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          })
            .then(function (res) {
              return res.json();
            })
            .then(function (data) {
              if (syncStatusEl) {
                syncStatusEl.textContent =
                  "Imported " + String(data.applied || 0) + " events, skipped " + String(data.skipped || 0);
              }
            })
            .catch(function () {
              if (syncStatusEl) {
                syncStatusEl.textContent = "Sync import failed.";
              }
            });
        } catch (e) {
          if (syncStatusEl) {
            syncStatusEl.textContent = "Invalid JSON file.";
          }
        }
      };
      reader.readAsText(file);
      syncImportFile.value = "";
    });
  }
})();
