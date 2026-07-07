// Simple, dependency-free lightbox: click a screenshot to view it full-size.
// Close by clicking the backdrop, the ✕, or pressing Escape.
(function () {
  var imgs = document.querySelectorAll(".shot img");
  if (!imgs.length) return;
  var box = null;

  function close() {
    if (!box) return;
    document.removeEventListener("keydown", onKey);
    box.remove();
    box = null;
    document.body.style.overflow = "";
  }

  function onKey(e) { if (e.key === "Escape") close(); }

  function open(src, alt) {
    close();
    box = document.createElement("div");
    box.className = "lightbox";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-label", alt || "Screenshot");

    var full = document.createElement("img");
    full.src = src;
    full.alt = alt || "";

    var btn = document.createElement("button");
    btn.className = "lb-close";
    btn.setAttribute("aria-label", "Close");
    btn.textContent = "×";

    box.appendChild(full);
    box.appendChild(btn);
    box.addEventListener("click", function (e) {
      if (e.target !== full) close();   // backdrop or ✕ closes; image itself doesn't
    });

    document.body.appendChild(box);
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKey);
    btn.focus();
  }

  imgs.forEach(function (img) {
    img.addEventListener("click", function () { open(img.src, img.alt); });
  });
})();
