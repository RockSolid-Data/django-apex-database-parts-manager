/**
 * Checkbox multi-select + Print Selected for list pages.
 *
 * Expects:
 *   - row checkboxes: .bulk-row-check
 *   - select-all:     #bulk-select-all (optional)
 *   - print button:   #list-print-btn (with .js-iframe-print)
 *   - print label:    #list-print-label
 *
 * Uses ApexDragSelect; selection changes update the Print label via onChange
 * (driven by checkbox `change` events).
 *
 * Print behavior (matches Parts List):
 *   - rows selected → ?print=1&ids=...
 *   - none selected → fall through to js-iframe-print (current page / filters)
 */
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
    var selectAll = document.getElementById('bulk-select-all');
    var printBtn = document.getElementById('list-print-btn');
    var printLabel = document.getElementById('list-print-label');

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

  function bindPrintSelected() {
    document.addEventListener('click', function (e) {
      var btn = e.target.closest('#list-print-btn');
      if (!btn) return;

      var ids = getSelectedIds();
      if (!ids.length) return; // fall through to default js-iframe-print

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

  function init() {
    if (!document.getElementById('list-print-btn')) return;
    if (!document.querySelector('.bulk-row-check')) return;

    if (typeof ApexDragSelect !== 'undefined') {
      dragApi = ApexDragSelect.init({
        rowCheckboxSelector: '.bulk-row-check',
        selectAllSelector: '#bulk-select-all',
        onChange: syncUI
      });
    } else {
      console.warn('ApexDragSelect missing; list select UI will be limited');
      document.addEventListener('change', function (e) {
        if (e.target.matches && e.target.matches('.bulk-row-check, #bulk-select-all')) {
          syncUI();
        }
      });
    }

    bindPrintSelected();
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
