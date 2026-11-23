document.querySelectorAll('[data-password-toggle]').forEach(button => {
  const field = document.getElementById(button.getAttribute('aria-controls'));
  const label = button.getAttribute('aria-label').slice('Show '.length);
  button.hidden = false;

  button.addEventListener('click', () => {
    const showing = field.type === 'password';
    const action = showing ? 'Hide' : 'Show';
    field.type = showing ? 'text' : 'password';
    button.textContent = action;
    button.setAttribute('aria-label', action + ' ' + label);
  });
});

// Let the browser submit the original form, and prevent a second submission during navigation.
document.querySelectorAll('[data-enrollment-form]').forEach(form => {
  const button = form.querySelector('button[type="submit"]');
  const label = button.textContent;
  form.addEventListener('submit', () => {
    button.textContent = 'Continuing...';
    button.disabled = true;
  });
  window.addEventListener('pageshow', () => {
    button.textContent = label;
    button.disabled = false;
  });
});
