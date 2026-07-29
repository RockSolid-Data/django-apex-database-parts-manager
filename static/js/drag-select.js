/**
 * Click-drag multi-select for table checkbox columns.
 *
 * - Single click toggles exactly one checkbox
 * - Drag only starts after a small movement threshold
 * - Shift+click selects a range
 *
 * Selection changes always notify via onChange (and a bubbling `change`
 * event on each checkbox), including native toggles where a cell's
 * onclick stopPropagation would block document click handlers.
 *
 * Usage:
 *   ApexDragSelect.init({
 *     rowCheckboxSelector: '.bulk-row-check',
 *     selectAllSelector: '#bulk-select-all',  // optional
 *     onChange: function () { ... }           // optional
 *   });
 */
(function (global) {
  'use strict';

  var MOVE_THRESHOLD_SQ = 6 * 6;

  function init(options) {
    if (!options || !options.rowCheckboxSelector) {
      throw new Error('ApexDragSelect.init requires rowCheckboxSelector');
    }

    var rowSelector = options.rowCheckboxSelector;
    var selectAllSelector = options.selectAllSelector || null;
    var onChange = typeof options.onChange === 'function' ? options.onChange : function () {};

    var pending = null;
    var paintState = false;
    var suppressClick = false;
    var lastIndex = null;

    function getBoxes() {
      return Array.from(document.querySelectorAll(rowSelector));
    }

    function isSelectAllTarget(target) {
      if (!selectAllSelector || !target || !target.closest) return false;
      return !!target.closest(selectAllSelector);
    }

    function checkboxFromCell(target) {
      if (!target || !target.closest) return null;
      var td = target.closest('td');
      if (!td) return null;
      return td.querySelector(rowSelector);
    }

    function checkboxForPaint(target) {
      var fromCell = checkboxFromCell(target);
      if (fromCell) return fromCell;
      if (!target || !target.closest) return null;
      var tr = target.closest('tr');
      return tr ? tr.querySelector(rowSelector) : null;
    }

    function notify() {
      onChange();
    }

    /** Set checked and fire a bubbling change event when the value changes. */
    function setChecked(cb, state) {
      if (!cb || cb.checked === state) return false;
      cb.checked = state;
      cb.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    }

    function applyPaint(cb) {
      if (!cb || cb.checked === paintState) return;
      setChecked(cb, paintState);
      lastIndex = getBoxes().indexOf(cb);
    }

    function endPointer() {
      if (pending && pending.moved) {
        suppressClick = true;
      }
      pending = null;
      document.body.classList.remove('bulk-drag-selecting');
    }

    /** Consume the leftover click after a drag (safe across same-target listeners). */
    function consumeSuppressedClick(e) {
      if (e._apexDragSuppressed) return true;
      if (!suppressClick) return false;
      e._apexDragSuppressed = true;
      suppressClick = false;
      e.preventDefault();
      e.stopPropagation();
      return true;
    }

    document.addEventListener('mousedown', function (e) {
      if (e.button !== 0) return;
      if (isSelectAllTarget(e.target)) return;
      var cb = checkboxFromCell(e.target);
      if (!cb) return;

      pending = {
        cb: cb,
        startX: e.clientX,
        startY: e.clientY,
        originalChecked: cb.checked,
        moved: false
      };
    });

    document.addEventListener('mousemove', function (e) {
      if (!pending) return;

      if (!pending.moved) {
        var dx = e.clientX - pending.startX;
        var dy = e.clientY - pending.startY;
        if (dx * dx + dy * dy < MOVE_THRESHOLD_SQ) return;
        pending.moved = true;
        paintState = !pending.originalChecked;
        document.body.classList.add('bulk-drag-selecting');
        applyPaint(pending.cb);
      }

      applyPaint(checkboxForPaint(e.target));
    });

    document.addEventListener('mouseup', endPointer);
    window.addEventListener('blur', endPointer);

    // Capture click handlers (run before td onclick stopPropagation).
    document.addEventListener('click', function (e) {
      if (consumeSuppressedClick(e)) return;

      // Shift+click range select. At capture time the box has not toggled yet.
      if (e.target.matches && e.target.matches(rowSelector)) {
        var boxes = getBoxes();
        var current = boxes.indexOf(e.target);
        if (current < 0) return;

        if (e.shiftKey && lastIndex !== null && lastIndex !== current) {
          var start = Math.min(lastIndex, current);
          var end = Math.max(lastIndex, current);
          var state = !e.target.checked;
          for (var i = start; i <= end; i++) {
            if (i === current) continue;
            setChecked(boxes[i], state);
          }
        }

        lastIndex = current;
        return;
      }

      // Cell padding (not the input) toggles that one box; block row navigation.
      if (isSelectAllTarget(e.target)) return;
      var cb = checkboxFromCell(e.target);
      if (!cb) return;
      setChecked(cb, !cb.checked);
      lastIndex = getBoxes().indexOf(cb);
      e.preventDefault();
      e.stopPropagation();
    }, true);

    // Native checkbox toggles (and setChecked dispatches) always refresh UI.
    // Critical: cell onclick stopPropagation blocks document click handlers, but
    // change still bubbles.
    document.addEventListener('change', function (e) {
      if (!e.target.matches || !e.target.matches(rowSelector)) return;
      lastIndex = getBoxes().indexOf(e.target);
      notify();
    });

    if (selectAllSelector) {
      document.addEventListener('change', function (e) {
        if (!e.target.matches || !e.target.matches(selectAllSelector)) return;
        var state = e.target.checked;
        getBoxes().forEach(function (cb) { setChecked(cb, state); });
        lastIndex = null;
        notify();
      });
    }

    notify();

    return {
      getCheckboxes: getBoxes,
      getSelected: function () {
        return getBoxes().filter(function (cb) { return cb.checked; });
      },
      clear: function () {
        getBoxes().forEach(function (cb) { setChecked(cb, false); });
        lastIndex = null;
        notify();
      },
      refresh: notify
    };
  }

  global.ApexDragSelect = { init: init };
})(window);
