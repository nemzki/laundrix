/* Shared by Jinja, the server dashboard and React. Blocking head load prevents a wrong-theme paint. */
(function () {
  'use strict';
  var key = 'laundrix-theme';
  var root = document.documentElement;
  var media = window.matchMedia('(prefers-color-scheme: dark)');
  function valid(value) { return ['light', 'dark', 'system'].indexOf(value) !== -1; }
  function read() { try { return localStorage.getItem(key); } catch (_) { return null; } }
  var saved = read();
  var preference = valid(saved) ? saved : 'system';
  function sync() {
    document.querySelectorAll('[data-theme-option]').forEach(function (option) {
      option.setAttribute('aria-checked', String(option.dataset.themeOption === preference));
      if (option.closest('[data-theme-preferences]')) option.tabIndex = option.dataset.themeOption === preference ? 0 : -1;
    });
  }
  function apply() {
    var resolved = preference === 'system' ? (media.matches ? 'dark' : 'light') : preference;
    root.dataset.lxTheme = resolved;
    root.dataset.themePreference = preference;
    root.dataset.bsTheme = resolved;
    // The landing export uses class-based dark variants; React uses the data attribute.
    root.classList.toggle('dark', resolved === 'dark');
    sync();
    window.dispatchEvent(new CustomEvent('laundrix:themechange', { detail: { preference: preference, resolved: resolved } }));
  }
  function choose(value) {
    if (!valid(value)) return;
    preference = value;
    try { localStorage.setItem(key, value); } catch (_) { /* Session preference still works. */ }
    apply();
  }
  window.LaundrixTheme = {
    set: choose,
    get: function () { return preference; },
    resolved: function () { return root.dataset.lxTheme; }
  };
  apply();
  // Back/forward cache restores an existing document; re-read changes made on other pages.
  window.addEventListener('pageshow', function (event) {
    if (event.persisted) { var stored = read(); preference = valid(stored) ? stored : 'system'; apply(); }
  });
  media.addEventListener('change', function () { if (preference === 'system') apply(); });
  window.addEventListener('storage', function (event) {
    if (event.key === key || event.key === null) { preference = valid(event.newValue) ? event.newValue : 'system'; apply(); }
  });
  function close(picker, focus) {
    picker.querySelector('[data-theme-menu]').hidden = true;
    var trigger = picker.querySelector('[data-theme-trigger]');
    trigger.setAttribute('aria-expanded', 'false');
    if (focus) trigger.focus();
  }
  function open(picker, last) {
    document.querySelectorAll('[data-theme-picker]').forEach(function (other) { if (other !== picker) close(other, false); });
    sync();
    picker.querySelector('[data-theme-menu]').hidden = false;
    picker.querySelector('[data-theme-trigger]').setAttribute('aria-expanded', 'true');
    var items = picker.querySelectorAll('[data-theme-option]');
    (last ? items[items.length - 1] : picker.querySelector('[aria-checked="true"]')).focus();
  }
  document.addEventListener('click', function (event) {
    var choice = event.target.closest('[data-theme-preferences] [data-theme-option]');
    if (choice) { choose(choice.dataset.themeOption); return; }
    var picker = event.target.closest('[data-theme-picker]');
    if (!picker) { document.querySelectorAll('[data-theme-picker]').forEach(function (item) { close(item, false); }); return; }
    var trigger = event.target.closest('[data-theme-trigger]');
    if (trigger) { if (trigger.getAttribute('aria-expanded') === 'true') close(picker, false); else open(picker, false); }
    var option = event.target.closest('[data-theme-option]');
    if (option) { choose(option.dataset.themeOption); close(picker, true); }
  });
  document.addEventListener('keydown', function (event) {
    var preferences = event.target.closest('[data-theme-preferences]');
    if (preferences && ['ArrowRight','ArrowLeft','ArrowDown','ArrowUp','Home','End'].indexOf(event.key) !== -1) {
      event.preventDefault();
      var options = Array.from(preferences.querySelectorAll('[data-theme-option]'));
      var current = options.indexOf(document.activeElement);
      var selected = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : (current + (event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 1) + options.length) % options.length;
      choose(options[selected].dataset.themeOption);
      options[selected].focus();
      return;
    }
    var picker = event.target.closest('[data-theme-picker]');
    if (!picker) return;
    var menu = picker.querySelector('[data-theme-menu]');
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(picker, true); return; }
    if (event.key === 'Tab') { close(picker, true); return; }
    var items = Array.from(picker.querySelectorAll('[data-theme-option]'));
    var index = items.indexOf(document.activeElement);
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].indexOf(event.key) !== -1) {
      event.preventDefault();
      if (menu.hidden) { open(picker, event.key === 'ArrowUp'); return; }
      var next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length;
      items[next].focus();
    }
  });
  document.addEventListener('focusin', function (event) {
    document.querySelectorAll('[data-theme-picker]').forEach(function (picker) { if (!picker.contains(event.target)) close(picker, false); });
  });
  document.addEventListener('DOMContentLoaded', function () {
    sync();
    // React replaces the server sidebar and creates mobile drawers after the initial paint.
    new MutationObserver(function (changes) {
      if (changes.some(function (change) { return Array.from(change.addedNodes).some(function (node) { return node.nodeType === 1 && (node.matches('[data-theme-picker]') || node.querySelector('[data-theme-picker]')); }); })) sync();
    }).observe(document.body, { childList: true, subtree: true });
  });
})();
