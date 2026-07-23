(function () {
  'use strict';

  var lastCheckedIndex = null;

  function getCheckboxes() {
    return Array.from(document.querySelectorAll('.bulk-row-check'));
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
  }

  function handleCheckboxChange(e) {
    var boxes = getCheckboxes();
    var current = boxes.indexOf(e.target);

    if (e.shiftKey && lastCheckedIndex !== null && lastCheckedIndex !== current) {
      var start = Math.min(lastCheckedIndex, current);
      var end = Math.max(lastCheckedIndex, current);
      var state = e.target.checked;
      for (var i = start; i <= end; i++) {
        boxes[i].checked = state;
      }
    }

    lastCheckedIndex = current;
    syncUI();
  }

  function handleSelectAll(e) {
    var state = e.target.checked;
    getCheckboxes().forEach(function (cb) { cb.checked = state; });
    lastCheckedIndex = null;
    syncUI();
  }

  function handleDeselectAll() {
    getCheckboxes().forEach(function (cb) { cb.checked = false; });
    lastCheckedIndex = null;
    syncUI();
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

  function bindEvents() {
    document.addEventListener('change', function (e) {
      if (e.target.id === 'bulk-select-all') {
        handleSelectAll(e);
        return;
      }
      if (e.target.classList.contains('bulk-row-check')) {
        handleCheckboxChange(e);
      }
    });

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
  }

  function init() {
    bindEvents();
    syncUI();

    var observer = new MutationObserver(function () {
      syncUI();
    });
    var results = document.getElementById('live-search-results');
    if (results) {
      observer.observe(results, { childList: true, subtree: true });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
