// Progressive enhancement: XHR upload with a progress bar. Falls back to a
// plain form POST if anything is unsupported.
(function () {
  var form = document.getElementById("contribute-form");
  if (!form || !window.FormData || !window.XMLHttpRequest) return;

  var bar = form.querySelector(".progress");
  var fill = form.querySelector(".progress-bar");
  var status = form.querySelector(".form-status");
  var button = form.querySelector('button[type="submit"]');

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var data = new FormData(form);
    data.set("ajax", "1");
    var xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    button.disabled = true;
    status.className = "form-status";
    status.textContent = "Uploading…";
    if (bar) bar.hidden = false;

    xhr.upload.addEventListener("progress", function (ev) {
      if (ev.lengthComputable && fill) fill.style.width = Math.round((ev.loaded / ev.total) * 100) + "%";
    });
    xhr.addEventListener("load", function () {
      button.disabled = false;
      if (bar) bar.hidden = true;
      var res = {};
      try { res = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status === 200 && res.ok) {
        status.className = "form-status ok";
        status.textContent = "Thank you! Your stack was uploaded 🌌";
        form.reset();
      } else {
        status.className = "form-status error";
        status.textContent = (res.errors && res.errors.join(" ")) || "Upload failed — please try again.";
      }
    });
    xhr.addEventListener("error", function () {
      button.disabled = false;
      if (bar) bar.hidden = true;
      status.className = "form-status error";
      status.textContent = "Upload failed — please check your connection and try again.";
    });
    xhr.send(data);
  });
})();
