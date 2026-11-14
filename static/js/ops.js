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
  var opsHelp = null;
  var lastThreadEntries = [];
  var pendingUserText = null;
  var intentBusy = false;
  var activePack = null;
  var packAwaitingApply = false;
  var packStepSubmitted = false;

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
  var opsPrefill = readOpsPrefill();
  if (opsPrefill && textEl) {
    textEl.value = opsPrefill;
  }

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
    } else if (action === "help") {
      label = "Help";
      cls = "bg-secondary";
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
    var capped = [];
    var userCount = 0;
    var asstCount = 0;
    var i;
    for (i = (entries || []).length - 1; i >= 0; i--) {
      var entry = entries[i];
      if (entry.role === "user" && (entry.text || "").trim().toLowerCase() === "help") {
        continue;
      }
      if (entry.role === "assistant" && entry.action === "help") {
        continue;
      }
      if (entry.role === "user") {
        if (userCount >= 10) {
          continue;
        }
        userCount++;
      } else if (entry.role === "assistant") {
        if (asstCount >= 10) {
          continue;
        }
        asstCount++;
      } else {
        continue;
      }
      capped.unshift(entry);
    }
    var history = [];
    capped.forEach(function (entry) {
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

  function readOpsPrefill() {
    try {
      var prefill = sessionStorage.getItem("desktopper_ops_prefill");
      if (prefill) {
        sessionStorage.removeItem("desktopper_ops_prefill");
        return prefill;
      }
    } catch (e) {}
    return "";
  }

  function renderHelpContent(parent, showFooter) {
    if (!opsHelp) {
      return;
    }
    parent.appendChild(el("strong", { text: opsHelp.title || "How this works" }));
    var ul = el("ul", { className: "small mb-0 mt-2 ps-3" });
    (opsHelp.lines || []).forEach(function (line) {
      ul.appendChild(el("li", { text: line }));
    });
    parent.appendChild(ul);
    if (activeUiContext) {
      parent.appendChild(
        el("p", {
          className: "small text-muted mb-0 mt-2",
          text:
            'You opened Ops from the App — say "this column" or "this screen" and the assistant knows what you mean.',
        })
      );
    }
    if (showFooter && opsHelp.footer) {
      parent.appendChild(
        el("p", { className: "small text-muted mb-0 mt-2", text: opsHelp.footer })
      );
    }
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
    if (entry.role === "assistant" && entry.action === "help") {
      renderHelpContent(wrap, true);
      return wrap;
    }
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
          text: "Schema version " + String(entry.version) + ". Return to the App and refresh.",
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

  function renderPendingWorking() {
    var wrap = el("div", {
      className: "mb-3",
      id: "ops-thread-pending",
    });
    var head = el("div", { className: "d-flex align-items-center mb-1 gap-2" });
    head.appendChild(
      el("span", { className: "badge bg-secondary me-2", text: "Working" })
    );
    head.appendChild(el("strong", { text: "App" }));
    var spinner = el("div", {
      className: "spinner-border spinner-border-sm text-secondary",
    });
    spinner.setAttribute("role", "status");
    spinner.setAttribute("aria-hidden", "true");
    head.appendChild(spinner);
    wrap.appendChild(head);
    wrap.appendChild(
      el("div", {
        className: "text-muted",
        text: "Thinking… the model is preparing a reply.",
      })
    );
    return wrap;
  }

  function renderThread(entries) {
    if (!threadEl) {
      return;
    }
    lastThreadEntries = entries || [];
    while (threadEl.firstChild) {
      threadEl.removeChild(threadEl.firstChild);
    }
    if ((!entries || !entries.length) && !pendingUserText) {
      var welcome = el("div", { className: "ops-help-welcome text-muted" });
      renderHelpContent(welcome, true);
      threadEl.appendChild(welcome);
      return;
    }
    (entries || []).forEach(function (entry) {
      threadEl.appendChild(renderThreadEntry(entry));
    });
    if (pendingUserText) {
      threadEl.appendChild(
        renderThreadEntry({ role: "user", text: pendingUserText })
      );
      threadEl.appendChild(renderPendingWorking());
    }
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
    pendingUserText = "(apply plan)";
    setBusy(true);
    renderThread(lastThreadEntries);
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
        pendingUserText = null;
        loadLogs();
        loadThread();
        if (!result.ok) {
          if (packAwaitingApply) {
            packAwaitingApply = false;
            renderPackSteps();
          }
          return;
        }
        loadReminders();
        loadRules();
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
        if (
          packAwaitingApply &&
          result.body &&
          result.body.action === "apply"
        ) {
          packAwaitingApply = false;
          completeCurrentPackStep();
        }
      })
      .catch(function () {
        pendingUserText = null;
        loadLogs();
        loadThread();
        if (packAwaitingApply) {
          packAwaitingApply = false;
          renderPackSteps();
        }
      })
      .then(function () {
        setBusy(false);
      });
  }

  function sendHelp() {
    pendingUserText = "help";
    if (textEl) {
      textEl.value = "";
    }
    setBusy(true);
    renderThread(lastThreadEntries);
    return fetch("/api/ops/thread/help", { method: "POST" })
      .then(function (res) {
        return res.json().then(function (body) {
          return { ok: res.ok, body: body };
        });
      })
      .then(function (result) {
        pendingUserText = null;
        if (result.ok && result.body && result.body.help) {
          opsHelp = result.body.help;
        }
        return loadThread();
      })
      .catch(function () {
        pendingUserText = null;
        return loadThread();
      })
      .then(function () {
        setBusy(false);
      });
  }

  function sendIntent(text) {
    pendingUserText = text;
    if (textEl) {
      textEl.value = "";
    }
    setBusy(true);
    renderThread(lastThreadEntries);
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
        pendingUserText = null;
        loadLogs();
        loadThread();
        if (!result.ok) {
          notePackIntentResult(result);
          return result;
        }
        loadReminders();
        loadRules();
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
        loadHooks();
        closeHookEditor();
        notePackIntentResult(result);
        return result;
      })
      .catch(function () {
        pendingUserText = null;
        loadLogs();
        loadThread();
        notePackIntentResult(null);
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
        if (data.help) {
          opsHelp = data.help;
        }
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
    intentBusy = !!busy;
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
    renderPackSteps();
  }

  function expandOpsSection(panelId) {
    var panel = document.getElementById(panelId);
    if (!panel || !window.bootstrap) {
      return;
    }
    var collapse = window.bootstrap.Collapse.getOrCreateInstance(panel, { toggle: false });
    collapse.show();
  }

  function setSectionCount(node, count) {
    if (!node) {
      return;
    }
    if (!count) {
      node.textContent = "";
      return;
    }
    node.textContent = " (" + String(count) + ")";
  }

  function parsePromptPack(markdown, filename) {
    var titleMatch = /^#\s+(.+?)\s*$/m.exec(markdown || "");
    var title = titleMatch
      ? titleMatch[1].trim()
      : String(filename || "Prompt pack")
          .replace(/\.md$/i, "")
          .replace(/[-_]+/g, " ");
    var stepRe = /^##\s+(?:Prompt|Step)\s+(\d+)\s*[—–\-]\s*(.+?)\s*$/gim;
    var matches = [];
    var m;
    while ((m = stepRe.exec(markdown)) !== null) {
      matches.push({
        index: m.index,
        end: m.index + m[0].length,
        title: m[2].trim(),
      });
    }
    var steps = [];
    var i;
    for (i = 0; i < matches.length; i++) {
      var start = matches[i].end;
      var end = i + 1 < matches.length ? matches[i + 1].index : markdown.length;
      var body = markdown.slice(start, end);
      var skipMatch = /^##\s+(How to run|If Ops goes sideways)\b/im.exec(body);
      if (skipMatch) {
        body = body.slice(0, skipMatch.index);
      }
      var fence = /```(?:text)?\s*\n([\s\S]*?)```/i.exec(body);
      if (!fence) {
        continue;
      }
      var intent = fence[1].trim();
      var prose = body.replace(/```(?:text)?\s*\n[\s\S]*?```/gi, "");
      var optional =
        /optional/i.test(matches[i].title) || /optional/i.test(prose);
      steps.push({
        index: steps.length,
        title: matches[i].title,
        intent: intent,
        optional: optional,
      });
    }
    return { title: title, steps: steps };
  }

  function setPackStatus(msg) {
    var statusEl = document.getElementById("packs-status");
    if (statusEl) {
      statusEl.textContent = msg || "";
    }
  }

  function activatePack(pack, filename) {
    if (!pack || !pack.steps || !pack.steps.length) {
      setPackStatus("No steps found in pack.");
      return;
    }
    activePack = {
      title: pack.title || filename || "Prompt pack",
      filename: filename || pack.filename || "",
      steps: pack.steps,
      currentIndex: 0,
      completed: {},
    };
    packAwaitingApply = false;
    packStepSubmitted = false;
    setPackStatus("");
    expandOpsSection("packs-panel");
    renderActivePack();
  }

  function completeCurrentPackStep() {
    if (!activePack) {
      return;
    }
    var idx = activePack.currentIndex;
    activePack.completed[idx] = true;
    if (idx + 1 < activePack.steps.length) {
      activePack.currentIndex = idx + 1;
    }
    renderActivePack();
  }

  function notePackIntentResult(result) {
    if (!activePack) {
      return;
    }
    if (!packStepSubmitted) {
      if (packAwaitingApply) {
        packAwaitingApply = false;
        renderPackSteps();
      }
      return;
    }
    packStepSubmitted = false;
    if (!result || !result.ok || !result.body) {
      packAwaitingApply = false;
      renderPackSteps();
      return;
    }
    var action = result.body.action;
    if (action === "apply") {
      packAwaitingApply = false;
      completeCurrentPackStep();
      return;
    }
    if (action === "propose") {
      packAwaitingApply = true;
      renderPackSteps();
      return;
    }
    packAwaitingApply = false;
    renderPackSteps();
  }

  function runPackStep(index) {
    if (!activePack || intentBusy) {
      return;
    }
    if (index !== activePack.currentIndex) {
      return;
    }
    if (activePack.completed[index]) {
      return;
    }
    var step = activePack.steps[index];
    if (!step || !step.intent) {
      return;
    }
    packStepSubmitted = true;
    packAwaitingApply = false;
    sendIntent(step.intent);
  }

  function skipPackStep(index) {
    if (!activePack || intentBusy) {
      return;
    }
    if (index !== activePack.currentIndex) {
      return;
    }
    var step = activePack.steps[index];
    if (!step || !step.optional) {
      return;
    }
    packAwaitingApply = false;
    packStepSubmitted = false;
    completeCurrentPackStep();
  }

  function renderActivePack() {
    var activeEl = document.getElementById("packs-active");
    var titleElPack = document.getElementById("packs-active-title");
    var progressEl = document.getElementById("packs-progress");
    if (!activePack) {
      if (activeEl) {
        activeEl.hidden = true;
      }
      return;
    }
    if (activeEl) {
      activeEl.hidden = false;
    }
    if (titleElPack) {
      titleElPack.textContent = activePack.title;
    }
    if (progressEl) {
      progressEl.textContent =
        "Step " +
        String(activePack.currentIndex + 1) +
        "/" +
        String(activePack.steps.length);
    }
    renderPackSteps();
  }

  function renderPackSteps() {
    var stepsEl = document.getElementById("packs-steps");
    if (!stepsEl) {
      return;
    }
    while (stepsEl.firstChild) {
      stepsEl.removeChild(stepsEl.firstChild);
    }
    if (!activePack) {
      return;
    }
    var i;
    for (i = 0; i < activePack.steps.length; i++) {
      (function (stepIndex) {
        var step = activePack.steps[stepIndex];
        var done = !!activePack.completed[stepIndex];
        var current = stepIndex === activePack.currentIndex && !done;
        var locked = stepIndex > activePack.currentIndex;
        var row = el("div", {
          className:
            "d-flex flex-wrap align-items-center gap-2 mb-2" +
            (locked ? " text-muted" : ""),
        });
        var label = "Step " + String(stepIndex + 1) + "/" + String(activePack.steps.length);
        label += "  " + step.title;
        if (step.optional) {
          label += " (optional)";
        }
        if (done) {
          label += " — done";
        } else if (locked) {
          label += " — locked";
        } else if (packAwaitingApply && current) {
          label += " — apply the plan above";
        }
        row.appendChild(el("span", { className: "small flex-grow-1", text: label }));
        if (current && !done) {
          var runBtn = el("button", {
            className: "btn btn-sm btn-primary",
            text: "Run step",
            type: "button",
          });
          runBtn.disabled = intentBusy;
          runBtn.addEventListener("click", function () {
            runPackStep(stepIndex);
          });
          row.appendChild(runBtn);
          if (step.optional) {
            var skipBtn = el("button", {
              className: "btn btn-sm btn-outline-secondary",
              text: "Skip",
              type: "button",
            });
            skipBtn.disabled = intentBusy;
            skipBtn.addEventListener("click", function () {
              skipPackStep(stepIndex);
            });
            row.appendChild(skipBtn);
          }
        }
        stepsEl.appendChild(row);
      })(i);
    }
  }

  function renderShippedPacks(packs) {
    var shippedEl = document.getElementById("packs-shipped");
    var countEl = document.getElementById("packs-count");
    if (!shippedEl) {
      return;
    }
    while (shippedEl.firstChild) {
      shippedEl.removeChild(shippedEl.firstChild);
    }
    setSectionCount(countEl, packs && packs.length ? packs.length : 0);
    if (!packs || !packs.length) {
      shippedEl.appendChild(
        el("span", { className: "text-muted small", text: "No shipped packs." })
      );
      return;
    }
    packs.forEach(function (pack) {
      var btn = el("button", {
        className: "btn btn-sm btn-outline-secondary",
        text: pack.filename || pack.id || pack.title,
        type: "button",
      });
      btn.addEventListener("click", function () {
        var name = pack.filename || pack.id;
        fetch("/api/ops/packs/" + encodeURIComponent(name))
          .then(function (res) {
            return res.json().then(function (body) {
              return { ok: res.ok, body: body };
            });
          })
          .then(function (result) {
            if (!result.ok) {
              setPackStatus((result.body && result.body.error) || "Pack not found.");
              return;
            }
            activatePack(result.body, result.body.filename || name);
          })
          .catch(function () {
            setPackStatus("Failed to load pack.");
          });
      });
      shippedEl.appendChild(btn);
    });
  }

  function loadShippedPacks() {
    fetch("/api/ops/packs")
      .then(function (res) {
        return res.ok ? res.json() : { packs: [] };
      })
      .then(function (data) {
        renderShippedPacks(data.packs || []);
      })
      .catch(function () {
        renderShippedPacks([]);
      });
  }

  function bindPacksUi() {
    var fileInput = document.getElementById("packs-file");
    if (fileInput) {
      fileInput.addEventListener("change", function () {
        var file = fileInput.files && fileInput.files[0];
        if (!file) {
          return;
        }
        var reader = new FileReader();
        reader.onload = function () {
          try {
            var parsed = parsePromptPack(String(reader.result || ""), file.name);
            activatePack(parsed, file.name);
          } catch (e) {
            setPackStatus("Could not parse pack file.");
          }
        };
        reader.onerror = function () {
          setPackStatus("Could not read pack file.");
        };
        reader.readAsText(file);
        fileInput.value = "";
      });
    }
    loadShippedPacks();
  }

  var remindersCountEl = document.getElementById("reminders-count");
  var rulesCountEl = document.getElementById("rules-count");
  var hooksCountEl = document.getElementById("hooks-count");
  var usersCountEl = document.getElementById("users-count");
  var logsPanelEl = document.getElementById("logs-panel");
  var logsLoaded = false;
  var rulesList = [];
  var rulesTbody = document.getElementById("rules-tbody");

  if (logsPanelEl) {
    logsPanelEl.addEventListener("shown.bs.collapse", function () {
      if (!logsLoaded) {
        logsLoaded = true;
        loadLogs();
      }
    });
  }

  function summarizeWhenExpr(expr) {
    if (!expr || typeof expr !== "object") {
      return "";
    }
    var op = expr.op;
    if (op === "eq" || op === "neq" || op === "lt" || op === "lte" || op === "gt" || op === "gte") {
      var left = summarizeWhenExpr(expr.left);
      var right = summarizeWhenExpr(expr.right);
      var sym = { eq: "=", neq: "≠", lt: "<", lte: "≤", gt: ">", gte: "≥" }[op] || op;
      if (left && right) {
        return left + " " + sym + " " + right;
      }
    }
    if (op === "and" || op === "or") {
      var parts = (expr.args || []).map(summarizeWhenExpr).filter(Boolean);
      if (parts.length) {
        return parts.join(" " + op + " ");
      }
    }
    if (op === "not") {
      var inner = summarizeWhenExpr(expr.arg || (expr.args && expr.args[0]));
      return inner ? "not (" + inner + ")" : "";
    }
    if (op === "col") {
      return String(expr.column || "");
    }
    if (op === "lit") {
      return JSON.stringify(expr.value);
    }
    if (op === "now") {
      return "now";
    }
    try {
      var raw = JSON.stringify(expr);
      return raw.length > 48 ? raw.slice(0, 45) + "…" : raw;
    } catch (e) {
      return "";
    }
  }

  function summarizeTrigger(trigger) {
    if (!trigger || typeof trigger !== "object") {
      return "";
    }
    if (trigger.kind === "on_write") {
      return "on_write";
    }
    if (trigger.kind === "schedule") {
      var every = trigger.every_seconds;
      if (typeof every === "number" && every > 0) {
        if (every % 3600 === 0) {
          return "schedule " + every / 3600 + "h";
        }
        if (every % 60 === 0) {
          return "schedule " + every / 60 + "m";
        }
        return "schedule " + every + "s";
      }
      return "schedule";
    }
    return String(trigger.kind || "");
  }

  function summarizeThen(thenList) {
    if (!Array.isArray(thenList) || !thenList.length) {
      return "";
    }
    return thenList
      .map(function (action) {
        if (!action || typeof action !== "object") {
          return "";
        }
        var kind = action.kind || "";
        if (kind === "notify" && action.title) {
          return "notify (" + action.title + ")";
        }
        if (kind === "set_column" && action.column) {
          return "set_column " + action.column;
        }
        return kind;
      })
      .filter(Boolean)
      .join(", ");
  }

  function loadRules() {
    return fetch("/api/rules")
      .then(function (res) {
        if (!res.ok) {
          throw new Error("rules");
        }
        return res.json();
      })
      .then(function (data) {
        rulesList = data.rules || [];
        renderRulesTable();
        setSectionCount(rulesCountEl, rulesList.length);
      })
      .catch(function () {
        rulesList = [];
        renderRulesTable();
        setSectionCount(rulesCountEl, 0);
      });
  }

  function renderRulesTable() {
    if (!rulesTbody) {
      return;
    }
    rulesTbody.textContent = "";
    if (!rulesList.length) {
      var emptyRow = document.createElement("tr");
      var emptyCell = document.createElement("td");
      emptyCell.colSpan = 6;
      emptyCell.className = "text-muted";
      emptyCell.textContent = "No rules yet. Describe one in the conversation above.";
      emptyRow.appendChild(emptyCell);
      rulesTbody.appendChild(emptyRow);
      return;
    }
    rulesList.forEach(function (rule) {
      var tr = document.createElement("tr");
      function td(text) {
        var cell = document.createElement("td");
        cell.textContent = text;
        return cell;
      }
      tr.appendChild(td(rule.id || ""));
      tr.appendChild(td(rule.table || ""));
      tr.appendChild(td(summarizeTrigger(rule.trigger)));
      tr.appendChild(td(summarizeWhenExpr(rule.when) || "—"));
      tr.appendChild(td(summarizeThen(rule.then) || "—"));
      var actionCell = document.createElement("td");
      actionCell.className = "text-nowrap";
      var toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.className = "btn btn-sm btn-outline-secondary me-1";
      toggleBtn.textContent = rule.enabled === false ? "Enable" : "Disable";
      toggleBtn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var nextEnabled = rule.enabled === false;
        fetch("/api/rules/" + encodeURIComponent(rule.id), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: nextEnabled }),
        })
          .then(function (res) {
            if (!res.ok) {
              throw new Error("patch");
            }
            return loadRules();
          })
          .catch(function () {});
      });
      actionCell.appendChild(toggleBtn);
      var deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "btn btn-sm btn-outline-danger me-1";
      deleteBtn.textContent = "Delete";
      deleteBtn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        confirmDeleteRule(rule.id);
      });
      actionCell.appendChild(deleteBtn);
      var expandBtn = document.createElement("button");
      expandBtn.type = "button";
      expandBtn.className = "btn btn-sm btn-link";
      expandBtn.textContent = "JSON";
      expandBtn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var next = tr.nextSibling;
        if (next && next.getAttribute && next.getAttribute("data-rule-expand") === rule.id) {
          rulesTbody.removeChild(next);
          return;
        }
        var expandRow = document.createElement("tr");
        expandRow.setAttribute("data-rule-expand", rule.id);
        var expandCell = document.createElement("td");
        expandCell.colSpan = 6;
        var pre = document.createElement("pre");
        pre.className = "small mb-0";
        pre.textContent = JSON.stringify(
          { when: rule.when, then: rule.then },
          null,
          2
        );
        expandCell.appendChild(pre);
        expandRow.appendChild(expandCell);
        if (next) {
          rulesTbody.insertBefore(expandRow, next);
        } else {
          rulesTbody.appendChild(expandRow);
        }
      });
      actionCell.appendChild(expandBtn);
      tr.appendChild(actionCell);
      rulesTbody.appendChild(tr);
    });
  }

  function confirmDeleteRule(ruleId) {
    var modalEl = document.getElementById("confirm-modal");
    var bodyEl = document.getElementById("confirm-modal-body");
    if (bodyEl) {
      bodyEl.textContent =
        "Remove rule " +
        ruleId +
        " from the schema? Past notices stay.";
    }
    if (!(window.bootstrap && modalEl && confirmModalOk)) {
      return;
    }
    var modal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
    confirmModalOk.onclick = function () {
      fetch("/api/rules/" + encodeURIComponent(ruleId), { method: "DELETE" })
        .then(function (res) {
          if (!res.ok) {
            throw new Error("delete");
          }
        })
        .then(function () {
          modal.hide();
          loadRules();
          loadLogs();
        })
        .catch(function () {
          modal.hide();
        });
    };
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
        setSectionCount(hooksCountEl, hooksList.length);
      })
      .catch(function () {
        hooksList = [];
        renderHooksTable();
        setSectionCount(hooksCountEl, 0);
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
    expandOpsSection("hooks-panel");
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
    expandOpsSection("hooks-panel");
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
      return loadThread().then(function () {
        loadSession();
      });
    })
    .catch(function () {
      loadThread();
      loadSession();
    });

  loadHooks();
  loadRules();

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
    logsLoaded = true;
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
      if (text.toLowerCase() === "help") {
        sendHelp();
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
        var reminders = data.reminders || [];
        setSectionCount(remindersCountEl, reminders.length);
        reminders.forEach(function (rem) {
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
    expandOpsSection("reminders-panel");
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
  bindPacksUi();

  var usersTbody = document.getElementById("users-tbody");
  var usersHintEl = document.getElementById("users-hint");
  var usersOwnerUiEl = document.getElementById("users-owner-ui");
  var userEditor = document.getElementById("user-editor");
  var userNewBtn = document.getElementById("user-new");
  var userSaveBtn = document.getElementById("user-save");
  var userCancelBtn = document.getElementById("user-cancel");
  var userEditorError = document.getElementById("user-editor-error");
  var userRoleSelect = document.getElementById("user-role");
  var sessionUser = null;

  function showUserError(msg) {
    if (!userEditorError) {
      return;
    }
    if (!msg) {
      userEditorError.hidden = true;
      userEditorError.textContent = "";
      return;
    }
    userEditorError.hidden = false;
    userEditorError.textContent = msg;
  }

  function populateUserRoles() {
    if (!userRoleSelect) {
      return;
    }
    userRoleSelect.textContent = "";
    var roles = ["guest"];
    if (loadedSchema && Array.isArray(loadedSchema.roles)) {
      loadedSchema.roles.forEach(function (role) {
        if (role && role.name && role.name !== "owner" && roles.indexOf(role.name) === -1) {
          roles.push(role.name);
        }
      });
    }
    roles.forEach(function (role) {
      var opt = document.createElement("option");
      opt.value = role;
      opt.textContent = role;
      userRoleSelect.appendChild(opt);
    });
  }

  function loadUsers() {
    if (!usersTbody) {
      return;
    }
    fetch("/api/users", { credentials: "same-origin" })
      .then(function (res) {
        if (res.status === 403) {
          return null;
        }
        if (!res.ok) {
          throw new Error("users");
        }
        return res.json();
      })
      .then(function (data) {
        if (!data) {
          return;
        }
        usersTbody.textContent = "";
        var users = data.users || [];
        setSectionCount(usersCountEl, users.length);
        users.forEach(function (user) {
          var tr = document.createElement("tr");
          function td(text) {
            var cell = document.createElement("td");
            cell.textContent = text;
            return cell;
          }
          tr.appendChild(td(user.name || ""));
          tr.appendChild(td(user.role || ""));
          tr.appendChild(td(user.created_at || ""));
          usersTbody.appendChild(tr);
        });
      })
      .catch(function () {});
  }

  function loadSession() {
    fetch("/api/session", { credentials: "same-origin" })
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        sessionUser = data.user || null;
        var isOwner = sessionUser && sessionUser.role === "owner";
        if (usersHintEl) {
          usersHintEl.hidden = isOwner;
        }
        if (usersOwnerUiEl) {
          usersOwnerUiEl.hidden = !isOwner;
        }
        if (settingsHintEl) {
          settingsHintEl.hidden = isOwner;
        }
        if (settingsOwnerUiEl) {
          settingsOwnerUiEl.hidden = !isOwner;
        }
        if (isOwner) {
          loadDaemonStatus();
        }
        if (isOwner) {
          populateUserRoles();
          loadUsers();
        } else if (usersCountEl) {
          usersCountEl.textContent = "";
        }
      })
      .catch(function () {});
  }

  var settingsHintEl = document.getElementById("settings-hint");
  var settingsOwnerUiEl = document.getElementById("settings-owner-ui");
  var daemonStatusEl = document.getElementById("daemon-status");
  var daemonRestartBtn = document.getElementById("daemon-restart");
  var daemonRestartStatusEl = document.getElementById("daemon-restart-status");
  var daemonPid = null;

  function describeDaemon(data) {
    if (data.managed_by === "launchagent") {
      return "Running as LaunchAgent " + data.label + ".";
    }
    if (data.managed_by === "pidfile") {
      return "Running in the background (started with `desktopper daemon start`).";
    }
    var msg = "This server is not running as the daemon, so it cannot restart itself.";
    if (data.installed) {
      msg += " LaunchAgent " + data.label + " is installed but does not own this server.";
    } else {
      msg += " Run `desktopper daemon install` to run it as a LaunchAgent.";
    }
    return msg;
  }

  function showDaemon(data) {
    daemonPid = data.pid;
    setText(daemonStatusEl, describeDaemon(data));
    if (daemonRestartBtn) {
      daemonRestartBtn.disabled = !data.managed_by;
    }
  }

  function loadDaemonStatus() {
    if (!daemonStatusEl) {
      return;
    }
    fetch("/api/daemon", { credentials: "same-origin" })
      .then(function (res) {
        if (!res.ok) {
          throw new Error("daemon");
        }
        return res.json();
      })
      .then(showDaemon)
      .catch(function () {
        setText(daemonStatusEl, "Could not read the daemon status.");
      });
  }

  function waitForRestart(attempt) {
    // The old process can still answer for a moment; wait for a new pid.
    fetch("/api/daemon", { credentials: "same-origin", cache: "no-store" })
      .then(function (res) {
        if (!res.ok) {
          throw new Error("down");
        }
        return res.json();
      })
      .then(function (data) {
        if (data.pid === daemonPid) {
          throw new Error("old");
        }
        setText(daemonRestartStatusEl, "Desktopper restarted.");
        showDaemon(data);
      })
      .catch(function () {
        if (attempt >= 40) {
          setText(daemonRestartStatusEl, "Desktopper did not come back. See daemon.log in the app directory.");
          daemonRestartBtn.disabled = false;
          return;
        }
        setTimeout(function () {
          waitForRestart(attempt + 1);
        }, 750);
      });
  }

  if (daemonRestartBtn) {
    daemonRestartBtn.addEventListener("click", function () {
      if (!window.confirm("Restart the Desktopper daemon? This page reconnects when it is back.")) {
        return;
      }
      daemonRestartBtn.disabled = true;
      setText(daemonRestartStatusEl, "Restarting…");
      fetch("/api/daemon/restart", { method: "POST", credentials: "same-origin" })
        .then(function (res) {
          return res.json().then(function (body) {
            return { ok: res.ok, body: body };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            setText(daemonRestartStatusEl, result.body.error || "Restart failed.");
            daemonRestartBtn.disabled = false;
            return;
          }
          waitForRestart(0);
        })
        .catch(function () {
          setText(daemonRestartStatusEl, "Restart failed.");
          daemonRestartBtn.disabled = false;
        });
    });
  }

  function openUserEditor() {
    expandOpsSection("users-panel");
    populateUserRoles();
    if (userEditor) {
      userEditor.hidden = false;
    }
    var nameEl = document.getElementById("user-name");
    var passwordEl = document.getElementById("user-password");
    if (nameEl) {
      nameEl.value = "";
    }
    if (passwordEl) {
      passwordEl.value = "";
    }
    if (userRoleSelect && userRoleSelect.options.length) {
      userRoleSelect.selectedIndex = 0;
    }
    showUserError("");
  }

  if (userNewBtn) {
    userNewBtn.addEventListener("click", function () {
      openUserEditor();
    });
  }
  if (userCancelBtn) {
    userCancelBtn.addEventListener("click", function () {
      if (userEditor) {
        userEditor.hidden = true;
      }
      showUserError("");
    });
  }
  if (userSaveBtn) {
    userSaveBtn.addEventListener("click", function () {
      var nameEl = document.getElementById("user-name");
      var passwordEl = document.getElementById("user-password");
      var name = nameEl ? nameEl.value.trim() : "";
      var password = passwordEl ? passwordEl.value : "";
      var role = userRoleSelect ? userRoleSelect.value : "guest";
      if (!name || !password) {
        showUserError("Name and password are required.");
        return;
      }
      showUserError("");
      fetch("/api/users", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name, password: password, role: role }),
      })
        .then(function (res) {
          return res.json().then(function (body) {
            return { ok: res.ok, body: body };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            showUserError((result.body && result.body.error) || "Create failed.");
            return;
          }
          if (userEditor) {
            userEditor.hidden = true;
          }
          loadUsers();
        })
        .catch(function () {
          showUserError("Create failed.");
        });
    });
  }

  loadSession();

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
