(() => {
  const root = document.getElementById('laundrix-staff');
  if (!root) return;

  const showError = () => {
    root.replaceChildren();
    root.dataset.ready = 'error';
    const panel = document.createElement('div');
    panel.className = 'staff-startup-error';
    panel.setAttribute('role', 'alert');
    const title = document.createElement('strong');
    title.textContent = 'Staff Management could not load.';
    const description = document.createElement('p');
    description.textContent = 'Reload the page to try again.';
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.textContent = 'Reload Staff Management';
    retry.addEventListener('click', () => location.reload());
    panel.append(title, description, retry);
    root.append(panel);
  };

  const loader = document.currentScript;
  if (!(loader instanceof HTMLScriptElement) || !loader.src) {
    showError();
    return;
  }
  import(new URL('../react-staff/staff.js', loader.src).href).catch(showError);
})();
