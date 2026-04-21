/**
 * Lightweight i18n module for Clutch dashboard.
 *
 * Usage:
 *   await i18n.init();          // Load saved language (or default)
 *   i18n.t('key');              // Translate a key
 *   i18n.t('key', {n: 5});     // With interpolation: "Found {n} items" → "Found 5 items"
 *   i18n.applyPage();          // Apply translations to all [data-i18n] elements
 *   i18n.setLanguage('es');    // Switch language and re-apply
 */
'use strict';
// eslint-disable-next-line no-unused-vars
const i18n = (() => {
  const STORAGE_KEY = 'clutch_lang';
  const DEFAULT_LANG = 'en';
  const SUPPORTED = ['en', 'es'];

  let _lang = DEFAULT_LANG;
  let _strings = {};

  /** Fetch the JSON translation file for a language code. */
  async function _load(lang) {
    const resp = await fetch(`/assets/lang/${lang}.json`);
    if (!resp.ok) throw new Error(`Failed to load language: ${lang}`);
    return resp.json();
  }

  /** Detect the preferred language from storage, cookie, or browser. */
  function _detect() {
    // 1. localStorage
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && SUPPORTED.includes(stored)) return stored;
    // 2. Server-set cookie
    const match = document.cookie.match(/(?:^|;\s*)clutch_lang=([a-z]{2})/);
    if (match && SUPPORTED.includes(match[1])) return match[1];
    // 3. Browser language
    const nav = (navigator.language || '').slice(0, 2).toLowerCase();
    if (SUPPORTED.includes(nav)) return nav;
    return DEFAULT_LANG;
  }

  /**
   * Translate a key, with optional interpolation.
   * Placeholders use {name} syntax.
   */
  function t(key, params) {
    let str = _strings[key];
    if (str === undefined) {
      // Fallback: return the key itself so missing translations are visible
      return key;
    }
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
      }
    }
    return str;
  }

  /**
   * Apply translations to all elements with [data-i18n] attributes.
   * Supports:
   *   data-i18n="key"                    → textContent
   *   data-i18n-placeholder="key"        → placeholder
   *   data-i18n-title="key"              → title attribute
   *   data-i18n-html="key"               → innerHTML (use sparingly)
   */
  function applyPage() {
    // Collect <select> values before translating their <option> children
    const selectValues = new Map();
    document.querySelectorAll('select').forEach(sel => {
      selectValues.set(sel, sel.value);
    });

    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      if (key) el.textContent = t(key);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      const key = el.getAttribute('data-i18n-placeholder');
      if (key) el.placeholder = t(key);
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
      const key = el.getAttribute('data-i18n-title');
      if (key) el.title = t(key);
    });
    document.querySelectorAll('[data-i18n-html]').forEach(el => {
      const key = el.getAttribute('data-i18n-html');
      if (key) el.innerHTML = t(key);
    });

    // Restore <select> values after translation
    selectValues.forEach((val, sel) => {
      if (val) sel.value = val;
    });
  }

  /** Initialize the i18n system. Call once on page load. */
  async function init(forceLang) {
    _lang = forceLang || _detect();
    try {
      _strings = await _load(_lang);
    } catch {
      // If the preferred language fails, fall back to English
      if (_lang !== DEFAULT_LANG) {
        _lang = DEFAULT_LANG;
        _strings = await _load(DEFAULT_LANG);
      }
    }
    applyPage();
    return _lang;
  }

  /** Switch language at runtime. */
  async function setLanguage(lang) {
    if (!SUPPORTED.includes(lang)) return;
    _lang = lang;
    localStorage.setItem(STORAGE_KEY, lang);
    _strings = await _load(lang);
    applyPage();
  }

  /** Get the current language code. */
  function getLang() {
    return _lang;
  }

  /** Get the list of supported languages. */
  function getSupported() {
    return [...SUPPORTED];
  }

  return { init, t, applyPage, setLanguage, getLang, getSupported };
})();
