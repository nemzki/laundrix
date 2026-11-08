/* Admin shell only. Reuses Bootstrap's existing mobile drawer. */
(function () {
  "use strict";
  var button = document.querySelector('[data-admin-sidebar-toggle]');
  if (!button) return;
  var desktop = window.matchMedia('(min-width: 768px)');
  var drawer = document.getElementById('appNavDrawer');
  function sync() {
    button.setAttribute('aria-controls', desktop.matches ? 'app-sidebar' : 'appNavDrawer');
    button.setAttribute('aria-expanded', String(desktop.matches
      ? !document.body.classList.contains('admin-sidebar-collapsed')
      : !!drawer && drawer.classList.contains('show')));
  }
  button.addEventListener('click', function () {
    if (desktop.matches) document.body.classList.toggle('admin-sidebar-collapsed');
    else if (drawer && typeof bootstrap !== 'undefined' && bootstrap.Offcanvas) {
      bootstrap.Offcanvas.getOrCreateInstance(drawer).toggle();
    }
    sync();
  });
  desktop.addEventListener('change', function () {
    if (desktop.matches && drawer && typeof bootstrap !== 'undefined' && bootstrap.Offcanvas) {
      var instance = bootstrap.Offcanvas.getInstance(drawer);
      if (instance) instance.hide();
    }
    sync();
  });
  if (drawer) {
    drawer.addEventListener('shown.bs.offcanvas', sync);
    drawer.addEventListener('hidden.bs.offcanvas', sync);
  }
  sync();
})();
