/* Payment Settings only. Uses the existing method-creation JSON response; all other forms remain native. */
(function () {
  'use strict';
  var form = document.getElementById('ps-add-method-form');
  var modal = document.getElementById('ps-add-method-modal');
  var trigger = document.querySelector('[data-add-method-trigger]');
  if (!form || !modal || !trigger || typeof bootstrap === 'undefined') return;
  trigger.hidden = false;
  var error = document.getElementById('ps-method-error');
  var name = form.elements.namedItem('label');
  var submit = form.querySelector('[type=submit]');
  var cancel = form.querySelector('[data-bs-dismiss]');
  var busy = false;
  var redirecting = false;
  modal.addEventListener('shown.bs.modal', function () { name.focus(); });
  modal.addEventListener('hide.bs.modal', function (event) { if (busy) event.preventDefault(); });
  name.addEventListener('input', function () {
    name.removeAttribute('aria-invalid');
    error.hidden = true;
  });
  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    busy = true;
    submit.disabled = true;
    cancel.disabled = true;
    submit.textContent = 'Adding...';
    form.setAttribute('aria-busy', 'true');
    error.hidden = true;
    name.removeAttribute('aria-invalid');
    try {
      var data = new FormData(form);
      // ui=1 selects the native redirect/flash workflow. Omitting it requests the existing JSON response.
      data.delete('ui');
      var response = await fetch(form.action, {
        method: 'POST', body: data, credentials: 'same-origin',
        headers: { 'Accept': 'application/json', 'X-CSRFToken': data.get('csrf_token') }
      });
      var payload = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null;
      if (!response.ok || !payload?.ok) {
        var message = payload?.error;
        error.textContent = typeof message === 'string' ? message :
          (response.status === 400 ? 'Your session token may have expired. Refresh the page and try again.' :
            'The method could not be added. Please try again.');
        error.hidden = false;
        if (response.status === 422) name.setAttribute('aria-invalid', 'true');
        name.focus();
        return;
      }
      redirecting = true;
      window.location.assign(form.dataset.returnUrl);
    } catch {
      error.textContent = 'The request could not be completed. Check the method list before trying again.';
      error.hidden = false;
    } finally {
      if (!redirecting) {
        busy = false;
        submit.disabled = false;
        cancel.disabled = false;
        submit.textContent = 'Add Method';
        form.removeAttribute('aria-busy');
      }
    }
  });
  var invalid = document.querySelector('#ps-settings-form [aria-invalid=true]');
  if (invalid) invalid.focus();
})();
