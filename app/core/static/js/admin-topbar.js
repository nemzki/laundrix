// NAVBAR: Keep the admin menu state in sync
/* Connect the admin header controls to their menus and actions. */
/* Admin shell sidebar and shared mobile drawer. */
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
    else if (drawer) {
      window.laundrixDialog(drawer).toggle();
    }
    sync();
  });
  desktop.addEventListener('change', function () {
    if (desktop.matches && drawer) window.laundrixDialog(drawer).hide();
    sync();
  });
  if (drawer) {
    drawer.addEventListener('dialog:shown', sync);
    drawer.addEventListener('dialog:hidden', sync);
  }
  sync();
})();
