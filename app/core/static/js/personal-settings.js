/* Preview only; profile writes use the existing authenticated form/CSRF session. */
(function () {
  'use strict';
  var form = document.querySelector('[data-profile-form]');
  if (!form) return;
  var file = form.querySelector('input[type=file]');
  var original = form.querySelector('[data-avatar-original]');
  var preview = form.querySelector('[data-avatar-preview]');
  var remove = form.querySelector('[data-remove-picture]');
  var error = form.querySelector('[data-picture-error]');
  var notice = form.querySelector('[data-profile-unsaved]');
  var name = form.querySelector('[name=full_name]');
  var reader;
  function clearPreview() {
    if (reader && reader.readyState === 1) reader.abort();
    preview.onload = null; preview.onerror = null;
    preview.hidden = true;
    preview.removeAttribute('src');
    original.hidden = false;
  }
  function dirty() { notice.textContent = 'Unsaved Changes'; }
  function reject(message) {
    file.value = '';
    clearPreview();
    error.textContent = message;
    file.setCustomValidity('');
  }
  form.querySelector('[data-select-picture]').addEventListener('click', function () { file.click(); });
  name.addEventListener('input', dirty);
  file.addEventListener('change', function () {
    clearPreview();
    error.textContent = '';
    var chosen = file.files[0];
    if (!chosen) return;
    if (!/\.(png|jpe?g|webp)$/i.test(chosen.name) || (chosen.type && ['image/png', 'image/jpeg', 'image/webp'].indexOf(chosen.type) === -1)) {
      reject('Choose a PNG, JPEG, or WebP image.'); return;
    }
    if (chosen.size > 1024 * 1024) { reject('The image must be 1 MB or smaller.'); return; }
    if (remove) remove.checked = false;
    reader = new FileReader();
    reader.addEventListener('load', function () {
      preview.onload = function () { original.hidden = true; preview.hidden = false; dirty(); };
      preview.onerror = function () { reject('That file could not be previewed. Choose a valid image.'); };
      preview.src = reader.result;
    });
    reader.addEventListener('error', function () { reject('The file could not be read.'); });
    reader.readAsDataURL(chosen);
  });
  if (remove) remove.addEventListener('change', function () {
    file.value = ''; clearPreview(); dirty();
    notice.textContent = remove.checked ? 'The default avatar will be used after saving.' : 'Unsaved Changes';
  });
  form.addEventListener('submit', function (event) {
    name.value = name.value.trim();
    if (!name.value || name.value.length < 2 || name.value.length > 150) {
      event.preventDefault();
      name.setAttribute('aria-invalid', 'true');
      document.getElementById('profile-name-error').textContent = 'Enter your full name (2 to 150 characters).';
      name.focus();
    }
  });
})();
