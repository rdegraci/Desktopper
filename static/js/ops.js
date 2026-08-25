(function () {
  var titleEl = document.getElementById("app-title");
  var versionEl = document.getElementById("schema-version");
  var formEl = document.getElementById("intent-form");
  var textEl = document.getElementById("intent-text");
  var submitEl = document.getElementById("intent-submit");
  var busyEl = document.getElementById("intent-busy");
  var busyLabelEl = document.getElementById("intent-busy-label");
  var summaryEl = document.getElementById("intent-summary");
  var hintEl = document.getElementById("intent-hint");
  var errorEl = document.getElementById("intent-error");
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

  function setText(node, value) {
    if (node) {
      node.textContent = value || "";
    }
  }

  function showError(msg) {
    if (!errorEl) {
      return;
    }
    if (!msg) {
      errorEl.hidden = true;
      errorEl.textContent = "";
      return;
    }
    errorEl.hidden = false;
    errorEl.textContent = msg;
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
      var name =
        schema.app && schema.app.title ? schema.app.title : "Desktopper";
      if (titleEl) {
        titleEl.textContent = "Ops — " + name;
      }
      document.title = "Ops — " + name;
      var ver = schema.version !== undefined ? schema.version : 0;
      setVersion(ver);
    })
    .catch(function () {});

  loadHooks();

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
      showError("");
      setText(summaryEl, "");
      if (hintEl) {
        hintEl.hidden = true;
      }
      if (hookPreviewEl) {
        hookPreviewEl.hidden = true;
      }
      var text = textEl ? textEl.value : "";
      setBusy(true);
      fetch("/api/intent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text }),
      })
        .then(function (res) {
          return res.json().then(function (body) {
            return { ok: res.ok, status: res.status, body: body };
          });
        })
        .then(function (result) {
          loadLogs();
          if (!result.ok) {
            var err = result.body && result.body.error
              ? result.body.error
              : "Intent failed.";
            showError(err);
            return;
          }
          var summary =
            result.body && result.body.summary
              ? result.body.summary
              : "Applied spec.";
          setText(summaryEl, summary);
          var changed = (result.body && result.body.hooks_changed) || [];
          if (changed.length) {
            showHookPreview(changed, null);
            if (hintEl) {
              hintEl.hidden = false;
              hintEl.textContent =
                "Hooks updated. Refresh the App tab if schema changed too.";
            }
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
                      "\n--- " +
                      hook.id +
                      " ---\n" +
                      (hook.code || "");
                    hookPreviewText.value += block;
                  });
              }
            });
          } else if (hintEl) {
            hintEl.hidden = false;
            hintEl.textContent = "Refresh the App tab to see the change.";
          }
          if (result.body && result.body.version !== undefined) {
            setVersion(result.body.version);
          }
          loadHooks();
          closeHookEditor();
        })
        .catch(function () {
          loadLogs();
          showError("Intent request failed.");
        })
        .then(function () {
          setBusy(false);
        });
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
})();
