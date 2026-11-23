document.querySelectorAll('[data-password-toggle]').forEach(button => {
  const field = document.getElementById(button.getAttribute('aria-controls'));
  const label = button.getAttribute('aria-label').slice('Show '.length);
  button.hidden = false;

  button.addEventListener('click', () => {
    const showing = field.type === 'password';
    field.type = showing ? 'text' : 'password';
    button.querySelector('[data-eye]').hidden = showing;
    button.querySelector('[data-eye-off]').hidden = !showing;
    button.setAttribute('aria-label', (showing ? 'Hide ' : 'Show ') + label);
  });
});

const enrollmentForm = document.querySelector('[data-enrollment-form]');
const passwordStage = enrollmentForm?.querySelector('[data-password-stage]');
if (passwordStage) {
  const consentStage = enrollmentForm.querySelector('[data-consent-stage]');
  const password = passwordStage.querySelector('#password');
  const confirmation = passwordStage.querySelector('#confirm_password');
  const next = passwordStage.querySelector('[data-next-password]');
  const back = consentStage.querySelector('[data-back-password]');
  const strength = passwordStage.querySelector('[data-password-strength]');
  const progress = strength.querySelector('[role="progressbar"]');
  const strengthText = strength.querySelector('[data-strength-text]');
  const lengthCheck = passwordStage.querySelector('[data-length-check]');
  const matchText = passwordStage.querySelector('#password-match');
  const steps = document.querySelectorAll('[data-enrollment-step]');

  function updatePassword() {
    const length = [...password.value].length;
    const validLength = length >= password.minLength && length <= password.maxLength;
    const matches = password.value === confirmation.value;
    const variety = [/\p{Lu}/u, /\p{Ll}/u, /\p{N}/u, /[^\p{L}\p{N}\s]/u]
      .filter(pattern => pattern.test(password.value)).length;
    // Strength is advice. Only the server's length rule and confirmation gate the next step.
    const score = length === 0 ? 0 : !validLength ? 1 : Math.min(4, 2 + Number(variety >= 3) + Number(length >= 16));
    const strengthLabel = ['Too weak', 'Weak', 'Fair', 'Good', 'Strong'][score];
    const matchLabel = confirmation.value ? (matches ? 'Passwords match' : 'Passwords don’t match yet') : '';
    next.disabled = !validLength || !matches;
    lengthCheck.hidden = !validLength;
    progress.setAttribute('aria-valuenow', String(score));
    progress.setAttribute('aria-valuetext', strengthLabel);
    progress.querySelectorAll('span').forEach((bar, index) => bar.classList.toggle('filled', index < score));
    if (strengthText.textContent !== strengthLabel) strengthText.textContent = strengthLabel;
    if (matchText.textContent !== matchLabel) matchText.textContent = matchLabel;
  }

  function showStage(consent, moveFocus = true) {
    enrollmentForm.dataset.enrollmentStage = consent ? 'consent' : 'password';
    passwordStage.hidden = consent;
    consentStage.hidden = !consent;
    steps.forEach((step, index) => {
      const active = index === Number(consent);
      const done = index < Number(consent);
      step.classList.toggle('active', active);
      step.classList.toggle('done', done);
      const marker = step.querySelector('[data-step-marker]');
      if (active) marker.setAttribute('aria-current', 'step');
      else marker.removeAttribute('aria-current');
      step.querySelector('[data-step-state]').textContent = done ? 'completed' : active ? '' : 'upcoming';
    });
    enrollmentForm.dispatchEvent(new Event('security-form:stage'));
    if (moveFocus) (consent ? consentStage : passwordStage).querySelector('h1').focus();
  }

  password.addEventListener('input', updatePassword);
  confirmation.addEventListener('input', updatePassword);
  next.addEventListener('click', () => {
    updatePassword();
    if (!next.disabled) showStage(true);
  });
  back.addEventListener('click', () => showStage(false));
  window.addEventListener('pageshow', updatePassword);
  strength.hidden = next.hidden = back.hidden = false;
  updatePassword();
  showStage(false, false);
}
