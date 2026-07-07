// Progressive enhancement: XHR upload with a live progress tracker (percent,
// MB, and a rough ETA). Falls back to a plain form POST if unsupported.
(function () {
  var form = document.getElementById("contribute-form");
  if (!form || !window.FormData || !window.XMLHttpRequest) return;

  var bar = form.querySelector(".progress");
  var fill = form.querySelector(".progress-bar");
  var status = form.querySelector(".form-status");
  var button = form.querySelector('button[type="submit"]');

  function mb(bytes) { return (bytes / 1048576).toFixed(0); }

  function eta(seconds) {
    if (!isFinite(seconds) || seconds <= 0) return "";
    if (seconds < 10) return " · almost done";
    if (seconds < 90) return " · about " + Math.round(seconds) + " sec left";
    return " · about " + Math.round(seconds / 60) + " min left";
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var data = new FormData(form);
    data.set("ajax", "1");
    var xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    button.disabled = true;
    status.className = "form-status";
    status.textContent = "Preparing…";
    if (fill) fill.style.width = "0%";
    if (bar) bar.hidden = false;
    var started = Date.now();

    xhr.upload.addEventListener("progress", function (ev) {
      if (ev.loaded >= ev.total) {
        // bytes are up — the server is now saving + recording the file
        if (fill) fill.style.width = "100%";
        status.textContent = "Processing on the server…";
        return;
      }
      if (ev.lengthComputable) {
        var pct = Math.round((ev.loaded / ev.total) * 100);
        if (fill) fill.style.width = pct + "%";
        var elapsed = (Date.now() - started) / 1000;
        var speed = elapsed > 0 ? ev.loaded / elapsed : 0;         // bytes/sec
        var remain = speed > 0 ? (ev.total - ev.loaded) / speed : Infinity;
        status.textContent = "Uploading… " + pct + "% · " +
          mb(ev.loaded) + " MB of " + mb(ev.total) + " MB" + eta(remain);
      } else {
        status.textContent = "Uploading… " + mb(ev.loaded) + " MB sent";
      }
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
