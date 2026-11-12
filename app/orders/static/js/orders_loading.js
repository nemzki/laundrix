/* Establish skeleton styling before first paint; native HTML remains the fallback. */
(function () {
  if (!window.fetch || !window.AbortController) return;
  document.documentElement.classList.add("orders-enhanced");
  window.setTimeout(function () {
    if (!window.laundrixOrdersReady) document.documentElement.classList.remove("orders-enhanced");
  }, 15000);
})();
