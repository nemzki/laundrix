// FORM: Show progress while security forms submit
// Keep native form submission, including the original CSRF field and action.
document.querySelectorAll('[data-security-form]').forEach(form => {
  const consent = form.querySelector('input[name="consent"]');
  const button = form.querySelector('button[type="submit"]');
  const spinner = button.querySelector('[data-submit-spinner]');
  const label = button.querySelector('[data-submit-label]');
  const loading = button.querySelector('[data-loading-label]');
  const update = () => {
    button.disabled = form.dataset.submitting === 'true' ||
      form.dataset.enrollmentStage === 'password' || Boolean(consent && !consent.checked);
  };

  consent?.addEventListener('change', update);
  form.addEventListener('security-form:stage', update);
  form.addEventListener('submit', event => {
    if (button.disabled) {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = 'true';
    label.hidden = true;
    spinner.hidden = loading.hidden = false;
    update();
  });
  window.addEventListener('pageshow', () => {
    delete form.dataset.submitting;
    spinner.hidden = loading.hidden = true;
    label.hidden = false;
    update();
  });
  update();
});
