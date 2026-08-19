(function () {
  var titleEl = document.getElementById("app-title");
  fetch("/api/schema")
    .then(function (res) {
      if (!res.ok) {
        return null;
      }
      return res.json();
    })
    .then(function (schema) {
      if (!schema || !schema.app || !schema.app.title) {
        return;
      }
      if (titleEl) {
        titleEl.textContent = schema.app.title;
      }
      document.title = schema.app.title;
    })
    .catch(function () {});
})();
