/* Approved v0 landing interactions, ported without React/Next or inline styles. */
(function () {
  'use strict';
  document.documentElement.classList.add('lp-enhanced');
  var menu = document.getElementById('mobile-menu');
  var toggle = document.querySelector('[data-mobile-toggle]');
  function setMenu(open, restoreFocus) {
    if (!menu || !toggle) return;
    menu.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    toggle.querySelector('svg').innerHTML = open
      ? '<path d="M18 6 6 18"></path><path d="m6 6 12 12"></path>'
      : '<path d="M4 5h16"></path><path d="M4 12h16"></path><path d="M4 19h16"></path>';
    if (restoreFocus) toggle.focus();
  }
  if (toggle && menu) {
    toggle.addEventListener('click', function () { setMenu(menu.hidden, false); });
    menu.addEventListener('click', function (event) { if (event.target.closest('a')) setMenu(false, false); });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !menu.hidden) { setMenu(false, true); }
    });
    window.matchMedia('(min-width: 768px)').addEventListener('change', function (event) {
      if (event.matches) setMenu(false, false);
    });
  }

  var flow = document.getElementById('how-it-works');
  if (flow) {
    var steps = Array.from(flow.querySelectorAll('[data-workflow-step]'));
    var progress = flow.querySelector('[data-workflow-progress]');
    var panel = flow.querySelector('[data-workflow-panel]');
    var selected = 0;
    function selectStep(index) {
      if (index === selected || index < 0 || index >= steps.length) return;
      var template = flow.querySelector('[data-workflow-template="' + index + '"]');
      if (!template) return;
      selected = index;
      steps.forEach(function (button, i) {
        var active = i === index;
        var circle = button.firstElementChild;
        var title = button.lastElementChild.firstElementChild;
        if (active) button.setAttribute('aria-current', 'step');
        else button.removeAttribute('aria-current');
        ['border-primary', 'bg-primary', 'text-primary-foreground'].forEach(function (name) { circle.classList.toggle(name, i <= index); });
        ['border-border', 'bg-card', 'text-muted-foreground', 'group-hover:border-primary/50'].forEach(function (name) { circle.classList.toggle(name, i > index); });
        ['shadow-lg', 'ring-4', 'shadow-primary/30', 'ring-primary/20'].forEach(function (name) { circle.classList.toggle(name, active); });
        title.classList.toggle('text-primary', active);
        title.classList.toggle('text-foreground', !active);
        button.parentElement.classList.toggle('after:bg-primary', i < index);
        button.parentElement.classList.toggle('after:bg-border', i >= index);
      });
      for (var i = 0; i < steps.length; i++) progress.classList.toggle('lp-progress-' + i, i === index);
      panel.replaceChildren(template.content.cloneNode(true));
    }
    steps.forEach(function (button, index) {
      button.addEventListener('click', function () { selectStep(index); });
      button.addEventListener('mouseenter', function () { selectStep(index); });
      button.addEventListener('focus', function () { selectStep(index); });
      button.addEventListener('keydown', function (event) {
        var next;
        if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % steps.length;
        if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index + steps.length - 1) % steps.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = steps.length - 1;
        if (next !== undefined) { event.preventDefault(); steps[next].focus(); }
      });
    });
  }

  var preview = document.getElementById('preview');
  if (preview) {
    var controls = Array.from(preview.querySelectorAll('[data-preview-tab]'));
    var tabs = controls.filter(function (button) { return button.getAttribute('role') === 'tab'; });
    var previewPanel = preview.querySelector('[data-preview-panel]');
    var current = 0;
    function selectPreview(index) {
      if (index === current) return;
      var template = preview.querySelector('[data-preview-template="' + index + '"]');
      if (!template) return;
      current = index;
      controls.forEach(function (button) {
        var active = Number(button.dataset.previewTab) === index;
        if (button.getAttribute('role') === 'tab') {
          button.setAttribute('aria-selected', String(active));
          button.tabIndex = active ? 0 : -1;
          if (active) button.setAttribute('data-active', '');
          else button.removeAttribute('data-active');
        } else {
          ['bg-primary', 'text-primary-foreground'].forEach(function (name) { button.classList.toggle(name, active); });
          ['text-background/70', 'hover:bg-background/10', 'hover:text-background'].forEach(function (name) { button.classList.toggle(name, !active); });
          if (active) button.setAttribute('aria-current', 'page');
          else button.removeAttribute('aria-current');
        }
      });
      previewPanel.setAttribute('aria-labelledby', 'preview-tab-' + index);
      previewPanel.dataset.index = index;
      previewPanel.replaceChildren(template.content.cloneNode(true));
    }
    controls.forEach(function (button) {
      button.addEventListener('click', function () { selectPreview(Number(button.dataset.previewTab)); });
    });
    tabs.forEach(function (button, index) {
      button.addEventListener('keydown', function (event) {
        var next;
        if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
        if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = tabs.length - 1;
        if (next !== undefined) { event.preventDefault(); tabs[next].focus(); selectPreview(next); }
      });
    });
  }

  var reveals = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { entry.target.dataset.visible = 'true'; observer.unobserve(entry.target); }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
    reveals.forEach(function (element) { observer.observe(element); });
  } else reveals.forEach(function (element) { element.dataset.visible = 'true'; });
})();

/* Decorative demo only: no requests, order identifiers or application state. */
(function () {
  'use strict';
  var statuses = ['received', 'washing', 'ready', 'released'];
  document.querySelectorAll('[data-demo-status]').forEach(function (ticket) {
    ticket.addEventListener('click', function () {
      var next = statuses[(statuses.indexOf(ticket.dataset.demoStatus) + 1) % statuses.length];
      ticket.dataset.demoStatus = next;
      ticket.querySelector('.claim-stamp').textContent = next.toUpperCase();
    });
  });
})();
