/**
 * Live search: results update as you type (debounced).
 * Only the #live-search-results region is replaced — the form is never touched,
 * so the active input keeps focus the entire time.
 *
 * Pagination and per-page changes are handled via AJAX too, so filters
 * are always preserved from the form (the single source of truth).
 *
 * Classes used:
 *   .js-live-search-form              – the <form>
 *   .js-search-with-clear            – wrapper around an input that has a clear (×) button
 *   .js-page-link                    – pagination prev/next links (data-page="N")
 *   .js-per-page-select              – items-per-page <select>
 *   .js-clear-all-filters            – reset / clear-all button
 *   [data-live-search-key]          – optional; when set, last query is kept in sessionStorage
 *                                     until the user clears (×) or a .js-live-search-clear-persisted link
 *
 * Storage: sessionStorage key meLiveSearch:<data-live-search-key>
 */
(function () {
  'use strict';

  const STORAGE_PREFIX = 'meLiveSearch:';
  const PER_PAGE_KEY = 'mePerPage';
  let _perPage = 0;
  let _fetchController = null;

  function debounce(fn, delay) {
    let timer;
    return function () {
      const ctx = this, args = arguments;
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(ctx, args), delay);
    };
  }

  function serializeForm(form) {
    return new URLSearchParams(new FormData(form)).toString();
  }

  function storageId(form) {
    const k = form.getAttribute('data-live-search-key');
    return k ? STORAGE_PREFIX + k : null;
  }

  function persistLiveSearch(form, relativeUrl) {
    const sid = storageId(form);
    if (!sid) return;
    try {
      const u = new URL(relativeUrl, window.location.origin);
      sessionStorage.setItem(sid, u.pathname + u.search);
    } catch (e) { /* ignore */ }
  }

  function clearPersistedSearch(form) {
    const sid = storageId(form);
    if (!sid) return;
    try {
      sessionStorage.removeItem(sid);
    } catch (e) { /* ignore */ }
  }

  function getSavedPerPage() {
    try {
      const v = parseInt(localStorage.getItem(PER_PAGE_KEY), 10);
      if ([25, 50, 100, 250, 500].includes(v)) return v;
    } catch (e) { /* ignore */ }
    return 0;
  }

  function savePerPage(v) {
    try { localStorage.setItem(PER_PAGE_KEY, String(v)); } catch (e) { /* ignore */ }
  }

  function initPerPage() {
    try {
      const u = new URL(window.location);
      const pp = u.searchParams.get('per_page');
      if (pp) { _perPage = parseInt(pp, 10) || 50; savePerPage(_perPage); return; }
    } catch (e) { /* ignore */ }
    const saved = getSavedPerPage();
    if (saved) { _perPage = saved; return; }
    const sel = document.querySelector('.js-per-page-select');
    if (sel) { _perPage = parseInt(sel.value, 10) || 50; return; }
    _perPage = 50;
  }

  /** @returns {boolean} true if restored from session (needs follow-up fetch) */
  function syncRestoreForm(form) {
    const sid = storageId(form);
    if (!sid) return false;

    if (window.location.search && window.location.search.length > 1) {
      try {
        sessionStorage.setItem(sid, window.location.pathname + window.location.search);
      } catch (e) { /* ignore */ }
      return false;
    }

    let stored;
    try {
      stored = sessionStorage.getItem(sid);
    } catch (e) {
      return false;
    }
    if (!stored) return false;

    let u;
    try {
      u = new URL(stored, window.location.origin);
    } catch (e) {
      return false;
    }
    if (u.pathname !== window.location.pathname) return false;

    applySearchParamsToForm(form, u.searchParams);
    if (history.replaceState) {
      history.replaceState(null, '', u.pathname + u.search);
    }
    return true;
  }

  function applySearchParamsToForm(form, params) {
    params.forEach((value, name) => {
      const el = form.elements.namedItem(name);
      if (!el) return;
      if (el instanceof RadioNodeList) {
        for (let i = 0; i < el.length; i++) {
          if (el[i].value === value) {
            el[i].checked = true;
            break;
          }
        }
        return;
      }
      if (el.type === 'checkbox') {
        el.checked = value === 'on' || value === '1' || value === 'true';
        return;
      }
      el.value = value;
    });
  }

  function setLoading(form, loading) {
    const indicator = form.querySelector('.js-search-loading');
    if (indicator) indicator.style.display = loading ? 'inline-block' : 'none';
  }

  /**
   * @param {HTMLFormElement} form
   * @param {Object} [options]
   * @param {number} [options.page]    – page number (default 1)
   * @param {number} [options.perPage] – items per page (default _perPage)
   */
  function doLiveSearch(form, options) {
    options = options || {};
    const resultsEl = document.getElementById('live-search-results');
    const main      = document.getElementById('main-content');
    if (!resultsEl && !main) return;

    const action = form.getAttribute('action') || window.location.pathname;
    const params = new URLSearchParams(new FormData(form));

    const perPage = options.perPage || _perPage || 50;
    _perPage = perPage;
    params.set('per_page', String(perPage));

    const page = options.page || 1;
    if (page > 1) {
      params.set('page', String(page));
    } else {
      params.delete('page');
    }

    const url = action + '?' + params.toString();

    setLoading(form, true);

    if (_fetchController) {
      _fetchController.abort();
    }
    _fetchController = new AbortController();

    fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      signal: _fetchController.signal,
    })
      .then(resp => resp.text())
      .then(html => {
        const doc = new DOMParser().parseFromString(html, 'text/html');

        if (resultsEl) {
          const fresh = doc.getElementById('live-search-results');
          if (fresh) resultsEl.innerHTML = fresh.innerHTML;
        } else if (main) {
          const freshMain = doc.getElementById('main-content');
          if (freshMain) main.innerHTML = freshMain.innerHTML;
          bindFormHandlers();
        }

        if (window.meSyncStickyVars) window.meSyncStickyVars();

        if (history.replaceState) history.replaceState(null, '', url);
        persistLiveSearch(form, url);
      })
      .catch(err => {
        if (err && err.name === 'AbortError') return;
        form.submit();
      })
      .finally(() => {
        setLoading(form, false);
      });
  }

  function bindPersistClearLinks() {
    document.querySelectorAll('a.js-live-search-clear-persisted').forEach(a => {
      if (a._lsClearBound) return;
      a._lsClearBound = true;
      a.addEventListener('click', () => {
        const key = a.getAttribute('data-live-search-key');
        if (key) {
          try {
            sessionStorage.removeItem(STORAGE_PREFIX + key);
          } catch (e) { /* ignore */ }
        }
      });
    });
  }

  function bindFormHandlers() {
    document.querySelectorAll('.js-live-search-form').forEach(form => {
      if (form._lsBound) return;
      form._lsBound = true;

      const debouncedSearch = debounce(() => doLiveSearch(form), 250);

      form.querySelectorAll('input[type="text"], input[type="search"]').forEach(input => {
        input.addEventListener('input', debouncedSearch);
        input.addEventListener('keydown', e => {
          if (e.key === 'Enter') { e.preventDefault(); doLiveSearch(form); }
        });
      });

      form.querySelectorAll('select').forEach(sel => {
        sel.addEventListener('change', () => doLiveSearch(form));
      });
      form.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        cb.addEventListener('change', () => doLiveSearch(form));
      });
      form.querySelectorAll('input[type="date"]').forEach(d => {
        d.addEventListener('change', () => doLiveSearch(form));
      });

      form.addEventListener('submit', e => {
        e.preventDefault();
        doLiveSearch(form);
      });
    });

    document.querySelectorAll('.js-search-with-clear').forEach(wrapper => {
      if (wrapper._lsBound) return;
      wrapper._lsBound = true;

      const input = wrapper.querySelector('input');
      const btn   = wrapper.querySelector('.search-clear-btn');
      if (!input || !btn) return;

      const toggleClear = () => btn.classList.toggle('invisible', !input.value.trim());
      toggleClear();
      input.addEventListener('input', toggleClear);
      input.addEventListener('focus', toggleClear);

      btn.addEventListener('click', () => {
        input.value = '';
        input.focus();
        toggleClear();
        const form = input.closest('form');
        if (form) {
          clearPersistedSearch(form);
          doLiveSearch(form);
        }
      });
    });

    bindPersistClearLinks();
  }

  function bindDelegatedHandlers() {
    document.addEventListener('click', function (e) {
      const link = e.target.closest('.js-page-link');
      if (!link) return;
      e.preventDefault();
      if (link.closest('.disabled') || link.closest('.page-item.disabled')) return;
      const form = document.querySelector('.js-live-search-form');
      if (!form) return;
      const page = parseInt(link.getAttribute('data-page'), 10) || 1;
      doLiveSearch(form, { page: page });
    });

    document.addEventListener('change', function (e) {
      if (!e.target.classList.contains('js-per-page-select')) return;
      const form = document.querySelector('.js-live-search-form');
      if (!form) return;
      const pp = parseInt(e.target.value, 10) || 50;
      savePerPage(pp);
      doLiveSearch(form, { perPage: pp });
    });

    // "Go to page" form handler
    document.addEventListener('click', function (e) {
      if (!e.target.closest('.js-goto-page-btn')) return;
      e.preventDefault();
      var wrapper = e.target.closest('.js-goto-page-form');
      var input = wrapper && wrapper.querySelector('.js-goto-page-input');
      if (!input) return;
      var page = parseInt(input.value, 10);
      if (!page || page < 1) return;
      var max = parseInt(input.getAttribute('max'), 10);
      if (max && page > max) page = max;
      var form = document.querySelector('.js-live-search-form');
      if (!form) return;
      doLiveSearch(form, { page: page });
      input.value = '';
    });

    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      var input = e.target.closest('.js-goto-page-input');
      if (!input) return;
      e.preventDefault();
      var wrapper = input.closest('.js-goto-page-form');
      var btn = wrapper && wrapper.querySelector('.js-goto-page-btn');
      if (btn) btn.click();
    });

    document.addEventListener('click', function (e) {
      const btn = e.target.closest('.js-clear-all-filters');
      if (!btn) return;
      e.preventDefault();
      const form = document.querySelector('.js-live-search-form');
      if (!form) return;

      form.querySelectorAll('input[type="text"], input[type="search"], input[type="date"]').forEach(function (input) {
        input.value = '';
      });
      form.querySelectorAll('select').forEach(function (sel) {
        if (sel.tomselect) {
          sel.tomselect.setValue('', true);
        } else {
          sel.value = '';
        }
      });
      form.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
        cb.checked = false;
      });

      var wrapper = form.querySelector('.js-search-with-clear');
      if (wrapper) {
        var clearBtn = wrapper.querySelector('.search-clear-btn');
        if (clearBtn) clearBtn.classList.add('invisible');
      }

      clearPersistedSearch(form);
      doLiveSearch(form);
    });
  }

  function init() {
    const restoredForms = [];
    document.querySelectorAll('.js-live-search-form[data-live-search-key]').forEach(form => {
      if (syncRestoreForm(form)) restoredForms.push(form);
    });

    initPerPage();

    const sel = document.querySelector('.js-per-page-select');
    const urlHasPerPage = new URL(window.location).searchParams.has('per_page');
    if (sel && _perPage && !urlHasPerPage) {
      const serverValue = parseInt(sel.value, 10) || 50;
      if (_perPage !== serverValue) {
        sel.value = String(_perPage);
        const form = document.querySelector('.js-live-search-form');
        if (form && !restoredForms.includes(form)) {
          restoredForms.push(form);
        }
      }
    }

    bindFormHandlers();
    bindDelegatedHandlers();

    if (restoredForms.length) {
      setTimeout(() => {
        restoredForms.forEach(f => doLiveSearch(f));
      }, 0);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
