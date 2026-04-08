/**
 * Iframe-based printing: load URL in hidden iframe and print its content.
 * Use data-print-url on a button/link for explicit URL, or class "js-iframe-print"
 * on a button to print current page with ?print=1 added.
 */
(function () {
  'use strict';

  var printFrame = null;

  function getPrintFrame() {
    if (!printFrame) {
      printFrame = document.createElement('iframe');
      printFrame.name = 'me-print-frame';
      printFrame.id = 'me-print-frame';
      printFrame.style.cssText = 'position:absolute;width:0;height:0;border:0;left:-9999px;top:0;';
      document.body.appendChild(printFrame);
    }
    return printFrame;
  }

  var overlay = null;
  function showPrintOverlay() {
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'me-print-overlay';
      overlay.innerHTML = '<div class="spinner-border spinner-border-sm me-2" role="status"></div> Preparing print\u2026';
      overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,0.8);z-index:9999;font-size:1.1rem;color:#333;';
      document.body.appendChild(overlay);
    }
    overlay.style.display = 'flex';
  }
  function hidePrintOverlay() {
    if (overlay) overlay.style.display = 'none';
  }

  function printViaIframe(url) {
    var frame = getPrintFrame();
    showPrintOverlay();
    frame.onload = function () {
      hidePrintOverlay();
      try {
        frame.contentWindow.focus();
        frame.contentWindow.print();
      } catch (e) {
        console.warn('Iframe print failed:', e);
      }
      frame.onload = null;
    };
    frame.src = url;
  }

  function getPrintUrl() {
    var href = window.location.href;
    var sep = href.indexOf('?') >= 0 ? '&' : '?';
    return href + sep + 'print=1';
  }

  function setupPrintButtons() {
    document.addEventListener('click', function (e) {
      var target = e.target.closest && e.target.closest('[data-print-url]');
      if (target) {
        e.preventDefault();
        e.stopPropagation();
        var url = target.getAttribute('data-print-url');
        if (url) printViaIframe(url);
        return;
      }
      target = e.target.closest && e.target.closest('.js-iframe-print');
      if (target && !target.hasAttribute('data-print-url')) {
        e.preventDefault();
        e.stopPropagation();
        printViaIframe(getPrintUrl());
      }
    });
  }

  window.printViaIframe = printViaIframe;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupPrintButtons);
  } else {
    setupPrintButtons();
  }
})();
