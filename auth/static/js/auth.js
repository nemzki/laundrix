(function () {
  const btn = document.getElementById("googleBtn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    btn.classList.add("loading");
    btn.querySelector("span").textContent = "Redirecting to Google…";
  });
  // Restore the button if the user comes back via the browser's back button.
  window.addEventListener("pageshow", (e) => {
    if (e.persisted) {
      btn.classList.remove("loading");
      btn.querySelector("span").textContent = "Continue with Google";
    }
  });
})();
