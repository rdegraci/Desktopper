(function () {
  var titleEl = document.getElementById("app-title");
  var emptyEl = document.getElementById("empty-state");

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
      var title =
        schema.app && schema.app.title ? schema.app.title : "Desktopper";
      if (titleEl) {
        titleEl.textContent = title;
      }
      document.title = title;
      var screens = schema.screens;
      var empty = !screens || !screens.length;
      if (emptyEl) {
        emptyEl.hidden = !empty;
      }
    })
    .catch(function () {});
})();
