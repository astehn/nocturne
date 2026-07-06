// Progressive enhancement only — the page works without JS.

// Current year in the footer.
var year = document.getElementById("year");
if (year) year.textContent = new Date().getFullYear();

// Smooth-scroll for in-page anchor links (respects reduced-motion via CSS).
document.querySelectorAll('a[href^="#"]').forEach(function (link) {
  link.addEventListener("click", function (e) {
    var id = link.getAttribute("href");
    if (id.length < 2) return;
    var target = document.querySelector(id);
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});
