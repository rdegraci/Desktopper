(function () {
  var titleEl = document.getElementById("app-title");
  var versionEl = document.getElementById("schema-version");
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
      var name = schema.app && schema.app.title ? schema.app.title : "Desktopper";
      if (titleEl) {
        titleEl.textContent = "Ops — " + name;
      }
      if (versionEl && schema.version !== undefined) {
        versionEl.textContent = "Schema version " + String(schema.version);
      }
    })
    .catch(function () {});
})();
