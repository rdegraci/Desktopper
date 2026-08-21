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
          if (hintEl) {
            hintEl.hidden = false;
            hintEl.textContent = "Refresh the App tab to see the change.";
          }
          if (result.body && result.body.version !== undefined) {
            setVersion(result.body.version);
          }
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
