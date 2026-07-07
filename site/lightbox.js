// Simple, dependency-free lightbox: click a screenshot to view it full-size.
// Fully self-contained — all styles are applied inline here, so it works even if
// styles.css is stale or missing. Close via the backdrop, the ✕, or Escape.
(function () {
  var imgs = document.querySelectorAll(".shot img");
  if (!imgs.length) return;
  var box = null;

  function css(el, styles) { for (var k in styles) el.style[k] = styles[k]; }

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
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-label", alt || "Screenshot");
    css(box, {
      position: "fixed", top: "0", left: "0", right: "0", bottom: "0",
      zIndex: "2000", display: "flex", alignItems: "center", justifyContent: "center",
      padding: "32px", boxSizing: "border-box",
      background: "rgba(3,6,15,0.9)",
      backdropFilter: "blur(4px)", webkitBackdropFilter: "blur(4px)",
      cursor: "zoom-out"
    });

    var full = document.createElement("img");
    full.src = src;
    full.alt = alt || "";
    css(full, {
      maxWidth: "96vw", maxHeight: "92vh", borderRadius: "10px",
      boxShadow: "0 24px 70px rgba(0,0,0,0.7)", cursor: "default"
    });

    var btn = document.createElement("button");
    btn.setAttribute("aria-label", "Close");
    btn.textContent = "×";
    css(btn, {
      position: "absolute", top: "16px", right: "20px", width: "42px", height: "42px",
      border: "none", borderRadius: "50%", background: "rgba(255,255,255,0.16)",
      color: "#fff", fontSize: "1.7rem", lineHeight: "1", cursor: "pointer"
    });

    box.appendChild(full);
    box.appendChild(btn);
    box.addEventListener("click", function (e) {
      if (e.target !== full) close();   // backdrop or ✕ closes; the image itself doesn't
    });

    document.body.appendChild(box);
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKey);
    btn.focus();
  }

  imgs.forEach(function (img) {
    img.style.cursor = "zoom-in";
    img.addEventListener("click", function () { open(img.src, img.alt); });
  });
})();
