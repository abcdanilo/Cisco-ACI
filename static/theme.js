/* Loaded in <head>: apply the saved palette before the page is painted. */
(() => {
  'use strict';
  const root = document.documentElement;
  const key = 'aci-theme';
  let button;
  function savedTheme() {
    try { return localStorage.getItem(key) === 'light' ? 'light' : 'dark'; }
    catch (_) { return 'dark'; }
  }
  function apply(theme, persist = false) {
    root.dataset.theme = theme === 'light' ? 'light' : 'dark';
    if (persist) { try { localStorage.setItem(key, root.dataset.theme); } catch (_) {} }
    if (button) {
      const light = root.dataset.theme === 'light';
      button.querySelector('[data-theme-icon]').textContent = light ? '☾' : '☀';
      button.querySelector('[data-theme-label]').textContent = light ? 'Tema escuro' : 'Tema claro';
      button.setAttribute('aria-label', light ? 'Ativar tema escuro' : 'Ativar tema claro');
      button.title = 'Tema atual: ' + (light ? 'claro' : 'escuro');
    }
  }
  apply(savedTheme());
  function mount() {
    button = document.getElementById('themeToggle');
    if (!button) {
      button = document.createElement('button');
      button.id = 'themeToggle';
      const bar = document.createElement('div');
      bar.className = 'aci-theme-bar';
      bar.append(button);
      (document.querySelector('main, .page') || document.body).prepend(bar);
    }
    button.type = 'button';
    button.classList.add('aci-theme-toggle');
    const icon = document.createElement('span');
    icon.dataset.themeIcon = '';
    icon.setAttribute('aria-hidden', 'true');
    const label = document.createElement('span');
    label.dataset.themeLabel = '';
    button.replaceChildren(icon, label);
    button.addEventListener('click', () => apply(root.dataset.theme === 'dark' ? 'light' : 'dark', true));
    apply(root.dataset.theme);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true});
  else mount();
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) apply(savedTheme());
  });
  window.addEventListener('pageshow', event => { if (event.persisted) apply(savedTheme()); });
})();
