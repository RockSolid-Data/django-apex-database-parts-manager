/**
 * Live search: results update as you type (debounced).
 * Only the #live-search-results region is replaced — the form is never touched,
 * so the active input keeps focus the entire time.
 *
 * Classes used:
 *   .js-live-search-form   – the <form>
 *   .js-search-with-clear  – wrapper around an input that has a clear (×) button
 */
(function () {
  'use strict';

  /* ---- helpers ---- */
  function debounce(fn, delay) {
    var timer;
    return function () {
      var ctx = this, args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(ctx, args); }, delay);
    };
  }

  function serializeForm(form) {
    return new URLSearchParams(new FormData(form)).toString();
  }

  /* ---- AJAX search (only replaces #live-search-results) ---- */
  function doLiveSearch(form) {
    var resultsEl = document.getElementById('live-search-results');
    var main      = document.getElementById('main-content');
    if (!resultsEl && !main) return;          // nothing to update

    var action = form.getAttribute('action') || window.location.pathname;
    var query  = serializeForm(form);
    var url    = action + '?' + query;

    fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function (resp) { return resp.text(); })
    .then(function (html) {
      var doc = new DOMParser().parseFromString(html, 'text/html');

      /* Prefer replacing only the results region so the form (and focus) stays */
      if (resultsEl) {
        var fresh = doc.getElementById('live-search-results');
        if (fresh) resultsEl.innerHTML = fresh.innerHTML;
      } else if (main) {
        var freshMain = doc.getElementById('main-content');
        if (freshMain) main.innerHTML = freshMain.innerHTML;
        /* Re-bind because the form was replaced */
        bindAll();
      }

      /* Update URL bar (no reload) */
      if (history.replaceState) history.replaceState(null, '', url);
    })
    .catch(function () {
      /* Network error → fall back to normal GET submission */
      form.submit();
    });
  }

  /* ---- bind events on every .js-live-search-form ---- */
  function bindAll() {
    document.querySelectorAll('.js-live-search-form').forEach(function (form) {
      if (form._lsBound) return;              // don't double-bind
      form._lsBound = true;

      var debouncedSearch = debounce(function () { doLiveSearch(form); }, 400);

      /* Text inputs: live search on typing + Enter */
      form.querySelectorAll('input[type="text"], input[type="search"]').forEach(function (input) {
        input.addEventListener('input', debouncedSearch);
        input.addEventListener('keydown', function (e) {
          if (e.key === 'Enter') { e.preventDefault(); doLiveSearch(form); }
        });
      });

      /* Selects, checkboxes, dates → immediate search */
      form.querySelectorAll('select').forEach(function (sel) {
        sel.addEventListener('change', function () { doLiveSearch(form); });
      });
      form.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
        cb.addEventListener('change', function () { doLiveSearch(form); });
      });
      form.querySelectorAll('input[type="date"]').forEach(function (d) {
        d.addEventListener('change', function () { doLiveSearch(form); });
      });

      /* Search button (type=submit) */
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        doLiveSearch(form);
      });
    });

    /* Clear (×) buttons inside .js-search-with-clear wrappers */
    document.querySelectorAll('.js-search-with-clear').forEach(function (wrapper) {
      if (wrapper._lsBound) return;
      wrapper._lsBound = true;

      var input = wrapper.querySelector('input');
      var btn   = wrapper.querySelector('.search-clear-btn');
      if (!input || !btn) return;

      function toggleClear() {
        btn.classList.toggle('invisible', !input.value.trim());
      }
      toggleClear();
      input.addEventListener('input', toggleClear);
      input.addEventListener('focus', toggleClear);

      btn.addEventListener('click', function () {
        input.value = '';
        input.focus();
        toggleClear();
        var form = input.closest('form');
        if (form) doLiveSearch(form);
      });
    });
  }

  /* ---- boot ---- */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindAll);
  } else {
    bindAll();
  }
})();
