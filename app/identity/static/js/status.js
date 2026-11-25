// VERIFY: Show progress when checking verification status
// Only the presentation changes. Flask still handles the form and redirects.
const openVerification = document.querySelector('[data-idv-open]');
const refreshForm = document.querySelector('[data-idv-refresh]');
const refreshButton = refreshForm?.querySelector('button[type="submit"]');

function showLoading(control, loading) {
  control.querySelector('[data-idv-label]').hidden = loading;
  control.querySelector('[data-idv-icon]').hidden = loading;
  control.querySelector('[data-submit-spinner]').hidden = !loading;
  control.querySelector('[data-idv-loading]').hidden = !loading;
}

openVerification?.addEventListener('click', event => {
  if (openVerification.getAttribute('aria-disabled') === 'true') {
    event.preventDefault();
  } else if (!event.defaultPrevented && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
    openVerification.setAttribute('aria-disabled', 'true');
    showLoading(openVerification, true);
  }
});

refreshForm?.addEventListener('submit', event => {
  if (refreshButton.disabled) {
    event.preventDefault();
    return;
  }
  refreshButton.disabled = true;
  showLoading(refreshButton, true);
});

window.addEventListener('pageshow', () => {
  if (openVerification) {
    openVerification.removeAttribute('aria-disabled');
    showLoading(openVerification, false);
  }
  if (refreshButton) {
    refreshButton.disabled = false;
    showLoading(refreshButton, false);
  }
});

document.querySelectorAll('[data-idv-toast]').forEach(toast => {
  window.setTimeout(() => { toast.hidden = true; }, 3500);
});
