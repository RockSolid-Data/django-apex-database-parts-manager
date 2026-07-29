(function () {
  'use strict';

  var dragApi = null;

  function getCheckboxes() {
    return dragApi ? dragApi.getCheckboxes() : Array.from(document.querySelectorAll('.bulk-row-check'));
  }

  function getSelectedIds() {
    return getCheckboxes()
      .filter(function (cb) { return cb.checked; })
      .map(function (cb) { return cb.value; });
  }

  function syncUI() {
    var ids = getSelectedIds();
    var count = ids.length;
    var toolbar = document.getElementById('bulk-toolbar');
    var badge = document.getElementById('bulk-count');
    var plural = document.getElementById('bulk-plural');
    var dropdown = document.getElementById('bulkActionsDropdown');
    var selectAll = document.getElementById('bulk-select-all');
    var deleteCount = document.querySelector('.bulk-delete-count');
    var printBtn = document.getElementById('parts-print-btn');
    var printLabel = document.getElementById('parts-print-label');

    if (toolbar) toolbar.style.display = count > 0 ? '' : 'none';
    if (badge) badge.textContent = String(count);
    if (plural) plural.textContent = count === 1 ? '' : 's';
    if (dropdown) dropdown.disabled = count === 0;
    if (deleteCount) deleteCount.textContent = String(count);

    if (selectAll) {
      var all = getCheckboxes();
      selectAll.checked = all.length > 0 && all.every(function (cb) { return cb.checked; });
      selectAll.indeterminate = count > 0 && count < all.length;
    }

    if (printLabel) {
      printLabel.textContent = count > 0 ? ('Print Selected (' + count + ')') : 'Print';
    }
    if (printBtn) {
      printBtn.classList.toggle('btn-outline-primary', count > 0);
      printBtn.classList.toggle('btn-outline-secondary', count === 0);
    }
  }

  function handleDeselectAll() {
    if (dragApi) {
      dragApi.clear();
    } else {
      getCheckboxes().forEach(function (cb) { cb.checked = false; });
      syncUI();
    }
  }

  function handleDropdownAction(e) {
    var item = e.target.closest('[data-bulk-modal]');
    if (!item) return;
    e.preventDefault();

    var modalId = item.getAttribute('data-bulk-modal');
    var modalEl = document.getElementById(modalId);
    if (!modalEl) return;

    var ids = getSelectedIds().join(',');
    modalEl.querySelectorAll('.bulk-ids-input').forEach(function (input) {
      input.value = ids;
    });

    var qs = '';
    var searchForm = document.querySelector('.js-live-search-form');
    if (searchForm) {
      qs = new URLSearchParams(new FormData(searchForm)).toString();
    }
    modalEl.querySelectorAll('.bulk-action-form').forEach(function (form) {
      var base = form.getAttribute('action').split('?')[0];
      form.setAttribute('action', qs ? base + '?' + qs : base);
    });

    var bsModal = bootstrap.Modal.getOrCreateInstance(modalEl);
    bsModal.show();
  }

  function bindPrintSelected() {
    document.addEventListener('click', function (e) {
      var btn = e.target.closest('#parts-print-btn');
      if (!btn) return;

      var ids = getSelectedIds();
      if (!ids.length) return; // fall through to default js-iframe-print (current list page)

      e.preventDefault();
      e.stopImmediatePropagation();

      var url = new URL(window.location.href);
      url.searchParams.set('print', '1');
      url.searchParams.set('ids', ids.join(','));
      if (typeof window.printViaIframe === 'function') {
        window.printViaIframe(url.toString());
      } else {
        window.open(url.toString(), '_blank');
      }
    }, true);
  }

  function bindEvents() {
    document.addEventListener('click', function (e) {
      if (e.target.closest('#bulk-deselect-all')) {
        handleDeselectAll();
        return;
      }
      var item = e.target.closest('[data-bulk-modal]');
      if (item) {
        handleDropdownAction(e);
      }
    });

    bindPrintSelected();
  }

  function init() {
    if (!document.querySelector('.bulk-row-check')) return;

    if (typeof ApexDragSelect === 'undefined') {
      console.warn('ApexDragSelect missing; bulk checkbox UI will be limited');
      bindEvents();
      syncUI();
      return;
    }

    dragApi = ApexDragSelect.init({
      rowCheckboxSelector: '.bulk-row-check',
      selectAllSelector: '#bulk-select-all',
      onChange: syncUI
    });

    bindEvents();
    syncUI();

    var results = document.getElementById('live-search-results');
    if (results) {
      var observer = new MutationObserver(function () {
        syncUI();
      });
      observer.observe(results, { childList: true, subtree: true });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
