/**
 * PersonaOn Embeddable Chat Widget v2
 * Usage: <script src="https://personaon.com/widget.js" data-key="twin_abc12345..."></script>
 */
(function () {
  'use strict';

  var WIDGET_ORIGIN = 'https://personaon.com';
  var API_ORIGIN = 'https://api.personaon.com';

  // Find the script tag to read data-key
  var scripts = document.querySelectorAll('script[data-key]');
  var scriptTag = scripts[scripts.length - 1];
  if (!scriptTag) return;

  var apiKey = scriptTag.getAttribute('data-key');
  if (!apiKey) return;

  // Extract prefix for config lookup (matches key_prefix format in DB)
  var keyPrefix = apiKey.slice(0, 20) + '...';

  // Prevent double-init
  if (window.__personaon_init) return;
  window.__personaon_init = true;

  // State
  var isOpen = false;
  var bubble, iframe, container, closeBtn;

  function injectStyles() {
    var s = document.createElement('style');
    s.textContent = [
      '.__pon_bubble{position:fixed;bottom:20px;right:20px;width:56px;height:56px;border-radius:50%;cursor:pointer;z-index:2147483646;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 20px rgba(0,0,0,0.15);transition:transform 0.2s,box-shadow 0.2s;border:none;outline:none;}',
      '.__pon_bubble:hover{transform:scale(1.08);box-shadow:0 6px 24px rgba(0,0,0,0.2);}',
      '.__pon_wrap{position:fixed;bottom:88px;right:20px;width:380px;height:560px;z-index:2147483647;border-radius:16px;overflow:hidden;box-shadow:0 8px 40px rgba(0,0,0,0.15);opacity:0;transform:translateY(16px) scale(0.95);transition:opacity 0.25s,transform 0.25s;pointer-events:none;}',
      '.__pon_wrap.__pon_open{opacity:1;transform:translateY(0) scale(1);pointer-events:auto;}',
      '.__pon_if{width:100%;height:100%;border:none;background:#fff;}',
      '.__pon_x{position:absolute;top:8px;right:8px;width:28px;height:28px;border-radius:50%;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:16px;z-index:1;background:rgba(0,0,0,0.08);color:#333;line-height:1;}',
      '.__pon_x:hover{background:rgba(0,0,0,0.15);}',
      '@media(max-width:480px){.__pon_wrap{right:0;bottom:0;width:100%;height:100%;border-radius:0;}.__pon_bubble{bottom:16px;right:16px;}}',
    ].join('\n');
    document.head.appendChild(s);
  }

  function createBubble(color) {
    bubble = document.createElement('button');
    bubble.className = '__pon_bubble';
    bubble.style.backgroundColor = color || '#F97316';
    bubble.setAttribute('aria-label', 'Chat');
    bubble.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    bubble.addEventListener('click', toggle);
    document.body.appendChild(bubble);
  }

  function createContainer() {
    container = document.createElement('div');
    container.className = '__pon_wrap';

    closeBtn = document.createElement('button');
    closeBtn.className = '__pon_x';
    closeBtn.innerHTML = '\u00d7';
    closeBtn.setAttribute('aria-label', 'Close chat');
    closeBtn.addEventListener('click', toggle);

    iframe = document.createElement('iframe');
    iframe.className = '__pon_if';
    iframe.setAttribute('allow', 'microphone');
    iframe.setAttribute('loading', 'lazy');
    iframe.setAttribute('title', 'PersonaOn Chat');

    container.appendChild(closeBtn);
    container.appendChild(iframe);
    document.body.appendChild(container);
  }

  function toggle() {
    isOpen = !isOpen;
    if (isOpen) {
      if (!iframe.src) {
        try {
          var visitorId = getVisitorId();
          var utms = getPageUTMs();
          var iframeUrl = WIDGET_ORIGIN + '/widget/' + encodeURIComponent(keyPrefix) + '?key=' + encodeURIComponent(apiKey);
          if (visitorId) iframeUrl += '&vid=' + encodeURIComponent(visitorId);
          Object.keys(utms).forEach(function(k) {
            iframeUrl += '&' + encodeURIComponent(k) + '=' + encodeURIComponent(utms[k]);
          });
          iframe.src = iframeUrl;
        } catch (e) {
          iframe.src = WIDGET_ORIGIN + '/widget/' + encodeURIComponent(keyPrefix) + '?key=' + encodeURIComponent(apiKey);
        }
      }
      container.classList.add('__pon_open');
      bubble.style.display = 'none';
    } else {
      container.classList.remove('__pon_open');
      bubble.style.display = 'flex';
    }
  }

  // Listen for messages from iframe
  window.addEventListener('message', function (e) {
    if (e.origin !== WIDGET_ORIGIN) return;
    var d = e.data;
    if (!d || typeof d !== 'object') return;
    if (d.type === 'personaon_close' && isOpen) toggle();
  });

  // ── Visitor tracking ─────────────────────────────────────────────────────
  function getVisitorId() {
    try {
      var cookieMatch = document.cookie.match(/_pon_vid=([^;]+)/);
      if (cookieMatch) return cookieMatch[1];
      var stored = localStorage.getItem('_pon_vid');
      if (stored) { _setVisitorCookie(stored); return stored; }
      var newId = 'v_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 9);
      _setVisitorCookie(newId);
      localStorage.setItem('_pon_vid', newId);
      return newId;
    } catch (e) { return ''; }
  }

  function _setVisitorCookie(id) {
    try {
      var expires = new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toUTCString();
      document.cookie = '_pon_vid=' + id + '; expires=' + expires + '; path=/; SameSite=Lax';
    } catch (e) {}
  }

  function getPageUTMs() {
    try {
      var params = new URLSearchParams(window.location.search);
      var utms = {};
      ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content'].forEach(function(k) {
        var v = params.get(k);
        if (v) utms[k] = v;
      });
      return utms;
    } catch (e) { return {}; }
  }

  function init() {
    injectStyles();
    createBubble('#F97316');
    createContainer();

    // Fetch config to get persona branding
    fetch(API_ORIGIN + '/widget/config/' + encodeURIComponent(keyPrefix))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (cfg) {
        if (!cfg) return;
        if (cfg.bubble_color) bubble.style.backgroundColor = cfg.bubble_color;
        if (cfg.position === 'bottom-left') {
          bubble.style.right = 'auto';
          bubble.style.left = '20px';
          container.style.right = 'auto';
          container.style.left = '20px';
        }
      })
      .catch(function () {});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
