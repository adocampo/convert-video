(function () {
    const state = {
        autoRefresh: true,
        timerId: null,
        theme: 'dark',
        allowedRoots: [],
        defaultJobSettings: {},
        release: {
            local_version: '',
            remote_version: '',
            update_available: false,
            changelog: '',
            checked_at: '',
            last_error: '',
            update_in_progress: false,
        },
        expandedJobs: (function () {
            try {
                var stored = window.localStorage.getItem('clutch-expanded-jobs');
                return stored ? JSON.parse(stored) : {};
            } catch (e) { return {}; }
        })(),
        activeQueueJobId: '',
        queueJobIds: [],
        lastJobs: [],
        selectedJobs: new Set(),
        jobSortColumn: 'default',
        jobSortAsc: true,
        browser: {
            open: false,
            target: '',
            selection: 'file',
            scope: 'allowed',
            showHidden: false,
            filterQuery: '',
            currentPath: '',
            entries: [],
            roots: [],
            parent: '',
            activeEntryIndex: -1,
        },
        biddingZones: [],
        scheduleConfig: {},
        scheduleStatus: {},
        scheduleRules: [],
        editingWatcherId: null,
        auth: {
            enabled: false,
            user: null,
            token: '',
        },
        dateFormat: 'YYYY-MM-DD',
        displayTimezone: '',
    };

    const tokenStorageKey = 'clutch-token';
    const themeStorageKey = 'clutch-theme';
    const legacyThemeStorageKey = 'convert-video-theme';
    const expandedJobsStorageKey = 'clutch-expanded-jobs';

    const statusPriority = {
        running: 0,
        paused: 1,
        cancelling: 2,
        queued: 3,
        failed: 4,
        cancelled: 5,
        skipped: 6,
        succeeded: 7,
    };

    const meta = document.getElementById('sidebar-meta');
    const sidebarVersion = document.getElementById('sidebar-version');
    const sidebar = document.getElementById('sidebar');
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const sidebarOverlay = document.getElementById('sidebar-overlay');
    const navActivityBadge = document.getElementById('nav-activity-badge');
    const jobsContainer = document.getElementById('jobs-container');
    const jobsFilterText = document.getElementById('jobs-filter-text');
    const jobsFilterStatus = document.getElementById('jobs-filter-status');
    const jobsCount = document.getElementById('jobs-count');
    const toggleExpandJobsButton = document.getElementById('toggle-expand-jobs');
    const bulkActionsBar = document.getElementById('bulk-actions');
    const bulkActionsCount = document.getElementById('bulk-actions-count');
    const bulkCancelBtn = document.getElementById('bulk-cancel');
    const bulkRetryBtn = document.getElementById('bulk-retry');
    const bulkClearBtn = document.getElementById('bulk-clear');
    const bulkDeselectBtn = document.getElementById('bulk-deselect');
    const form = document.getElementById('job-form');
    const inputFileField = document.getElementById('input-file');
    const inputKindField = document.getElementById('input-kind');
    const inputSelectionHint = document.getElementById('input-selection-hint');
    const inputRecursiveField = document.getElementById('input-recursive');
    const recursiveToggleInline = document.getElementById('recursive-toggle-inline');
    const browserRecursiveToggle = document.getElementById('browser-recursive-toggle');
    const browserRecursiveField = document.getElementById('browser-recursive');
    const filterPatternRow = document.getElementById('filter-pattern-row');
    const inputFilterPattern = document.getElementById('input-filter-pattern');
    const browseInputFileButton = document.getElementById('browse-input-file');
    const browseInputDirectoryButton = document.getElementById('browse-input-directory');
    const clearInputFileButton = document.getElementById('clear-input-file');
    const outputDirField = document.getElementById('output-dir');
    const browseOutputDirButton = document.getElementById('browse-output-dir');
    const clearOutputDirButton = document.getElementById('clear-output-dir');
    const formStatus = document.getElementById('form-status');
    const settingsForm = document.getElementById('settings-form');
    const allowedRootsList = document.getElementById('allowed-roots-list');
    const addAllowedRootButton = document.getElementById('add-allowed-root');
    const settingsStatus = document.getElementById('settings-status');
    const defaultOutputDirField = document.getElementById('default-output-dir');
    const browseDefaultOutputDirButton = document.getElementById('browse-default-output-dir');
    const clearDefaultOutputDirButton = document.getElementById('clear-default-output-dir');
    const watcherForm = document.getElementById('watcher-form');
    const watcherDirectoryField = document.getElementById('watcher-directory');
    const browseWatcherDirectoryButton = document.getElementById('browse-watcher-directory');
    const clearWatcherDirectoryButton = document.getElementById('clear-watcher-directory');
    const watcherOutputDirField = document.getElementById('watcher-output-dir');
    const browseWatcherOutputDirButton = document.getElementById('browse-watcher-output-dir');
    const clearWatcherOutputDirButton = document.getElementById('clear-watcher-output-dir');
    const watcherOverridesDetails = document.getElementById('watcher-overrides');
    const watcherStatus = document.getElementById('watcher-status');
    const watchersContainer = document.getElementById('watchers-container');
    const submitButton = document.getElementById('submit-button');
    const settingsButton = document.getElementById('settings-button');
    const watcherButton = document.getElementById('watcher-button');
    const cancelEditWatcherButton = document.getElementById('cancel-edit-watcher');
    const refreshButton = document.getElementById('refresh-button');
    const clearJobsButton = document.getElementById('clear-jobs');
    const clearJobsDropdown = document.getElementById('clear-jobs-dropdown');
    const toggleAutoRefreshButton = document.getElementById('toggle-autorefresh');
    const themeSelect = document.getElementById('theme-select');
    const releaseButton = document.getElementById('release-check');
    const releaseLabel = document.getElementById('release-label');
    const aboutVersion = document.getElementById('about-version');
    const aboutEnvironment = document.getElementById('about-environment');
    const changelogRow = document.getElementById('changelog-row');
    const changelogText = document.getElementById('changelog-text');
    const navSystemBadge = document.getElementById('nav-system-badge');
    const toastContainer = document.getElementById('toast-container');
    const browserModal = document.getElementById('path-browser');
    const browserEyebrow = document.getElementById('path-browser-eyebrow');
    const browserTitle = document.getElementById('path-browser-title');
    const browserRoots = document.getElementById('browser-roots');
    const browserCurrentPath = document.getElementById('browser-current-path');
    const browserUpButton = document.getElementById('browser-up');
    const browserFilter = document.getElementById('browser-filter');
    const browserShowHidden = document.getElementById('browser-show-hidden');
    const browserStatus = document.getElementById('browser-status');
    const browserList = document.getElementById('browser-list');
    const browserSelectCurrentButton = document.getElementById('browser-select-current');
    const closeBrowserButton = document.getElementById('close-browser');
    const scheduleEnabled = document.getElementById('schedule-enabled');
    const scheduleMode = document.getElementById('schedule-mode');
    const schedulePriority = document.getElementById('schedule-priority');
    const schedulePauseBehavior = document.getElementById('schedule-pause-behavior');
    const scheduleRulesList = document.getElementById('schedule-rules-list');
    const addScheduleRuleButton = document.getElementById('add-schedule-rule');
    const priceProvider = document.getElementById('price-provider');
    const priceBiddingZone = document.getElementById('price-bidding-zone');
    const priceEntsoeKey = document.getElementById('price-entsoe-key');
    const entsoeKeyLabel = document.getElementById('entsoe-key-label');
    const priceStrategy = document.getElementById('price-strategy');
    const priceThreshold = document.getElementById('price-threshold');
    const priceThresholdLabel = document.getElementById('price-threshold-label');
    const priceCheapestHours = document.getElementById('price-cheapest-hours');
    const priceCheapestLabel = document.getElementById('price-cheapest-label');
    const priceChart = document.getElementById('price-chart');
    const priceChartLabel = document.getElementById('price-chart-label');
    const priceChartWrap = document.getElementById('price-chart-wrap');
    const scheduleStatusBar = document.getElementById('schedule-status-bar');
    const scheduleManualSection = document.getElementById('schedule-manual-section');
    const schedulePriceSection = document.getElementById('schedule-price-section');
    const saveScheduleButton = document.getElementById('save-schedule-button');
    const scheduleStatusEl = document.getElementById('schedule-status');
    const confirmModal = document.getElementById('confirm-modal');
    const confirmTitle = document.getElementById('confirm-title');
    const confirmMessage = document.getElementById('confirm-message');
    const confirmOkButton = document.getElementById('confirm-ok');
    const confirmCancelButton = document.getElementById('confirm-cancel');
    const confirmInput = document.getElementById('confirm-input');
    const sysmonContainer = document.getElementById('sysmon-container');
    const startupParams = new URLSearchParams(window.location.search);
    const systemThemeQuery = window.matchMedia
        ? window.matchMedia('(prefers-color-scheme: dark)')
        : null;

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function basename(path) {
        const normalized = String(path || '');
        const parts = normalized.split('/');
        return parts[parts.length - 1] || normalized;
    }

    /**
     * Return a display label for the codec column.
     * When a preset was used, show its name; otherwise fall back to codec / speed.
     */
    function resolvePresetLabel(record) {
        var pid = record.preset_id || '';
        if (!pid) return (record.codec || '') + ' / ' + (record.encode_speed || '');
        // Official preset: "official:Name" → show the name
        if (pid.startsWith('official:')) return pid.substring(9);
        // Custom preset: look up in cached list by id
        var presets = (typeof presetsState !== 'undefined' && presetsState.quickAccess) || [];
        for (var i = 0; i < presets.length; i++) {
            if (presets[i].id === pid) return presets[i].name;
        }
        // Fallback: show codec/speed from the job record if available
        if (record.codec) return (record.codec || '') + ' / ' + (record.encode_speed || '');
        return pid.length > 12 ? pid.substring(0, 8) + '\u2026' : pid;
    }

    function padNumber(value) {
        return String(value).padStart(2, '0');
    }

    function buildSubmittedDisplay(date, showSeconds) {
        var tz = state.displayTimezone || 'UTC';
        var y, m, d, hh, mm, ss;
        var opts = { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false };
        if (showSeconds) opts.second = '2-digit';
        var parts = {};
        try {
            new Intl.DateTimeFormat('en-GB', opts).formatToParts(date).forEach(function (p) { parts[p.type] = p.value; });
        } catch (e) {
            // Invalid timezone — fall back to local
            return buildSubmittedDisplayLocal(date, showSeconds);
        }
        y = parts.year; m = parts.month; d = parts.day;
        hh = parts.hour; mm = parts.minute; ss = parts.second || '00';
        var time = ' ' + hh + ':' + mm;
        if (showSeconds) time += ':' + ss;
        var fmt = state.dateFormat || 'YYYY-MM-DD';
        if (fmt === 'DD/MM/YYYY') return d + '/' + m + '/' + y + time;
        if (fmt === 'MM/DD/YYYY') return m + '/' + d + '/' + y + time;
        return y + '-' + m + '-' + d + time;
    }

    function buildSubmittedDisplayLocal(date, showSeconds) {
        var y = date.getFullYear();
        var m = padNumber(date.getMonth() + 1);
        var d = padNumber(date.getDate());
        var time = ' ' + padNumber(date.getHours()) + ':' + padNumber(date.getMinutes());
        if (showSeconds) time += ':' + padNumber(date.getSeconds());
        var fmt = state.dateFormat || 'YYYY-MM-DD';
        if (fmt === 'DD/MM/YYYY') return d + '/' + m + '/' + y + time;
        if (fmt === 'MM/DD/YYYY') return m + '/' + d + '/' + y + time;
        return y + '-' + m + '-' + d + time;
    }

    function populateTimezoneDatalist() {
        var dl = document.getElementById('tz-list');
        if (!dl || dl.childNodes.length > 0) return;
        var zones = Intl.supportedValuesOf ? Intl.supportedValuesOf('timeZone') : [
            'Africa/Cairo','Africa/Johannesburg','Africa/Lagos','Africa/Nairobi',
            'America/Anchorage','America/Argentina/Buenos_Aires','America/Bogota',
            'America/Chicago','America/Denver','America/Los_Angeles','America/Mexico_City',
            'America/New_York','America/Sao_Paulo','America/Toronto','America/Vancouver',
            'Asia/Bangkok','Asia/Colombo','Asia/Dubai','Asia/Ho_Chi_Minh','Asia/Hong_Kong',
            'Asia/Jakarta','Asia/Karachi','Asia/Kolkata','Asia/Manila','Asia/Seoul',
            'Asia/Shanghai','Asia/Singapore','Asia/Taipei','Asia/Tokyo',
            'Atlantic/Reykjavik','Australia/Melbourne','Australia/Perth','Australia/Sydney',
            'Europe/Amsterdam','Europe/Athens','Europe/Berlin','Europe/Brussels',
            'Europe/Bucharest','Europe/Budapest','Europe/Copenhagen','Europe/Dublin',
            'Europe/Helsinki','Europe/Istanbul','Europe/Lisbon','Europe/London',
            'Europe/Madrid','Europe/Moscow','Europe/Oslo','Europe/Paris',
            'Europe/Prague','Europe/Rome','Europe/Stockholm','Europe/Vienna',
            'Europe/Warsaw','Europe/Zurich','Pacific/Auckland','Pacific/Honolulu','UTC'
        ];
        zones.forEach(function (tz) {
            var opt = document.createElement('option');
            opt.value = tz;
            dl.appendChild(opt);
        });
    }

    function formatBytes(value) {
        const size = Number(value || 0);
        if (!Number.isFinite(size) || size <= 0) {
            return 'Not available';
        }

        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let scaled = size;
        let unitIndex = 0;

        while (scaled >= 1024 && unitIndex < units.length - 1) {
            scaled /= 1024;
            unitIndex += 1;
        }

        const decimals = scaled >= 100 || unitIndex === 0 ? 0 : scaled >= 10 ? 1 : 2;
        return `${scaled.toFixed(decimals)} ${units[unitIndex]}`;
    }

    function formatCompression(value) {
        const percent = Number(value);
        if (!Number.isFinite(percent)) {
            return 'Not available';
        }
        return `${Math.abs(percent).toFixed(1)}%`;
    }

    function extractEtaLabel(message) {
        const match = String(message || '').match(/\bETA\s+([0-9:]+)/i);
        return match ? match[1] : '';
    }

    function formatElapsed(startedAt, finishedAt) {
        if (!startedAt || !finishedAt) return null;
        var t0 = new Date(startedAt).getTime();
        var t1 = new Date(finishedAt).getTime();
        if (!Number.isFinite(t0) || !Number.isFinite(t1) || t1 <= t0) return null;
        var secs = Math.round((t1 - t0) / 1000);
        var h = Math.floor(secs / 3600);
        var m = Math.floor((secs % 3600) / 60);
        var s = secs % 60;
        if (h > 0) return h + 'h ' + m + 'm ' + s + 's';
        if (m > 0) return m + 'm ' + s + 's';
        return s + 's';
    }

    function summarizeMessage(job) {
        if (job.status === 'running') {
            return job.message || 'Conversion in progress.';
        }
        if (job.status === 'paused') {
            return job.message || 'Conversion paused.';
        }
        if (job.status === 'queued') {
            return job.message || 'Waiting in queue.';
        }
        return job.message || job.input_file || '';
    }

    function renderMediaSection(label, media) {
        if (!media) return '';
        var lines = [];
        // General line
        var gen = [];
        if (media.container) gen.push(media.container);
        if (media.duration) gen.push(media.duration);
        if (media.bitrate) gen.push(media.bitrate);
        if (gen.length) lines.push(`<div class="media-row"><span class="media-label">${i18n.t('media.general')}</span> ${escapeHtml(gen.join(' · '))}</div>`);
        // Video tracks
        if (media.video && media.video.length) {
            media.video.forEach(function (v) {
                var parts = [];
                if (v.codec) parts.push(v.codec);
                if (v.resolution) parts.push(v.resolution);
                if (v.fps) parts.push(v.fps + ' fps');
                if (v.bitrate) parts.push(v.bitrate);
                if (v.bit_depth) parts.push(v.bit_depth + '-bit');
                lines.push(`<div class="media-row"><span class="media-label">${i18n.t('media.video')}</span> ${escapeHtml(parts.join(' · '))}</div>`);
            });
        }
        // Audio tracks
        if (media.audio && media.audio.length) {
            media.audio.forEach(function (a) {
                var parts = [];
                if (a.codec) parts.push(a.codec);
                if (a.channels) parts.push(a.channels);
                if (a.bitrate) parts.push(a.bitrate);
                if (a.lang) parts.push(a.lang);
                if (a.title) parts.push(a.title);
                lines.push(`<div class="media-row"><span class="media-label">${i18n.t('media.audio')}</span> ${escapeHtml(parts.join(' · '))}</div>`);
            });
        }
        // Subtitle tracks
        if (media.subtitles && media.subtitles.length) {
            media.subtitles.forEach(function (s) {
                var parts = [];
                if (s.codec) parts.push(s.codec);
                if (s.lang) parts.push(s.lang);
                if (s.title) parts.push(s.title);
                if (s.forced) parts.push(i18n.t('media.forced'));
                lines.push(`<div class="media-row"><span class="media-label">${i18n.t('media.subtitle')}</span> ${escapeHtml(parts.join(' · '))}</div>`);
            });
        }
        if (!lines.length) return '';
        return `<div class="job-detail"><div class="job-detail-label">${escapeHtml(label)}</div><div class="job-detail-value media-info">${lines.join('')}</div></div>`;
    }

    var arrowSvg = '<svg class="custom-select-arrow" viewBox="0 0 12 8" fill="none" xmlns="http://www.w3.org/2000/svg">'
        + '<path d="M1 1l5 5 5-5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

    function buildCustomSelect(selectEl) {
        if (selectEl.dataset.customized) return;
        selectEl.dataset.customized = '1';
        selectEl.classList.add('custom-select-source');

        var wrapper = document.createElement('div');
        wrapper.className = 'custom-select';

        var trigger = document.createElement('button');
        trigger.type = 'button';
        trigger.className = 'custom-select-trigger';

        var optionsPanel = document.createElement('div');
        optionsPanel.className = 'custom-select-options';
        optionsPanel.hidden = true;

        selectEl.parentNode.insertBefore(wrapper, selectEl);
        wrapper.appendChild(trigger);
        wrapper.appendChild(optionsPanel);
        wrapper.appendChild(selectEl);

        function renderOptions() {
            var current = selectEl.dataset.wantedValue || selectEl.value;
            optionsPanel.innerHTML = '';
            Array.prototype.forEach.call(selectEl.options, function (opt) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'custom-select-option' + (opt.value === current ? ' selected' : '');
                btn.textContent = opt.textContent;
                btn.dataset.value = opt.value;
                btn.addEventListener('click', function (e) {
                    e.stopPropagation();
                    selectEl.value = opt.value;
                    selectEl.dataset.wantedValue = opt.value;
                    selectEl.dispatchEvent(new Event('change', { bubbles: true }));
                    optionsPanel.hidden = true;
                    wrapper.classList.remove('open');
                    syncTrigger();
                });
                optionsPanel.appendChild(btn);
            });
        }

        function syncTrigger() {
            // Use wantedValue as source of truth in case native value was transiently reset
            var wantedVal = selectEl.dataset.wantedValue || selectEl.value;
            if (wantedVal && wantedVal !== selectEl.value) selectEl.value = wantedVal;
            var selected = selectEl.options[selectEl.selectedIndex];
            trigger.innerHTML = escapeHtml(selected ? selected.textContent : '') + ' ' + arrowSvg;
        }

        trigger.addEventListener('click', function (e) {
            e.stopPropagation();
            var isOpen = !optionsPanel.hidden;
            closeAllCustomSelects();
            if (!isOpen) {
                renderOptions();
                optionsPanel.hidden = false;
                wrapper.classList.add('open');
            }
        });

        syncTrigger();
        selectEl._customSelect = { syncTrigger: syncTrigger, renderOptions: renderOptions, wrapper: wrapper, optionsPanel: optionsPanel };
    }

    function closeAllCustomSelects() {
        Array.prototype.forEach.call(
            document.querySelectorAll('.custom-select.open'),
            function (w) {
                w.classList.remove('open');
                var panel = w.querySelector('.custom-select-options');
                if (panel) panel.hidden = true;
            }
        );
    }

    function syncCustomSelect(selectEl) {
        if (selectEl._customSelect) {
            selectEl._customSelect.syncTrigger();
        }
    }

    function initCustomSelects() {
        Array.prototype.forEach.call(
            document.querySelectorAll('select:not([data-customized])'),
            function (sel) { buildCustomSelect(sel); }
        );
    }

    function syncAllCustomSelects() {
        Array.prototype.forEach.call(
            document.querySelectorAll('select[data-customized]'),
            function (sel) { syncCustomSelect(sel); }
        );
    }

    function setFormStatus(message, kind) {
        if (!message) return;
        showToast(message, kind);
    }

    function setStatus(target, message, kind) {
        const effectiveKind = kind || '';
        target.textContent = message || '';
        target.className = effectiveKind ? `status-line ${effectiveKind}` : 'status-line';
    }

    function showToast(message, kind, duration) {
        if (!message) return;
        var ms = duration != null ? duration : (kind === 'error' ? 8000 : 4000);
        var cls = 'toast' + (kind ? ' toast-' + kind : '');
        var el = document.createElement('div');
        el.className = cls;
        el.innerHTML = '<span class="toast-message">' + escapeHtml(message) + '</span>'
            + '<button class="toast-close" type="button" title="Dismiss">&times;</button>';
        toastContainer.appendChild(el);
        var timer = null;
        function dismiss() {
            if (timer) clearTimeout(timer);
            el.classList.add('toast-closing');
            setTimeout(function () { el.remove(); }, 220);
        }
        el.querySelector('.toast-close').addEventListener('click', dismiss);
        if (ms > 0) timer = setTimeout(dismiss, ms);
    }

    // Shared modal helper: supports confirm, alert and prompt modes
    function _showModal(options) {
        return new Promise(function (resolve) {
            var mode = options._mode || 'confirm';
            confirmTitle.textContent = options.title || 'Confirm';
            confirmMessage.textContent = options.message || '';
            confirmOkButton.textContent = options.ok || 'Ok';
            confirmCancelButton.textContent = options.cancel || i18n.t('common.cancel');

            // Style the OK button: danger (red) for confirms, primary for prompts/alerts
            if (mode === 'confirm' && !options.primary) {
                confirmOkButton.classList.add('confirm-danger');
                confirmOkButton.classList.remove('confirm-ok-primary');
            } else {
                confirmOkButton.classList.remove('confirm-danger');
                confirmOkButton.classList.add('confirm-ok-primary');
            }

            // Show/hide input for prompt mode
            if (mode === 'prompt') {
                confirmInput.hidden = false;
                confirmInput.value = options.defaultValue || '';
                confirmInput.placeholder = options.placeholder || '';
            } else {
                confirmInput.hidden = true;
                confirmInput.value = '';
            }

            // Show/hide cancel button for alert mode
            if (mode === 'alert') {
                confirmCancelButton.hidden = true;
            } else {
                confirmCancelButton.hidden = false;
            }

            confirmModal.hidden = false;

            // Focus the appropriate element
            if (mode === 'prompt') {
                confirmInput.focus();
            } else if (mode === 'alert') {
                confirmOkButton.focus();
            } else {
                confirmCancelButton.focus();
            }

            var backdrop = confirmModal.querySelector('.confirm-backdrop');

            function cleanup() {
                confirmModal.hidden = true;
                confirmOkButton.removeEventListener('click', onOk);
                confirmCancelButton.removeEventListener('click', onCancel);
                backdrop.removeEventListener('click', onCancel);
                document.removeEventListener('keydown', onKeyDown, true);
            }

            function getResult() {
                if (mode === 'prompt') return confirmInput.value;
                return true;
            }

            function onOk() { cleanup(); resolve(getResult()); }
            function onCancel() { cleanup(); resolve(mode === 'prompt' ? null : false); }

            // Keyboard: Esc = cancel, Enter = ok, Tab = focus trap
            function onKeyDown(e) {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    e.stopPropagation();
                    onCancel();
                    return;
                }
                if (e.key === 'Enter') {
                    e.preventDefault();
                    e.stopPropagation();
                    if (document.activeElement === confirmCancelButton) {
                        onCancel();
                    } else {
                        onOk();
                    }
                    return;
                }
                if (e.key === 'Tab') {
                    // Focus trap: cycle only between dialog focusable elements
                    var focusable = Array.from(
                        confirmModal.querySelectorAll('button:not([hidden]), input:not([hidden])')
                    ).filter(function (el) { return el.offsetParent !== null; });
                    if (focusable.length === 0) return;
                    var idx = focusable.indexOf(document.activeElement);
                    if (e.shiftKey) {
                        idx = idx <= 0 ? focusable.length - 1 : idx - 1;
                    } else {
                        idx = idx >= focusable.length - 1 ? 0 : idx + 1;
                    }
                    e.preventDefault();
                    focusable[idx].focus();
                }
            }

            document.addEventListener('keydown', onKeyDown, true);
            confirmOkButton.addEventListener('click', onOk);
            confirmCancelButton.addEventListener('click', onCancel);
            backdrop.addEventListener('click', onCancel);
        });
    }

    function showConfirm(options) {
        options._mode = 'confirm';
        return _showModal(options);
    }

    function showAlert(options) {
        if (typeof options === 'string') options = { message: options };
        options._mode = 'alert';
        options.title = options.title || 'Alert';
        options.ok = options.ok || 'Ok';
        options.primary = true;
        return _showModal(options);
    }

    function showPrompt(options) {
        if (typeof options === 'string') options = { message: options };
        options._mode = 'prompt';
        options.title = options.title || 'Input';
        options.ok = options.ok || 'Ok';
        options.primary = true;
        return _showModal(options);
    }

    function isInteractiveTarget(target) {
        return Boolean(
            target
            && typeof target.closest === 'function'
            && target.closest('input, select, textarea, button, a, [contenteditable="true"]')
        );
    }

    function getStoredTheme() {
        try {
            const storedTheme = window.localStorage.getItem(themeStorageKey);
            const legacyTheme = window.localStorage.getItem(legacyThemeStorageKey);
            const resolvedTheme = storedTheme || legacyTheme;
            if (resolvedTheme === 'light' || resolvedTheme === 'dark') {
                return resolvedTheme;
            }
        } catch (error) {
            return '';
        }
        return '';
    }

    function getPreferredTheme() {
        const storedTheme = getStoredTheme();
        if (storedTheme) {
            return storedTheme;
        }
        if (window.matchMedia) {
            if (window.matchMedia('(prefers-color-scheme: light)').matches) return 'light';
            if (window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark';
        }
        return 'dark';
    }

    function getAutoRefreshTitle() {
        if (state.autoRefresh) {
            return i18n.t('activity.auto_refresh_title_on');
        }
        return i18n.t('activity.auto_refresh_title_off');
    }

    function updateAutoRefreshButton() {
        if (!toggleAutoRefreshButton) {
            return;
        }
        toggleAutoRefreshButton.textContent = state.autoRefresh ? i18n.t('activity.auto_refresh_on') : i18n.t('activity.auto_refresh_off');
        toggleAutoRefreshButton.setAttribute('title', getAutoRefreshTitle());
        toggleAutoRefreshButton.setAttribute('aria-label', getAutoRefreshTitle());
    }

    function delay(ms) {
        return new Promise(function (resolve) {
            window.setTimeout(resolve, ms);
        });
    }

    function formatIsoTimestamp(value, showSeconds) {
        if (!value) {
            return '';
        }

        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) {
            return String(value);
        }
        return buildSubmittedDisplay(parsed, showSeconds);
    }

    function markdownToPlainText(markdown) {
        return String(markdown || '')
            .replace(/\r/g, '')
            .replace(/^###\s+/gm, '')
            .replace(/^##\s+/gm, '')
            .replace(/^#\s+/gm, '')
            .replace(/\*\*(.*?)\*\*/g, '$1')
            .replace(/`([^`]+)`/g, '$1')
            .replace(/^\s*-\s+/gm, '- ')
            .replace(/\n{3,}/g, '\n\n')
            .trim();
    }

    function changelogToHtml(markdown) {
        var raw = String(markdown || '').replace(/\r/g, '').trim();
        if (!raw) return '';
        var lines = raw.split('\n');
        var parts = [];
        var inList = false;
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            var headingMatch = line.match(/^#{1,3}\s+(.+)/);
            var bulletMatch = line.match(/^\s*-\s+(.+)/);
            if (headingMatch) {
                if (inList) { parts.push('</ul>'); inList = false; }
                parts.push('<strong>' + escapeHtml(headingMatch[1]) + '</strong>');
            } else if (bulletMatch) {
                if (!inList) { parts.push('<ul>'); inList = true; }
                var text = escapeHtml(bulletMatch[1])
                    .replace(/`([^`]+)`/g, '<code>$1</code>')
                    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
                parts.push('<li>' + text + '</li>');
            } else if (line.trim() === '') {
                if (inList) { parts.push('</ul>'); inList = false; }
            }
        }
        if (inList) parts.push('</ul>');
        return parts.join('\n');
    }

    function buildReleaseTooltip(updateInfo) {
        if (updateInfo.update_in_progress) {
            return i18n.t('release.installing_tooltip');
        }

        if (updateInfo.update_available) {
            const heading = i18n.t('release.update_available_tooltip', { local: updateInfo.local_version, remote: updateInfo.remote_version });
            const changelog = markdownToPlainText(updateInfo.changelog);
            return changelog ? `${heading}\n\n${changelog}` : heading;
        }

        const checkedAt = formatIsoTimestamp(updateInfo.checked_at);
        return checkedAt
            ? i18n.t('release.check_tooltip_date', { date: checkedAt })
            : i18n.t('release.check_tooltip');
    }

    function renderReleaseControl(updateInfo) {
        const nextInfo = {
            local_version: String(updateInfo.local_version || state.release.local_version || ''),
            remote_version: String(updateInfo.remote_version || ''),
            update_available: Boolean(updateInfo.update_available),
            changelog: String(updateInfo.changelog || ''),
            checked_at: String(updateInfo.checked_at || ''),
            last_error: String(updateInfo.last_error || ''),
            update_in_progress: Boolean(updateInfo.update_in_progress),
            update_step: Number(updateInfo.update_step) || 0,
            update_step_total: Number(updateInfo.update_step_total) || 5,
            update_step_label: String(updateInfo.update_step_label || ''),
            runtime_environment: String(updateInfo.runtime_environment || ''),
        };

        // If local matches remote, the update is done — treat as no-update
        if (nextInfo.local_version && nextInfo.remote_version && nextInfo.local_version === nextInfo.remote_version) {
            nextInfo.update_available = false;
        }

        state.release = nextInfo;

        // Version display
        if (aboutVersion) {
            aboutVersion.textContent = nextInfo.local_version ? 'v' + nextInfo.local_version : '\u2014';
        }
        if (aboutEnvironment) {
            aboutEnvironment.textContent = nextInfo.runtime_environment || '\u2014';
        }

        // Update button
        if (releaseButton && releaseLabel) {
            let label = i18n.t('release.check_for_updates');
            if (nextInfo.update_in_progress) {
                label = nextInfo.update_step_label || i18n.t('release.updating');
            } else if (nextInfo.update_available && nextInfo.remote_version) {
                var isDocker = nextInfo.runtime_environment && nextInfo.runtime_environment.toLowerCase().indexOf('docker') !== -1;
                label = isDocker
                    ? i18n.t('release.update_available_docker', { version: nextInfo.remote_version })
                    : i18n.t('release.update_to', { version: nextInfo.remote_version });
            }

            releaseLabel.textContent = label;
            releaseButton.disabled = nextInfo.update_in_progress;
            releaseButton.dataset.busy = nextInfo.update_in_progress ? 'true' : 'false';
            releaseButton.classList.toggle('has-badge', nextInfo.update_available);
        }

        // Update progress bar
        var updateProgressEl = document.getElementById('update-progress');
        if (updateProgressEl) {
            updateProgressEl.hidden = !nextInfo.update_in_progress;
            var fill = updateProgressEl.querySelector('.update-progress-fill');
            if (fill) {
                if (nextInfo.update_in_progress && nextInfo.update_step > 0) {
                    var pct = Math.min(100, Math.round((nextInfo.update_step / nextInfo.update_step_total) * 100));
                    fill.style.animation = 'none';
                    fill.style.marginLeft = '0';
                    fill.style.width = pct + '%';
                    fill.style.transition = 'width 0.6s ease';
                } else if (nextInfo.update_in_progress) {
                    fill.style.width = '';
                    fill.style.marginLeft = '';
                    fill.style.transition = '';
                    fill.style.animation = '';
                }
            }
        }

        // Changelog text
        if (changelogRow && changelogText) {
            var cl = changelogToHtml(nextInfo.changelog);
            if (cl && nextInfo.update_available && !nextInfo.update_in_progress) {
                changelogText.innerHTML = cl;
                changelogRow.hidden = false;
            } else {
                changelogRow.hidden = true;
            }
        }

        // System nav badge
        if (navSystemBadge) {
            navSystemBadge.hidden = !nextInfo.update_available;
            navSystemBadge.textContent = '!';
        }

        // Sidebar version dot
        if (sidebarVersion && nextInfo.local_version) {
            var existingDot = sidebarVersion.querySelector('.sidebar-version-dot');
            if (nextInfo.update_available && !existingDot) {
                var anchor = sidebarVersion.querySelector('a');
                if (anchor) {
                    var dotEl = document.createElement('span');
                    dotEl.className = 'sidebar-version-dot';
                    dotEl.title = i18n.t('release.update_available_dot', { version: nextInfo.remote_version });
                    anchor.appendChild(dotEl);
                }
            } else if (!nextInfo.update_available && existingDot) {
                existingDot.remove();
            }
        }
    }

    async function waitForReleaseRestart(targetVersion) {
        let lastError = '';

        for (let attempt = 0; attempt < 45; attempt += 1) {
            await delay(attempt < 5 ? 1000 : 2000);

            try {
                const payload = await fetchJson('/config');
                renderMeta(payload);
                applySummaryToForms(payload);
                renderWatchers(payload.watchers || []);
                const updateInfo = payload.update_info || {};
                renderReleaseControl(updateInfo);

                // Keep changelog visible during upgrade until "Install complete" (step 6)
                if (updateInfo.update_in_progress && updateInfo.update_step < 6 && changelogRow) {
                    changelogRow.hidden = false;
                }

                if (!updateInfo.update_in_progress && (!targetVersion || updateInfo.local_version === targetVersion)) {
                    showToast(i18n.t('toast.service_restarted', { version: updateInfo.local_version || targetVersion }), 'ok');
                    // Full reload so all cached assets and state refresh cleanly
                    setTimeout(function () { location.reload(); }, 1200);
                    return;
                }
            } catch (error) {
                lastError = error.message;
            }
        }

        showToast(
            lastError || i18n.t('toast.service_restarting'),
            'error', 0
        );
    }

    // ── Full changelog page ──

    var changelogLastFetched = 0;
    var CHANGELOG_CLIENT_TTL = 300000; // 5 min client-side re-fetch guard

    function changelogMarkdownToHtml(md, localVersion) {
        var lines = String(md || '').split('\n');
        var html = [];
        var inList = false;
        var localParts = String(localVersion || '').split('.').map(Number);

        function isNewer(ver) {
            if (!localParts.length || !localParts[0]) return false;
            var parts = ver.split('.').map(Number);
            for (var j = 0; j < Math.max(parts.length, localParts.length); j++) {
                var a = parts[j] || 0;
                var b = localParts[j] || 0;
                if (a > b) return true;
                if (a < b) return false;
            }
            return false;
        }

        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];

            // Skip top-level heading ("# Changelog") and boilerplate description
            if (line.match(/^# /)) continue;
            if (line.match(/^All notable changes/i)) continue;

            // ## [version] - date
            var versionMatch = line.match(/^## \[(.+?)\]\s*-\s*(.+)/);
            if (versionMatch) {
                if (inList) { html.push('</ul>'); inList = false; }
                var extraClass = isNewer(versionMatch[1]) ? ' changelog-version-new' : '';
                html.push('<div class="changelog-version-block' + extraClass + '" id="changelog-' + escapeHtml(versionMatch[1]) + '">');
                var badge = isNewer(versionMatch[1]) ? ' <span class="changelog-new-badge">' + escapeHtml(i18n.t('system.changelog.new_badge')) + '</span>' : '';
                html.push('<h3 class="changelog-version-title">' + escapeHtml('v' + versionMatch[1]) + badge + ' <span class="changelog-date">' + escapeHtml(versionMatch[2].trim()) + '</span></h3>');
                continue;
            }

            // ### Section heading
            var sectionMatch = line.match(/^### (.+)/);
            if (sectionMatch) {
                if (inList) { html.push('</ul>'); inList = false; }
                html.push('<strong>' + escapeHtml(sectionMatch[1]) + '</strong>');
                continue;
            }

            // Bullet items
            var bulletMatch = line.match(/^- (.+)/);
            if (bulletMatch) {
                if (!inList) { html.push('<ul>'); inList = true; }
                var text = escapeHtml(bulletMatch[1])
                    .replace(/`([^`]+)`/g, '<code>$1</code>')
                    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
                html.push('<li>' + text + '</li>');
                continue;
            }

            // Close list on empty lines / other content
            if (line.trim() === '') {
                if (inList) { html.push('</ul>'); inList = false; }
                // Close version block if next line is a new version or EOF
                if (i + 1 < lines.length && lines[i + 1].match(/^## \[/)) {
                    html.push('</div>');
                }
                continue;
            }

            // Plain paragraph text
            if (line.trim()) {
                if (inList) { html.push('</ul>'); inList = false; }
                var pText = escapeHtml(line.trim())
                    .replace(/`([^`]+)`/g, '<code>$1</code>')
                    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
                html.push('<p class="changelog-paragraph">' + pText + '</p>');
            }
        }
        if (inList) html.push('</ul>');
        html.push('</div>'); // close last version block
        return html.join('\n');
    }

    async function loadFullChangelog(force) {
        var now = Date.now();
        if (!force && changelogLastFetched && (now - changelogLastFetched) < CHANGELOG_CLIENT_TTL) return;
        var container = document.getElementById('changelog-full-container');
        if (!container) return;
        try {
            var url = force ? '/system/changelog?force=true' : '/system/changelog';
            var data = await fetchJson(url);
            var rendered = changelogMarkdownToHtml(data.changelog || '', state.release.local_version);
            container.innerHTML = '<div class="changelog-text changelog-full-text">' + rendered + '</div>';
            changelogLastFetched = Date.now();
        } catch (err) {
            container.innerHTML = '<div class="empty">Failed to load changelog.</div>';
        }
    }

    function applyTheme(theme) {
        const nextTheme = theme === 'dark' ? 'dark' : 'light';

        state.theme = nextTheme;
        document.documentElement.setAttribute('data-theme', nextTheme);
        if (themeSelect) {
            themeSelect.value = nextTheme;
        }
    }

    function persistTheme(theme) {
        try {
            window.localStorage.setItem(themeStorageKey, theme);
            window.localStorage.removeItem(legacyThemeStorageKey);
        } catch (error) {
            return;
        }
    }

    async function fetchJson(path, options) {
        const requestOptions = Object.assign({}, options || {});
        const method = String(requestOptions.method || 'GET').toUpperCase();
        let requestPath = path;

        if (method === 'GET') {
            const separator = path.indexOf('?') !== -1 ? '&' : '?';
            requestPath = `${path}${separator}_ts=${Date.now()}`;
            requestOptions.cache = 'no-store';
        }

        // Inject auth token
        if (state.auth.token) {
            requestOptions.headers = Object.assign({}, requestOptions.headers || {});
            requestOptions.headers['Authorization'] = 'Bearer ' + state.auth.token;
        }

        const response = await fetch(requestPath, requestOptions);

        if (response.status === 401 && state.auth.enabled) {
            state.auth.token = '';
            state.auth.user = null;
            try { localStorage.removeItem(tokenStorageKey); } catch (ignored) { /* noop */ }
            window.location.replace('/login');
            throw new Error(i18n.t('auth.session_expired'));
        }

        const payload = await response.json().catch(function () {
            return {};
        });

        if (!response.ok) {
            throw new Error(payload.error || `Request failed with status ${response.status}`);
        }
        return payload;
    }

    function normalizePaths(paths) {
        const seen = {};
        const normalized = [];

        Array.prototype.forEach.call(paths || [], function (value) {
            const path = String(value || '').trim();
            if (!path || Object.prototype.hasOwnProperty.call(seen, path)) {
                return;
            }
            seen[path] = true;
            normalized.push(path);
        });

        return normalized;
    }

    function setInputSelection(path, kind) {
        const nextKind = kind === 'directory' ? 'directory' : 'file';
        inputFileField.value = path || '';
        inputKindField.value = nextKind;
        inputFileField.dispatchEvent(new Event('change', { bubbles: true }));
        if (recursiveToggleInline) recursiveToggleInline.hidden = nextKind !== 'directory';
        if (filterPatternRow) filterPatternRow.hidden = nextKind !== 'directory';
        inputFileField.setAttribute(
            'title',
            path
                ? `Selected source ${nextKind === 'directory' ? 'folder' : 'file'}: ${path}`
                : 'Source file or folder to convert. Use the chooser buttons to browse the source.'
        );
        if (nextKind !== 'directory') {
            inputRecursiveField.checked = false;
            if (inputFilterPattern) inputFilterPattern.value = '';
            if (filterPreview) filterPreview.innerHTML = '';
            var previewRow = document.getElementById('filter-preview-row');
            if (previewRow) previewRow.hidden = true;
        }

        if (!path) {
            inputSelectionHint.textContent = i18n.t('jobs.hint_choose');
            return;
        }

        if (nextKind === 'directory') {
            inputSelectionHint.textContent = i18n.t('jobs.hint_folder');
            if (path) scheduleFilterPreview();
            return;
        }

        inputSelectionHint.textContent = i18n.t('jobs.hint_file');
    }

    function clearInputSelection() {
        setInputSelection('', 'file');
    }

    // ── Filter pattern live preview ──
    var filterPreview = document.getElementById('filter-preview');
    var filterPreviewTimer = null;

    function fetchFilterPreview() {
        var dir = inputFileField.value;
        var pattern = inputFilterPattern ? inputFilterPattern.value.trim() : '';
        var previewRow = document.getElementById('filter-preview-row');
        if (!dir || inputKindField.value !== 'directory' || !pattern) {
            if (filterPreview) filterPreview.innerHTML = '';
            if (previewRow) previewRow.hidden = true;
            return;
        }
        var recursive = inputRecursiveField.checked ? '1' : '0';
        var url = '/browse/match?path=' + encodeURIComponent(dir)
            + '&pattern=' + encodeURIComponent(pattern)
            + '&recursive=' + recursive;
        filterPreview.innerHTML = '<div class="filter-preview-loading"><span class="filter-preview-spinner"></span>Searching…</div>';
        if (previewRow) previewRow.hidden = false;
        fetchJson(url).then(function (data) {
            if (!filterPreview) return;
            var names = data.matches || [];
            var total = data.total || 0;
            if (!names.length) {
                filterPreview.innerHTML = '<div class="filter-preview-header">No matches</div>';
                if (previewRow) previewRow.hidden = false;
                return;
            }
            var maxShow = 30;
            var label = total + ' file' + (total !== 1 ? 's' : '') + ' matching';
            var html = '<div class="filter-preview-header">' + escapeHtml(label) + '</div>';
            html += '<ul class="filter-preview-list">';
            names.slice(0, maxShow).forEach(function (n) {
                html += '<li>' + escapeHtml(n) + '</li>';
            });
            html += '</ul>';
            if (total > maxShow) {
                html += '<div class="filter-preview-more">\u2026 and ' + (total - maxShow) + ' more</div>';
            }
            filterPreview.innerHTML = html;
            if (previewRow) previewRow.hidden = false;
        }).catch(function () {
            if (filterPreview) filterPreview.innerHTML = '';
            if (previewRow) previewRow.hidden = true;
        });
    }

    function scheduleFilterPreview() {
        if (filterPreviewTimer) clearTimeout(filterPreviewTimer);
        filterPreviewTimer = setTimeout(fetchFilterPreview, 350);
    }

    if (inputFilterPattern) {
        inputFilterPattern.addEventListener('input', scheduleFilterPreview);
    }
    if (inputRecursiveField) {
        inputRecursiveField.addEventListener('change', function () {
            if (inputKindField.value === 'directory' && inputFileField.value) {
                scheduleFilterPreview();
            }
        });
    }

    function setWatcherDirectory(path) {
        watcherDirectoryField.value = path || '';
        watcherDirectoryField.dispatchEvent(new Event('change', { bubbles: true }));
        watcherDirectoryField.setAttribute(
            'title',
            path
                ? i18n.t('watchers.selected_source_dir', { path: path })
                : i18n.t('watchers.source_dir_tooltip')
        );
    }

    function setWatcherOutputDir(path) {
        watcherOutputDirField.value = path || '';
        watcherOutputDirField.dispatchEvent(new Event('change', { bubbles: true }));
        watcherOutputDirField.setAttribute(
            'title',
            path
                ? `Override output directory: ${path}`
                : 'Override the output directory for files converted by this watcher.'
        );
    }

    function resetWatcherForm() {
        state.editingWatcherId = null;
        watcherForm.reset();
        setWatcherDirectory('');
        setWatcherOutputDir('');
        watcherForm.elements.poll_interval.value = '5';
        watcherForm.elements.settle_time.value = '30';
        watcherForm.elements.delete_source.checked = settingsForm.elements.default_delete_source.checked;
        watcherForm.elements.codec.value = '';
        watcherForm.elements.encode_speed.value = '';
        if (watcherForm.elements.preset_id) {
            watcherForm.elements.preset_id.value = '';
            watcherForm.elements.preset_id.dispatchEvent(new Event('change'));
        }
        watcherForm.elements.audio_passthrough.checked = false;
        watcherForm.elements.force.checked = false;
        syncAllCustomSelects();
        watcherButton.textContent = i18n.t('watchers.add_watcher');
        cancelEditWatcherButton.hidden = true;
        // Re-enable Edit/Remove buttons
        Array.prototype.forEach.call(
            watchersContainer.querySelectorAll('[data-edit-watcher], [data-remove-watcher]'),
            function (btn) { btn.disabled = false; }
        );
        resetDirtyTracker('watcher-form');
    }

    function syncAllowedRootsField() {
        settingsForm.elements.allowed_roots.value = state.allowedRoots.join('\n');
    }

    function renderAllowedRoots() {
        syncAllowedRootsField();

        if (!state.allowedRoots.length) {
            allowedRootsList.innerHTML = '<div class="empty">' + i18n.t('settings.allowed_roots_empty') + '</div>';
            return;
        }

        allowedRootsList.innerHTML = state.allowedRoots.map(function (root, index) {
            return `
                <div class="list-item">
                    <div class="job-name">${i18n.t('settings.allowed_root_n', { n: index + 1 })}</div>
                    <div class="path-code" title="${escapeHtml(root)}">${escapeHtml(root)}</div>
                    <div class="actions">
                        <button class="ghost" type="button" data-remove-allowed-root="${index}" title="${i18n.t('settings.remove_root_tooltip')}">${i18n.t('common.remove')}</button>
                    </div>
                </div>`;
        }).join('');

        Array.prototype.forEach.call(
            allowedRootsList.querySelectorAll('[data-remove-allowed-root]'),
            function (button) {
                button.addEventListener('click', function () {
                    const index = Number(button.dataset.removeAllowedRoot);
                    if (!Number.isFinite(index)) {
                        return;
                    }
                    state.allowedRoots.splice(index, 1);
                    renderAllowedRoots();
                    if (settingsButton) settingsButton.disabled = false;
                    setStatus(settingsStatus, i18n.t('toast.allowed_root_removed'), 'ok');
                });
            }
        );
    }

    function setAllowedRoots(roots) {
        state.allowedRoots = normalizePaths(roots);
        renderAllowedRoots();
    }

    function addAllowedRoot(path) {
        const normalized = String(path || '').trim();
        if (!normalized) {
            return;
        }
        if (state.allowedRoots.indexOf(normalized) !== -1) {
            setStatus(settingsStatus, i18n.t('toast.allowed_root_exists'), 'ok');
            return;
        }
        state.allowedRoots = state.allowedRoots.concat([normalized]);
        renderAllowedRoots();
        if (settingsButton) settingsButton.disabled = false;
        setStatus(settingsStatus, i18n.t('toast.allowed_root_added'), 'ok');
    }

    function setBrowserStatus(message, kind) {
        setStatus(browserStatus, message, kind);
    }

    function renderBrowserRoots(roots) {
        if (!browserRoots) return;
        browserRoots.innerHTML = '';
    }

    function focusBrowserFilter() {
        window.setTimeout(function () {
            if (!browserModal.hidden) {
                browserFilter.focus();
            }
        }, 0);
    }

    function closePathBrowser() {
        state.browser.open = false;
        browserModal.hidden = true;
        document.body.classList.remove('modal-open');
        if (browserRoots) browserRoots.innerHTML = '';
        browserList.innerHTML = '';
        browserCurrentPath.value = '';
        browserShowHidden.checked = false;
        browserFilter.value = '';
        state.browser.filterQuery = '';
        state.browser.activeEntryIndex = -1;
        setBrowserStatus('', '');
    }

    /* ── Scroll + Highlight utility ── */

    function scrollAndHighlight(el) {
        if (!el) return;
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        el.classList.remove('highlight-pulse');
        void el.offsetWidth;
        el.classList.add('highlight-pulse');
        el.addEventListener('animationend', function () {
            el.classList.remove('highlight-pulse');
        }, { once: true });
    }

    /* ── Sidebar Navigation ── */

    var validPages = [
        'activity', 'jobs', 'watchers', 'schedule',
        'settings/general', 'settings/binaries', 'settings/media', 'settings/presets', 'settings/smtp', 'settings/notifications', 'settings/logs', 'settings/user',
        'system/users', 'system/logs', 'system/tasks', 'system/changelog', 'system/about',
    ];

    function navigateTo(page) {
        if (validPages.indexOf(page) === -1) page = 'activity';

        // Role guard: non-admins cannot access settings/* (except settings/user) or system/* pages
        if (state.auth.enabled && state.auth.user && state.auth.user.role !== 'admin') {
            if ((page.indexOf('settings/') === 0 && page !== 'settings/user') || page.indexOf('system/') === 0) {
                page = 'activity';
            }
        }

        validPages.forEach(function (p) {
            var section = document.getElementById('page-' + p.replace('/', '-'));
            if (section) section.hidden = (p !== page);
        });

        var links = sidebar.querySelectorAll('.sidebar-link');
        links.forEach(function (link) {
            link.classList.toggle('active', link.dataset.page === page);
        });

        // Also sync flyout links
        var flyoutLinks = sidebar.querySelectorAll('.sidebar-flyout a');
        flyoutLinks.forEach(function (link) {
            link.classList.toggle('active', link.dataset.page === page);
        });

        // Auto-open the parent sidebar group when navigating to a sub-page
        if (!isCollapsedSidebar()) {
            var groups = sidebar.querySelectorAll('.sidebar-group');
            groups.forEach(function (group) {
                var toggle = group.querySelector('.sidebar-group-toggle');
                if (!toggle) return;
                var groupName = toggle.dataset.group;
                if (page.indexOf(groupName + '/') === 0) {
                    // Accordion: close others first
                    sidebar.querySelectorAll('.sidebar-group.open').forEach(function (g) {
                        if (g !== group) g.classList.remove('open');
                    });
                    group.classList.add('open');
                }
            });
        }

        if (page === 'schedule' && priceProvider.value) {
            loadPriceChart();
        }
        if (page === 'settings/media' || page === 'watchers') {
            initCustomSelects();
            syncAllCustomSelects();
        }
        if (page === 'settings/presets') {
            loadPresetsPage();
        }
        if (page === 'system/about') {
            startSysmonPolling();
        } else {
            stopSysmonPolling();
        }
        if (page === 'system/logs') {
            loadLogFilesTable();
        } else {
            stopLogPolling();
        }
        if (page === 'system/users') {
            refreshUsers();
            refreshAdminTokens();
            if (state.auth.user && state.auth.user.role === 'admin') {
                refreshSmtp();
            }
        }
        if (page === 'system/tasks') {
            loadTasks();
        }
        if (page === 'system/changelog') {
            loadFullChangelog();
        }
        if (page === 'settings/smtp') {
            refreshSmtp();
        }
        if (page === 'settings/notifications') {
            loadNotifChannels();
            closeNotifEditor();
        }
        if (page === 'settings/user') {
            populateUserSettings();
            refreshUserTokens();
        }
        closeSidebar();

        // Auto-focus the filter input when navigating to the activity page
        if (page === 'activity') {
            requestAnimationFrame(function () { jobsFilterText.focus(); });
        }

        // Scroll to sub-section if specified
        var scrollTarget = getScrollTargetFromHash();
        if (scrollTarget) {
            requestAnimationFrame(function () {
                var el = document.getElementById(scrollTarget);
                if (el) scrollAndHighlight(el);
            });
        }
    }

    function getPageFromHash() {
        var raw = window.location.hash.replace('#', '');
        var parts = raw.split(':');
        var page = parts[0];
        return validPages.indexOf(page) !== -1 ? page : 'activity';
    }

    function getScrollTargetFromHash() {
        var raw = window.location.hash.replace('#', '');
        var parts = raw.split(':');
        return parts[1] || null;
    }

    function closeSidebar() {
        sidebar.classList.remove('open');
        sidebarOverlay.hidden = true;
    }

    /* ── Schedule UI ── */

    var DAY_LABELS = [i18n.t('schedule.day_mon'), i18n.t('schedule.day_tue'), i18n.t('schedule.day_wed'), i18n.t('schedule.day_thu'), i18n.t('schedule.day_fri'), i18n.t('schedule.day_sat'), i18n.t('schedule.day_sun')];
    var DAY_VALUES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

    function makeDefaultRule() {
        return { days: ['mon', 'tue', 'wed', 'thu', 'fri'], start: '00:00', end: '07:00', action: 'allow' };
    }

    function renderScheduleRules() {
        var rules = state.scheduleRules;
        if (!rules.length) {
            scheduleRulesList.innerHTML = '<div class="empty">' + i18n.t('schedule.no_rules') + '</div>';
            return;
        }

        scheduleRulesList.innerHTML = rules.map(function (rule, index) {
            var dayChecks = DAY_VALUES.map(function (d, di) {
                var checked = (rule.days || []).indexOf(d) !== -1 ? ' checked' : '';
                return '<label class="check check-compact" title="' + DAY_LABELS[di] + '">'
                    + '<input type="checkbox" data-rule="' + index + '" data-day="' + d + '"' + checked + '>'
                    + DAY_LABELS[di] + '</label>';
            }).join('');

            return '<div class="schedule-rule" data-rule-index="' + index + '">'
                + '<div class="schedule-rule-fields">'
                + '<div class="checks checks-inline">' + dayChecks + '</div>'
                + '<label><span>' + i18n.t('schedule.from') + '</span><input type="time" value="' + escapeHtml(rule.start || '00:00') + '" data-rule="' + index + '" data-field="start"></label>'
                + '<label><span>' + i18n.t('schedule.to') + '</span><input type="time" value="' + escapeHtml(rule.end || '07:00') + '" data-rule="' + index + '" data-field="end"></label>'
                + '<label><span>' + i18n.t('schedule.action') + '</span><select data-rule="' + index + '" data-field="action">'
                + '<option value="allow"' + (rule.action === 'allow' ? ' selected' : '') + '>' + i18n.t('schedule.action_allow') + '</option>'
                + '<option value="block"' + (rule.action === 'block' ? ' selected' : '') + '>' + i18n.t('schedule.action_block') + '</option>'
                + '</select></label>'
                + '<button class="ghost" type="button" data-remove-rule="' + index + '" title="' + escapeHtml(i18n.t('schedule.remove_rule_title')) + '">&times;</button>'
                + '</div></div>';
        }).join('');

        Array.prototype.forEach.call(
            scheduleRulesList.querySelectorAll('[data-remove-rule]'),
            function (btn) {
                btn.addEventListener('click', function () {
                    var idx = Number(btn.dataset.removeRule);
                    state.scheduleRules.splice(idx, 1);
                    renderScheduleRules();
                    if (saveScheduleButton) saveScheduleButton.disabled = false;
                });
            }
        );

        Array.prototype.forEach.call(
            scheduleRulesList.querySelectorAll('[data-day]'),
            function (cb) {
                cb.addEventListener('change', function () {
                    var idx = Number(cb.dataset.rule);
                    var day = cb.dataset.day;
                    var rule = state.scheduleRules[idx];
                    if (!rule) return;
                    if (cb.checked) {
                        if (rule.days.indexOf(day) === -1) rule.days.push(day);
                    } else {
                        rule.days = rule.days.filter(function (d) { return d !== day; });
                    }
                    if (saveScheduleButton) saveScheduleButton.disabled = false;
                });
            }
        );

        Array.prototype.forEach.call(
            scheduleRulesList.querySelectorAll('[data-field]'),
            function (input) {
                input.addEventListener('change', function () {
                    var idx = Number(input.dataset.rule);
                    var field = input.dataset.field;
                    var rule = state.scheduleRules[idx];
                    if (!rule) return;
                    rule[field] = input.value;
                    if (saveScheduleButton) saveScheduleButton.disabled = false;
                });
            }
        );

        initCustomSelects();
    }

    function updateScheduleSections() {
        var enabled = scheduleEnabled.checked;
        var mode = scheduleMode.value;
        var showManual = enabled && (mode === 'manual' || mode === 'both');
        var showPrice = enabled && (mode === 'price' || mode === 'both');
        var showPriority = enabled && mode === 'both';

        scheduleManualSection.hidden = !showManual;
        schedulePriceSection.hidden = !showPrice;
        schedulePriority.closest('.field-row').hidden = !showPriority;
        schedulePauseBehavior.closest('.field-row').hidden = !enabled;
        scheduleMode.closest('.field-row').hidden = !enabled;

        updatePriceSections();
    }

    function updatePriceSections() {
        var pv = priceProvider.value;
        var isEntsoe = pv === 'entsoe';
        var isRee = pv === 'ree_pvpc';
        entsoeKeyLabel.hidden = !isEntsoe;
        // REE PVPC is Spain-only; hide bidding zone selector
        priceBiddingZone.closest('.field-row').hidden = isRee;

        var strategy = priceStrategy.value;
        priceThresholdLabel.hidden = strategy !== 'threshold';
        priceCheapestLabel.hidden = strategy !== 'cheapest_n';
    }

    function renderPriceChart(prices, thresholdValue) {
        if (!prices || !prices.length) {
            priceChartWrap.hidden = true;
            return;
        }

        priceChartWrap.hidden = false;
        var maxPrice = Math.max.apply(null, prices.map(function (p) { return p.price; }));
        if (maxPrice <= 0) maxPrice = 1;
        var threshold = (Number(thresholdValue) || 0) * 1000; // kWh input → MWh for comparison
        var now = Date.now() / 1000;

        var sorted = prices.slice().sort(function (a, b) { return a.price - b.price; });
        var cheapestCount = Number(priceCheapestHours.value) || 8;
        var cheapHours = {};
        for (var ci = 0; ci < Math.min(cheapestCount, sorted.length); ci++) {
            cheapHours[sorted[ci].start] = true;
        }

        var bars = prices.map(function (p) {
            var height = Math.max(1, (Math.abs(p.price) / maxPrice) * 100);
            var isCurrent = p.start <= now && now < p.end;
            var isOver = threshold > 0 && p.price > threshold;
            var isCheap = cheapHours[p.start];
            var cls = 'price-bar';
            if (isCurrent) cls += ' price-bar-current';
            if (isOver) cls += ' price-bar-over';
            else if (isCheap) cls += ' price-bar-cheap';
            var hour = new Date(p.start * 1000).getHours();
            var label = String(hour).length < 2 ? '0' + hour : String(hour);
            var pKwh = (p.price / 1000);
            return '<div class="' + cls + '" style="height:' + height.toFixed(1) + '%" title="'
                + label + ':00 — ' + pKwh.toFixed(5) + ' ' + i18n.t('schedule.price_unit') + '">'
                + '<span class="price-bar-label">' + label + '</span></div>';
        }).join('');

        var thresholdLine = '';
        if (threshold > 0 && threshold < maxPrice) {
            var linePos = (threshold / maxPrice) * 100;
            thresholdLine = '<div class="price-threshold-line" style="bottom:' + linePos.toFixed(1) + '%"></div>';
        }

        priceChart.innerHTML = bars + thresholdLine;

        var currentPrice = null;
        for (var pi = 0; pi < prices.length; pi++) {
            if (prices[pi].start <= now && now < prices[pi].end) {
                currentPrice = prices[pi].price;
                break;
            }
        }

        var cheapestRange = '';
        if (sorted.length >= cheapestCount) {
            var cheapSorted = sorted.slice(0, cheapestCount).sort(function (a, b) { return a.start - b.start; });
            var ranges = [];
            var rStart = new Date(cheapSorted[0].start * 1000).getHours();
            var rEnd = rStart;
            for (var ri = 1; ri < cheapSorted.length; ri++) {
                var h = new Date(cheapSorted[ri].start * 1000).getHours();
                if (h === rEnd + 1 || (rEnd === 23 && h === 0)) {
                    rEnd = h;
                } else {
                    ranges.push((rStart < 10 ? '0' : '') + rStart + ':00–' + (rEnd + 1 < 10 ? '0' : '') + ((rEnd + 1) % 24) + ':00');
                    rStart = h;
                    rEnd = h;
                }
            }
            ranges.push((rStart < 10 ? '0' : '') + rStart + ':00–' + ((rEnd + 1) % 24 < 10 ? '0' : '') + ((rEnd + 1) % 24) + ':00');
            cheapestRange = i18n.t('schedule.cheapest_range', {count: cheapestCount}) + ranges.join(', ');
        }

        var isRee = priceProvider.value === 'ree_pvpc';
        var priceLabel = isRee ? i18n.t('schedule.price_pvpc') : i18n.t('schedule.price_spot');
        var summary = i18n.t('schedule.price_summary', {label: priceLabel, count: prices.length});
        if (currentPrice != null) {
            summary += ' · ' + i18n.t('schedule.price_now') + ': ' + (currentPrice / 1000).toFixed(5) + ' ' + i18n.t('schedule.price_unit');
        }
        if (sorted.length) summary += ' · ' + i18n.t('schedule.price_min') + ': ' + (sorted[0].price / 1000).toFixed(5) + ' · ' + i18n.t('schedule.price_max') + ': ' + (sorted[sorted.length - 1].price / 1000).toFixed(5);
        summary += cheapestRange;
        priceChartLabel.textContent = summary;
    }

    function renderScheduleStatusBar(status) {
        if (!status || !status.enabled) {
            scheduleStatusBar.innerHTML = '';
            scheduleStatusBar.className = 'schedule-status-bar schedule-disabled';
            scheduleStatusBar.hidden = true;
            return;
        }

        scheduleStatusBar.hidden = false;
        var allowed = status.allowed !== false;
        scheduleStatusBar.className = 'schedule-status-bar ' + (allowed ? 'schedule-allowed' : 'schedule-blocked');
        var label = allowed ? i18n.t('schedule.conversions_allowed') : i18n.t('schedule.conversions_blocked');
        if (status.reason) label += ' — ' + status.reason;
        if (status.current_price != null) {
            label += ' ' + i18n.t('schedule.status_current_price', {price: (Number(status.current_price) / 1000).toFixed(5)});
        }
        scheduleStatusBar.textContent = label;
    }

    function populateBiddingZones(zones) {
        if (!zones || !zones.length) return;
        state.biddingZones = zones;
        var current = priceBiddingZone.value;
        var options = '<option value="">' + i18n.t('schedule.zone_select') + '</option>';
        zones.forEach(function (zone) {
            var code = zone.code || '';
            var label = zone.label || code;
            var selected = code === current ? ' selected' : '';
            options += '<option value="' + escapeHtml(code) + '"' + selected + '>'
                + escapeHtml(label) + ' (' + escapeHtml(code) + ')</option>';
        });
        priceBiddingZone.innerHTML = options;
        if (current) priceBiddingZone.value = current;
    }

    function applyScheduleToForm(config, status) {
        if (!config) config = {};
        scheduleEnabled.checked = Boolean(config.enabled);
        scheduleMode.value = config.mode || 'manual';
        schedulePriority.value = config.priority || 'both_must_allow';
        schedulePauseBehavior.value = config.pause_behavior || 'block_new';

        state.scheduleRules = (config.manual_rules || []).map(function (r) {
            return { days: (r.days || []).slice(), start: r.start || '00:00', end: r.end || '07:00', action: r.action || 'allow' };
        });
        renderScheduleRules();

        var price = config.price || {};
        priceProvider.value = price.provider || '';
        if (price.bidding_zone) priceBiddingZone.value = price.bidding_zone;
        priceEntsoeKey.value = price.entsoe_api_key || '';
        priceStrategy.value = price.strategy || 'threshold';
        priceThreshold.value = price.threshold != null ? (Number(price.threshold) / 1000).toFixed(4) : '0.0000';
        priceCheapestHours.value = price.cheapest_hours != null ? String(price.cheapest_hours) : '8';

        renderScheduleStatusBar(status);
        updateScheduleSections();

        if (price.provider) {
            loadPriceChart();
        }
    }

    function collectScheduleConfig() {
        var rules = state.scheduleRules.map(function (r) {
            return { days: r.days.slice(), start: r.start, end: r.end, action: r.action };
        });

        return {
            enabled: scheduleEnabled.checked,
            mode: scheduleMode.value,
            priority: schedulePriority.value,
            pause_behavior: schedulePauseBehavior.value,
            manual_rules: rules,
            price: {
                provider: priceProvider.value,
                bidding_zone: priceProvider.value === 'ree_pvpc' ? 'ES' : priceBiddingZone.value,
                entsoe_api_key: priceEntsoeKey.value,
                strategy: priceStrategy.value,
                threshold: (Number(priceThreshold.value) || 0) * 1000,
                cheapest_hours: Number(priceCheapestHours.value) || 8,
            },
        };
    }

    async function saveSchedule() {
        saveScheduleButton.disabled = true;
        setStatus(scheduleStatusEl, i18n.t('toast.saving_schedule'));

        try {
            await fetchJson('/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ schedule_config: collectScheduleConfig() }),
            });
            setStatus(scheduleStatusEl, i18n.t('toast.schedule_saved'), 'ok');
            resetDirtyTracker('schedule');
            await Promise.all([refreshSummary(), refreshJobs()]);
        } catch (error) {
            setStatus(scheduleStatusEl, error.message, 'error');
            saveScheduleButton.disabled = false;
        }
    }

    async function loadPriceChart() {
        try {
            var data = await fetchJson('/schedule/prices');
            if (data.prices) {
                renderPriceChart(data.prices, priceThreshold.value);
            }
        } catch (_) {
            priceChartWrap.hidden = true;
        }
    }

    function getFilteredBrowserEntries() {
        const filterValue = String(state.browser.filterQuery || '').trim().toLowerCase();
        if (!filterValue) {
            return state.browser.entries.map(function (entry, index) {
                return {
                    entry: entry,
                    originalIndex: index,
                };
            });
        }

        return state.browser.entries.reduce(function (matches, entry, index) {
            if (entry.name.toLowerCase().indexOf(filterValue) !== -1
                || entry.path.toLowerCase().indexOf(filterValue) !== -1) {
                matches.push({
                    entry: entry,
                    originalIndex: index,
                });
            }
            return matches;
        }, []);
    }

    function selectBrowserPath(path) {
        if (state.browser.target === 'input_file') {
            setInputSelection(path, 'file');
            setFormStatus(i18n.t('toast.source_file_selected'), 'ok');
        } else if (state.browser.target === 'input_directory') {
            if (browserRecursiveField) inputRecursiveField.checked = browserRecursiveField.checked;
            setInputSelection(path, 'directory');
            setFormStatus(i18n.t('toast.source_folder_selected'), 'ok');
        } else if (state.browser.target === 'allowed_root') {
            addAllowedRoot(path);
        } else if (state.browser.target === 'watcher_directory') {
            setWatcherDirectory(path);
            setStatus(watcherStatus, i18n.t('toast.watcher_source_selected'), 'ok');
        } else if (state.browser.target === 'watcher_output_directory') {
            setWatcherOutputDir(path);
            setStatus(watcherStatus, i18n.t('toast.watcher_output_selected'), 'ok');
        } else if (state.browser.target === 'output_directory') {
            outputDirField.value = path;
            outputDirField.dispatchEvent(new Event('change', { bubbles: true }));
            setFormStatus(i18n.t('toast.dest_folder_selected'), 'ok');
        } else if (state.browser.target === 'default_output_directory') {
            defaultOutputDirField.value = path;
            defaultOutputDirField.dispatchEvent(new Event('change', { bubbles: true }));
            setStatus(settingsStatus, i18n.t('toast.default_dest_selected'), 'ok');
        }
        closePathBrowser();
    }

    function getActiveBrowserEntry(entries) {
        if (!entries.length) {
            state.browser.activeEntryIndex = -1;
            return null;
        }

        const activeMatch = entries.find(function (item) {
            return item.originalIndex === state.browser.activeEntryIndex;
        });

        if (activeMatch) {
            return activeMatch;
        }

        state.browser.activeEntryIndex = entries[0].originalIndex;
        return entries[0];
    }

    function scrollActiveBrowserEntryIntoView() {
        const activeEntry = browserList.querySelector('.browser-row-active');
        if (!activeEntry) {
            return;
        }
        activeEntry.scrollIntoView({ block: 'nearest' });
    }

    function moveBrowserSelection(offset) {
        const entries = getFilteredBrowserEntries();
        if (!entries.length) {
            state.browser.activeEntryIndex = -1;
            return;
        }

        const currentPosition = entries.findIndex(function (item) {
            return item.originalIndex === state.browser.activeEntryIndex;
        });
        const startPosition = currentPosition === -1
            ? (offset > 0 ? 0 : entries.length - 1)
            : currentPosition + offset;
        const nextPosition = Math.max(0, Math.min(entries.length - 1, startPosition));

        state.browser.activeEntryIndex = entries[nextPosition].originalIndex;
        renderBrowserEntries();
        scrollActiveBrowserEntryIntoView();
    }

    function activateBrowserSelection() {
        const activeItem = getActiveBrowserEntry(getFilteredBrowserEntries());
        if (!activeItem) {
            return;
        }

        if (activeItem.entry.kind === 'directory') {
            loadBrowserPath(activeItem.entry.path, { resetFilter: true, focusFilter: true });
            return;
        }

        if (activeItem.entry.selectable) {
            selectBrowserPath(activeItem.entry.path);
        }
    }

    function renderBrowserEntries() {
        const entries = getFilteredBrowserEntries();
        const activeItem = getActiveBrowserEntry(entries);

        if (!state.browser.entries.length) {
            state.browser.activeEntryIndex = -1;
            browserList.innerHTML = '<tr><td colspan="2" class="empty">' + i18n.t('browser.no_items') + '</td></tr>';
            return;
        }

        if (!entries.length) {
            state.browser.activeEntryIndex = -1;
            browserList.innerHTML = '<tr><td colspan="2" class="empty">' + i18n.t('browser.no_entries') + '</td></tr>';
            return;
        }

        var folderIcon = '<svg class="browser-icon" viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>';
        var fileIcon = '<svg class="browser-icon" viewBox="0 0 24 24"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>';

        browserList.innerHTML = entries.map(function (item) {
            var entry = item.entry;
            var originalIndex = item.originalIndex;
            var isActive = activeItem && originalIndex === activeItem.originalIndex;
            var activeClass = isActive ? ' browser-row-active' : '';
            var icon = entry.kind === 'directory' ? folderIcon : fileIcon;

            return '<tr class="' + activeClass.trim() + '" data-entry-index="' + originalIndex + '">' +
                '<td>' + icon + '</td>' +
                '<td>' + escapeHtml(entry.name) + '</td>' +
                '</tr>';
        }).join('');

        Array.prototype.forEach.call(
            browserList.querySelectorAll('[data-entry-index]'),
            function (row) {
                row.addEventListener('click', function () {
                    var index = Number(row.dataset.entryIndex);
                    if (!Number.isFinite(index) || !state.browser.entries[index]) {
                        return;
                    }
                    state.browser.activeEntryIndex = index;
                    if (state.browser.entries[index].kind === 'directory') {
                        loadBrowserPath(state.browser.entries[index].path, { resetFilter: true, focusFilter: false });
                        return;
                    }
                    if (state.browser.entries[index].selectable) {
                        selectBrowserPath(state.browser.entries[index].path);
                    }
                });
            }
        );
    }

    function renderBrowser(payload) {
        state.browser.currentPath = payload.path || '';
        state.browser.entries = payload.entries || [];
        state.browser.roots = payload.roots || [];
        state.browser.parent = payload.parent || '';
        state.browser.showHidden = Boolean(payload.show_hidden);
        browserCurrentPath.value = payload.path || '';
        browserCurrentPath.setAttribute(
            'title',
            payload.path
                ? `Current source browser path: ${payload.path}`
                : 'Current folder in the source browser.'
        );
        browserFilter.value = state.browser.filterQuery;
        browserShowHidden.checked = state.browser.showHidden;
        browserUpButton.disabled = !payload.parent && !payload.path;
        browserSelectCurrentButton.hidden = state.browser.selection !== 'directory';
        renderBrowserRoots(payload.roots || []);
        renderBrowserEntries();
        setBrowserStatus('', '');
    }

    async function loadBrowserPath(path, options) {
        const effectiveOptions = options || {};
        const targetPath = path || '';

        if (effectiveOptions.resetFilter && targetPath !== state.browser.currentPath) {
            state.browser.filterQuery = '';
            browserFilter.value = '';
        }

        const requestPath = `/browse?selection=${encodeURIComponent(state.browser.selection)}&scope=${encodeURIComponent(state.browser.scope)}&show_hidden=${state.browser.showHidden ? '1' : '0'}&path=${encodeURIComponent(path || '')}`;
        browserUpButton.disabled = true;
        browserList.innerHTML = '<div class="empty">Loading...</div>';
        setBrowserStatus('Loading source directory...', '');

        try {
            const payload = await fetchJson(requestPath);
            renderBrowser(payload);
            if (effectiveOptions.focusFilter) {
                focusBrowserFilter();
            }
        } catch (error) {
            browserList.innerHTML = '';
            setBrowserStatus(error.message, 'error');
        }
    }

    function openPathBrowser(options) {
        state.browser.open = true;
        state.browser.target = options.target;
        state.browser.selection = options.selection;
        state.browser.scope = options.scope;
        state.browser.showHidden = false;
        state.browser.filterQuery = '';
        state.browser.currentPath = '';
        state.browser.entries = [];
        state.browser.roots = [];
        state.browser.parent = '';
        state.browser.activeEntryIndex = -1;

        browserEyebrow.textContent = options.eyebrow;
        browserTitle.textContent = options.title;
        browserEyebrow.setAttribute('title', options.title);
        browserTitle.setAttribute('title', options.title);
        browserCurrentPath.value = '';
        browserShowHidden.checked = false;
        browserList.innerHTML = '<div class="empty">Loading...</div>';
        if (browserRecursiveToggle) {
            browserRecursiveToggle.hidden = options.selection !== 'directory' || options.target !== 'input_directory';
            if (browserRecursiveField) browserRecursiveField.checked = inputRecursiveField.checked;
        }
        browserModal.hidden = false;
        document.body.classList.add('modal-open');
        loadBrowserPath(options.path || '', { resetFilter: true, focusFilter: true });
    }

    function renderMeta(summary) {
        const chips = [];
        const workerCount = Number(summary.worker_count || 1);

        chips.push(`<span class="chip">Workers: ${escapeHtml(String(workerCount))}</span>`);

        const schedStatus = summary.schedule_status || {};
        if (schedStatus.enabled) {
            const schedAllowed = schedStatus.allowed !== false;
            const schedClass = schedAllowed ? 'allowed' : 'blocked';
            const schedLabel = schedAllowed ? 'Allowed' : 'Blocked';
            const schedTip = schedStatus.reason || '';
            chips.push(`<span class="chip schedule-chip-${schedClass}" title="${escapeHtml(schedTip)}">${escapeHtml(schedLabel)}</span>`);
        }

        meta.innerHTML = chips.join('');
        renderReleaseControl(summary.update_info || {});

        if (sidebarVersion && state.release.local_version) {
            var vText = 'v' + state.release.local_version;
            var dot = state.release.update_available
                ? '<span class="sidebar-version-dot" title="' + escapeHtml(i18n.t('release.update_available_dot', { version: state.release.remote_version })) + '"></span>'
                : '';
            sidebarVersion.innerHTML = '<a href="#system/about:about-version-section">' + escapeHtml(vText) + dot + '</a>';
            sidebarVersion.querySelector('a').addEventListener('click', function (e) {
                if (getPageFromHash() === 'system/about') {
                    e.preventDefault();
                    window.location.hash = '#system/about:about-version-section';
                    var el = document.getElementById('about-version-section');
                    if (el) scrollAndHighlight(el);
                }
            });
        }
    }

    // ── Form dirty tracking ──
    // Tracks whether form fields have changed from their initial values.
    // Save/submit buttons start disabled and only enable when a change is detected.

    var dirtyTrackers = {};

    function formSnapshot(formEl) {
        var snap = {};
        var els = formEl.elements;
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            if (!el.name && !el.id) continue;
            var key = el.name || el.id;
            if (el.type === 'checkbox') {
                snap[key] = el.checked;
            } else if (el.type !== 'submit' && el.type !== 'button' && el.type !== 'hidden') {
                snap[key] = el.value;
            }
        }
        return snap;
    }

    function formSnapshotFromIds(ids) {
        var snap = {};
        ids.forEach(function (id) {
            var el = document.getElementById(id);
            if (!el) return;
            snap[id] = el.type === 'checkbox' ? el.checked : el.value;
        });
        return snap;
    }

    function isFormDirty(formEl, snapshot) {
        var els = formEl.elements;
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            if (!el.name && !el.id) continue;
            var key = el.name || el.id;
            if (!(key in snapshot)) continue;
            if (el.type === 'checkbox') {
                if (el.checked !== snapshot[key]) return true;
            } else if (el.type !== 'submit' && el.type !== 'button' && el.type !== 'hidden') {
                if (el.value !== snapshot[key]) return true;
            }
        }
        return false;
    }

    function isIdsDirty(ids, snapshot) {
        for (var i = 0; i < ids.length; i++) {
            var el = document.getElementById(ids[i]);
            if (!el) continue;
            var current = el.type === 'checkbox' ? el.checked : el.value;
            if (current !== snapshot[ids[i]]) return true;
        }
        return false;
    }

    function setupFormDirtyTracking(name, formEl, btnEl) {
        if (!formEl || !btnEl) return;
        var snap = formSnapshot(formEl);
        dirtyTrackers[name] = { form: formEl, btn: btnEl, snapshot: snap, type: 'form' };
        btnEl.disabled = true;
        function check() {
            var dirty = isFormDirty(formEl, dirtyTrackers[name].snapshot);
            btnEl.disabled = !dirty;
        }
        formEl.addEventListener('input', check);
        formEl.addEventListener('change', check);
    }

    function setupIdsDirtyTracking(name, ids, btnEl) {
        if (!btnEl) return;
        var snap = formSnapshotFromIds(ids);
        dirtyTrackers[name] = { ids: ids, btn: btnEl, snapshot: snap, type: 'ids' };
        btnEl.disabled = true;
        function check() {
            var dirty = isIdsDirty(ids, dirtyTrackers[name].snapshot);
            btnEl.disabled = !dirty;
        }
        ids.forEach(function (id) {
            var el = document.getElementById(id);
            if (el) {
                el.addEventListener('input', check);
                el.addEventListener('change', check);
            }
        });
    }

    function resetDirtyTracker(name) {
        var tracker = dirtyTrackers[name];
        if (!tracker) return;
        if (tracker.type === 'form') {
            tracker.snapshot = formSnapshot(tracker.form);
        } else {
            tracker.snapshot = formSnapshotFromIds(tracker.ids);
        }
        tracker.btn.disabled = true;
    }

    function refreshDirtyTracker(name) {
        var tracker = dirtyTrackers[name];
        if (!tracker) return;
        if (tracker.type === 'form') {
            tracker.snapshot = formSnapshot(tracker.form);
        } else {
            tracker.snapshot = formSnapshotFromIds(tracker.ids);
        }
        tracker.btn.disabled = true;
    }

    function applySummaryToForms(summary) {
        const defaults = summary.default_job_settings || {};
        state.defaultJobSettings = defaults;
        setAllowedRoots(summary.allowed_roots || []);
        settingsForm.elements.worker_count.value = String(summary.worker_count || 1);
        settingsForm.elements.gpu_devices.value = Array.isArray(summary.gpu_devices) ? summary.gpu_devices.join(',') : '';
        settingsForm.elements.default_output_dir.value = defaults.output_dir || '';
        settingsForm.elements.default_codec.value = defaults.codec || 'nvenc_h265';
        settingsForm.elements.default_encode_speed.value = defaults.encode_speed || 'normal';
        settingsForm.elements.default_audio_passthrough.checked = Boolean(defaults.audio_passthrough);
        settingsForm.elements.default_delete_source.checked = Boolean(defaults.delete_source);
        settingsForm.elements.default_force.checked = Boolean(defaults.force);
        settingsForm.elements.default_verbose.checked = Boolean(defaults.verbose);

        // Default preset
        var defPresetSel = document.getElementById('settings-default-preset');
        if (defPresetSel) {
            var wantedVal = defaults.default_preset_id || '';
            // Store wanted value so populatePresetSelects can restore it
            // even if preset options have not been loaded yet
            defPresetSel.dataset.wantedValue = wantedVal;
            // If the value is an official preset, enable show-all and load official presets
            if (wantedVal.startsWith('official:')) {
                defPresetSel.dataset.showAllPresets = 'true';
                // Also sync the checkbox
                var cb = document.querySelector('.show-all-presets-toggle input[data-target="settings-default-preset"]');
                if (cb) cb.checked = true;
                if (!presetsState.loadedOfficial) {
                    refreshOfficialPresets(false).then(function () {
                        populatePresetSelects(presetsState.quickAccess || []);
                        defPresetSel.value = wantedVal;
                    });
                } else {
                    populatePresetSelects(presetsState.quickAccess || []);
                }
            }
            defPresetSel.value = wantedVal;
            if (window._clutchToggleSettingsCodecSpeedRows) window._clutchToggleSettingsCodecSpeedRows(!wantedVal);
        }
        watcherForm.elements.delete_source.checked = Boolean(defaults.delete_source);

        // Log settings
        var logLevelEl = document.getElementById('settings-log-level');
        var logRetentionEl = document.getElementById('settings-log-retention');
        if (logLevelEl) logLevelEl.value = summary.log_level || 'INFO';
        if (logRetentionEl) logRetentionEl.value = String(summary.log_retention_days || 30);

        // General settings
        var authEnabledEl = document.getElementById('general-auth-enabled');
        if (authEnabledEl) authEnabledEl.checked = Boolean(summary.auth_enabled);

        var listenPortEl = document.getElementById('general-listen-port');
        if (listenPortEl) listenPortEl.value = String(summary.listen_port || 8765);

        var dateFormatEl = document.getElementById('general-date-format');
        if (dateFormatEl && summary.default_date_format) dateFormatEl.value = summary.default_date_format;
        state.dateFormat = summary.default_date_format || 'YYYY-MM-DD';

        var timezoneEl = document.getElementById('general-timezone');
        if (timezoneEl) timezoneEl.value = summary.display_timezone || '';
        state.displayTimezone = summary.display_timezone || '';
        populateTimezoneDatalist();

        // Upload settings
        var uploadDirEl = document.getElementById('general-upload-dir');
        if (uploadDirEl) uploadDirEl.value = summary.upload_dir || '';
        var maxUploadEl = document.getElementById('general-max-upload-size');
        if (maxUploadEl) maxUploadEl.value = summary.max_upload_size_bytes ? Math.round(summary.max_upload_size_bytes / (1024 * 1024)) : 0;
        // Show/hide upload section based on whether upload is configured
        var uploadSection = document.getElementById('upload-section');
        if (uploadSection) uploadSection.hidden = !summary.upload_dir;

        populateBiddingZones(summary.bidding_zones || []);
        applyScheduleToForm(summary.schedule_config, summary.schedule_status);
        syncAllCustomSelects();

        // Binary paths
        applyBinaryPaths(summary.binary_paths || {});
        updateMissingBinariesBanner(summary.missing_binaries || []);

        // Reset dirty trackers after server values are applied
        refreshDirtyTracker('settings-form');
        refreshDirtyTracker('log-settings');
        refreshDirtyTracker('general-settings');
        refreshDirtyTracker('schedule');
    }

    function renderWatchers(watchers) {
        if (!watchers.length) {
            watchersContainer.innerHTML = '<div class="empty">' + i18n.t('watchers.no_watchers') + '</div>';
            return;
        }

        var rows = watchers.map(function (watcher) {
            var overrides = [];
            if (watcher.output_dir) overrides.push(i18n.t('watchers.override_output', {value: escapeHtml(watcher.output_dir)}));
            if (watcher.codec) overrides.push(i18n.t('watchers.override_codec', {value: escapeHtml(watcher.codec)}));
            if (watcher.encode_speed) overrides.push(i18n.t('watchers.override_speed', {value: escapeHtml(watcher.encode_speed)}));
            if (watcher.audio_passthrough === true) overrides.push(i18n.t('watchers.override_audio'));
            if (watcher.force === true) overrides.push(i18n.t('watchers.override_force'));
            var overridesCell = overrides.length
                ? `<span class="watcher-overrides">${overrides.join(' | ')}</span>`
                : '<span class="watcher-details">—</span>';
            var isEditing = Boolean(state.editingWatcherId);
            var disabledAttr = isEditing ? ' disabled' : '';
            return `<tr>
                        <td><span class="watcher-dir" title="${escapeHtml(watcher.directory)}">${escapeHtml(watcher.directory)}</span></td>
                        <td class="watcher-details">${escapeHtml(i18n.t('watchers.detail_line', {recursive: String(watcher.recursive), poll: String(watcher.poll_interval), settle: String(watcher.settle_time), delete_src: String(Boolean(watcher.delete_source))}))}</td>
                        <td>${overridesCell}</td>
                        <td class="watcher-actions">
                            <button class="inline-button-warn" type="button" data-edit-watcher="${watcher.id}" title="${escapeHtml(i18n.t('watchers.edit_title'))}"${disabledAttr}>${i18n.t('common.edit')}</button>
                            <button class="inline-button" type="button" data-remove-watcher="${watcher.id}" title="${escapeHtml(i18n.t('watchers.remove_title'))}"${disabledAttr}>${i18n.t('common.remove')}</button>
                        </td>
                    </tr>`;
        }).join('');

        watchersContainer.innerHTML =
            '<div class="watcher-section-header">' + i18n.t('watchers.section_header') + '</div>' +
            '<table class="watcher-table"><thead><tr><th>' + i18n.t('watchers.col_directory') + '</th><th>' + i18n.t('watchers.col_settings') + '</th><th>' + i18n.t('watchers.col_overrides') + '</th><th></th></tr></thead><tbody>' +
            rows + '</tbody></table>';

        Array.prototype.forEach.call(
            watchersContainer.querySelectorAll('[data-edit-watcher]'),
            function (button) {
                button.addEventListener('click', function () {
                    var watcher = watchers.find(function (w) { return w.id === button.dataset.editWatcher; });
                    if (!watcher) return;
                    state.editingWatcherId = watcher.id;
                    setWatcherDirectory(watcher.directory);
                    watcherForm.elements.poll_interval.value = String(watcher.poll_interval);
                    watcherForm.elements.settle_time.value = String(watcher.settle_time);
                    watcherForm.elements.recursive.checked = Boolean(watcher.recursive);
                    watcherForm.elements.delete_source.checked = Boolean(watcher.delete_source);
                    setWatcherOutputDir(watcher.output_dir || '');
                    watcherForm.elements.codec.value = watcher.codec || '';
                    watcherForm.elements.encode_speed.value = watcher.encode_speed || '';
                    if (watcherForm.elements.preset_id) {
                        watcherForm.elements.preset_id.value = watcher.preset_id || '';
                        watcherForm.elements.preset_id.dispatchEvent(new Event('change'));
                    }
                    watcherForm.elements.audio_passthrough.checked = Boolean(watcher.audio_passthrough);
                    watcherForm.elements.force.checked = Boolean(watcher.force);
                    syncAllCustomSelects();
                    watcherButton.textContent = i18n.t('watchers.update_watcher');
                    cancelEditWatcherButton.hidden = false;
                    scrollAndHighlight(watcherForm);
                    // Disable all Edit/Remove buttons while editing
                    Array.prototype.forEach.call(
                        watchersContainer.querySelectorAll('[data-edit-watcher], [data-remove-watcher]'),
                        function (btn) { btn.disabled = true; }
                    );
                });
            }
        );

        Array.prototype.forEach.call(
            watchersContainer.querySelectorAll('[data-remove-watcher]'),
            function (button) {
                button.addEventListener('click', async function () {
                    var watcher = watchers.find(function (w) { return w.id === button.dataset.removeWatcher; });
                    var dirName = watcher ? watcher.directory : 'this watcher';
                    var confirmed = await showConfirm({
                        title: i18n.t('confirm.remove_watcher_title'),
                        message: i18n.t('confirm.remove_watcher_message', { directory: dirName }),
                        ok: i18n.t('confirm.remove_watcher_ok'),
                    });
                    if (!confirmed) return;
                    button.disabled = true;
                    try {
                        await fetchJson(`/watchers/${button.dataset.removeWatcher}`, { method: 'DELETE' });
                        setStatus(watcherStatus, i18n.t('toast.watcher_removed'), 'ok');
                        await refreshSummary();
                    } catch (error) {
                        setStatus(watcherStatus, error.message, 'error');
                        button.disabled = false;
                    }
                });
            }
        );
    }

    function sortJobs(jobs) {
        var col = state.jobSortColumn || 'default';
        var asc = state.jobSortAsc;

        if (col === 'default') {
            return defaultSortJobs(jobs);
        }

        return jobs.slice().sort(function (a, b) {
            var va, vb;
            if (col === 'name') {
                va = basename(a.input_file).toLowerCase();
                vb = basename(b.input_file).toLowerCase();
            } else if (col === 'status') {
                va = a.status;
                vb = b.status;
            } else if (col === 'progress') {
                va = Number(a.progress_percent || 0);
                vb = Number(b.progress_percent || 0);
                return asc ? va - vb : vb - va;
            } else if (col === 'codec') {
                va = resolvePresetLabel(a);
                vb = resolvePresetLabel(b);
            } else if (col === 'size') {
                va = Number(a.input_size_bytes || 0);
                vb = Number(b.input_size_bytes || 0);
                return asc ? va - vb : vb - va;
            } else if (col === 'eta') {
                va = extractEtaLabel(a.message) || '\uffff';
                vb = extractEtaLabel(b.message) || '\uffff';
            } else if (col === 'submitted') {
                va = a.submitted_at || '';
                vb = b.submitted_at || '';
            } else {
                return 0;
            }
            var cmp = String(va).localeCompare(String(vb));
            return asc ? cmp : -cmp;
        });
    }

    function defaultSortJobs(jobs) {
        return jobs.slice().sort(function (left, right) {
            const leftRank = Object.prototype.hasOwnProperty.call(statusPriority, left.status)
                ? statusPriority[left.status]
                : 99;
            const rightRank = Object.prototype.hasOwnProperty.call(statusPriority, right.status)
                ? statusPriority[right.status]
                : 99;

            if (leftRank !== rightRank) {
                return leftRank - rightRank;
            }

            var activeStatuses = { running: 1, paused: 1, cancelling: 1, queued: 1 };
            if (Object.prototype.hasOwnProperty.call(activeStatuses, left.status)) {
                var leftPri = left.priority || 0;
                var rightPri = right.priority || 0;
                if (left.status === 'queued' && right.status === 'queued' && leftPri !== rightPri) {
                    return rightPri - leftPri;
                }
                const leftTime = String(left.submitted_at || '');
                const rightTime = String(right.submitted_at || '');
                return leftTime.localeCompare(rightTime);
            }

            const leftTime = String(left.finished_at || left.submitted_at || '');
            const rightTime = String(right.finished_at || right.submitted_at || '');
            return rightTime.localeCompare(leftTime);
        });
    }

    function filterJobs(jobs) {
        var text = jobsFilterText.value.trim().toLowerCase();
        var status = jobsFilterStatus.value;
        return jobs.filter(function (job) {
            if (status && job.status !== status) return false;
            if (text && basename(job.input_file).toLowerCase().indexOf(text) === -1) return false;
            return true;
        });
    }

    function shouldShowJobOpen(job) {
        if (Object.prototype.hasOwnProperty.call(state.expandedJobs, job.id)) {
            return Boolean(state.expandedJobs[job.id]);
        }
        return false;
    }

    function persistExpandedJobs() {
        try { window.localStorage.setItem(expandedJobsStorageKey, JSON.stringify(state.expandedJobs)); } catch (e) { /* noop */ }
    }

    function pruneExpandedJobs(jobs) {
        const nextExpanded = {};

        jobs.forEach(function (job) {
            if (Object.prototype.hasOwnProperty.call(state.expandedJobs, job.id)) {
                nextExpanded[job.id] = state.expandedJobs[job.id];
            }
        });

        state.expandedJobs = nextExpanded;
        persistExpandedJobs();
    }

    function ensureActiveQueueJob(jobs) {
        state.queueJobIds = jobs.map(function (job) {
            return job.id;
        });

        if (!state.queueJobIds.length) {
            state.activeQueueJobId = '';
            return;
        }

        if (state.queueJobIds.indexOf(state.activeQueueJobId) === -1) {
            state.activeQueueJobId = state.queueJobIds[0];
        }
    }

    function updateActiveQueueSelection() {
        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('.jt-row'),
            function (row) {
                const isActive = row.dataset.jobId === state.activeQueueJobId;
                row.classList.toggle('jt-row-active', isActive);
                row.setAttribute('aria-selected', isActive ? 'true' : 'false');
            }
        );
    }

    function scrollActiveQueueJobIntoView() {
        const activeRow = jobsContainer.querySelector('.jt-row-active');
        if (!activeRow) {
            return;
        }
        activeRow.scrollIntoView({ block: 'nearest' });
    }

    function moveQueueSelection(offset) {
        if (!state.queueJobIds.length) {
            state.activeQueueJobId = '';
            return;
        }

        const currentIndex = state.queueJobIds.indexOf(state.activeQueueJobId);
        const baseIndex = currentIndex === -1
            ? (offset > 0 ? 0 : state.queueJobIds.length - 1)
            : currentIndex + offset;
        const nextIndex = Math.max(0, Math.min(state.queueJobIds.length - 1, baseIndex));

        state.activeQueueJobId = state.queueJobIds[nextIndex];
        updateActiveQueueSelection();
        scrollActiveQueueJobIntoView();
    }

    function toggleActiveQueueJob() {
        if (!state.activeQueueJobId) {
            return;
        }
        var detailRow = jobsContainer.querySelector('[data-detail-for="' + state.activeQueueJobId + '"]');
        if (!detailRow) {
            return;
        }
        var isOpen = !detailRow.classList.contains('jt-detail-hidden');
        detailRow.classList.toggle('jt-detail-hidden', isOpen);
        state.expandedJobs[state.activeQueueJobId] = !isOpen;
        persistExpandedJobs();
        updateToggleExpandButton();
    }

    function updateJobsCount(filtered, total) {
        if (!total) {
            jobsCount.textContent = '';
        } else if (filtered === total) {
            jobsCount.textContent = i18n.t('activity.jobs_total', { total: total });
        } else {
            jobsCount.textContent = i18n.t('activity.jobs_filtered', { filtered: filtered, total: total });
        }
    }

    function updateToggleExpandButton() {
        var details = jobsContainer.querySelectorAll('.jt-detail-row');
        var anyOpen = false;
        Array.prototype.forEach.call(details, function (row) {
            if (!row.classList.contains('jt-detail-hidden')) anyOpen = true;
        });
        toggleExpandJobsButton.textContent = anyOpen ? i18n.t('activity.collapse_all') : i18n.t('activity.expand_all');
    }

    function buildSortIndicator(col) {
        if (state.jobSortColumn !== col) return '';
        return state.jobSortAsc ? ' ▲' : ' ▼';
    }

    // ── Bulk selection helpers ──

    function pruneSelectedJobs(visibleIds) {
        // Remove selections that are no longer in the visible set
        var validIds = new Set(visibleIds);
        state.selectedJobs.forEach(function (id) {
            if (!validIds.has(id)) state.selectedJobs.delete(id);
        });
    }

    function updateBulkActionsBar() {
        var count = state.selectedJobs.size;
        if (bulkActionsBar) {
            bulkActionsBar.style.visibility = count === 0 ? 'hidden' : 'visible';
            bulkActionsCount.textContent = i18n.t('activity.bulk_count', { count: count });
        }
        // Update select-all checkbox state
        var selectAllCb = jobsContainer.querySelector('#jt-select-all');
        if (selectAllCb) {
            var visibleRows = jobsContainer.querySelectorAll('.jt-row[data-job-id]');
            var visibleCount = visibleRows.length;
            var selectedVisible = 0;
            visibleRows.forEach(function (row) {
                if (state.selectedJobs.has(row.dataset.jobId)) selectedVisible++;
            });
            selectAllCb.checked = visibleCount > 0 && selectedVisible === visibleCount;
            selectAllCb.indeterminate = selectedVisible > 0 && selectedVisible < visibleCount;
        }
    }

    function toggleJobSelection(jobId, selected) {
        if (selected) {
            state.selectedJobs.add(jobId);
        } else {
            state.selectedJobs.delete(jobId);
        }
        updateBulkActionsBar();
    }

    function selectAllVisibleJobs(checked) {
        var visibleRows = jobsContainer.querySelectorAll('.jt-row[data-job-id]');
        visibleRows.forEach(function (row) {
            var jobId = row.dataset.jobId;
            if (checked) {
                state.selectedJobs.add(jobId);
            } else {
                state.selectedJobs.delete(jobId);
            }
            var cb = row.querySelector('.jt-select-cb');
            if (cb) cb.checked = checked;
        });
        updateBulkActionsBar();
    }

    async function bulkAction(action) {
        var ids = Array.from(state.selectedJobs);
        if (!ids.length) return;

        var actionKey = { cancel: 'confirm.bulk_cancel_label', retry: 'confirm.bulk_retry_label', clear: 'confirm.bulk_clear_label' }[action];
        var actionLabel = actionKey ? i18n.t(actionKey) : action;
        var confirmed = await showConfirm({
            title: i18n.t('confirm.bulk_action_title', { action: actionLabel, count: ids.length }),
            message: i18n.t('confirm.bulk_action_message', { action: actionLabel, count: ids.length }),
            ok: actionLabel,
        });
        if (!confirmed) return;

        var succeeded = 0;
        var failed = 0;
        for (var i = 0; i < ids.length; i++) {
            try {
                if (action === 'cancel') {
                    await fetchJson('/jobs/' + ids[i], { method: 'DELETE' });
                } else if (action === 'retry') {
                    await fetchJson('/jobs/' + ids[i] + '/retry', { method: 'POST' });
                } else if (action === 'clear') {
                    await fetchJson('/jobs/' + ids[i] + '?purge=1', { method: 'DELETE' });
                }
                succeeded++;
            } catch (e) {
                failed++;
            }
        }

        state.selectedJobs.clear();
        updateBulkActionsBar();
        var msg = failed
            ? i18n.t('confirm.bulk_result_partial', { action: actionLabel, succeeded: succeeded, failed: failed })
            : i18n.t('confirm.bulk_result', { action: actionLabel, succeeded: succeeded });
        setFormStatus(msg, failed ? 'error' : 'ok');
        await refreshJobs();
    }

    function renderJobs(jobs) {
        state.lastJobs = jobs.slice();
        var filtered = filterJobs(jobs);
        updateJobsCount(filtered.length, jobs.length);
        if (!filtered.length) {
            state.expandedJobs = {};
            persistExpandedJobs();
            state.activeQueueJobId = '';
            state.queueJobIds = [];
            state.selectedJobs.clear();
            updateBulkActionsBar();
            jobsContainer.innerHTML = jobs.length
                ? '<div class="empty">' + i18n.t('activity.no_jobs_filter') + '</div>'
                : '<div class="empty">' + i18n.t('activity.no_jobs_yet') + '</div>';
            updateToggleExpandButton();
            return;
        }

        pruneExpandedJobs(filtered);

        const sortedJobs = sortJobs(filtered);
        // Prune selections to only visible job IDs
        pruneSelectedJobs(sortedJobs.map(function (j) { return j.id; }));
        ensureActiveQueueJob(sortedJobs);

        var headerCols = [
            { key: 'name', label: i18n.t('table.name') },
            { key: 'status', label: i18n.t('table.status') },
            { key: 'progress', label: i18n.t('table.progress') },
            { key: 'codec', label: i18n.t('table.codec') },
            { key: 'size', label: i18n.t('table.size') },
            { key: 'eta', label: i18n.t('table.eta') },
            { key: 'submitted', label: i18n.t('table.submitted') },
        ];

        var thead = '<thead><tr>'
            + '<th class="jt-select-cell"><input type="checkbox" id="jt-select-all" title="' + escapeHtml(i18n.t('activity.select_all')) + '"></th>'
            + headerCols.map(function (c) {
            var cls = state.jobSortColumn === c.key ? ' class="jt-sorted"' : '';
            return '<th' + cls + ' data-sort-col="' + c.key + '">' + c.label + buildSortIndicator(c.key) + '</th>';
        }).join('') + '<th></th></tr></thead>';

        var rows = sortedJobs.map(function (job) {
            const rawProgress = Number(job.progress_percent == null ? 0 : job.progress_percent);
            const progress = Number.isFinite(rawProgress) ? Math.max(0, Math.min(rawProgress, 100)) : 0;
            const etaLabel = extractEtaLabel(job.message);
            let progressLabel = i18n.t('job_progress.done');

            if (job.status === 'queued') progressLabel = i18n.t('job_progress.waiting');
            else if (job.status === 'running') progressLabel = progress.toFixed(1) + '%';
            else if (job.status === 'paused') progressLabel = progress.toFixed(1) + '%';
            else if (job.status === 'cancelling') progressLabel = i18n.t('job_progress.cancelling');
            else if (job.status === 'failed') progressLabel = i18n.t('job_progress.failed');
            else if (job.status === 'cancelled') progressLabel = i18n.t('job_progress.cancelled');
            else if (job.status === 'skipped') progressLabel = i18n.t('job_progress.skipped');
            else if (progress > 0) progressLabel = progress.toFixed(1) + '%';

            const submitted = formatIsoTimestamp(job.submitted_at) || job.submitted_display || '';
            const isOpen = shouldShowJobOpen(job);
            const isActive = job.id === state.activeQueueJobId;
            const activeClass = isActive ? ' jt-row-active' : '';

            // Action buttons
            const pauseButton = job.status === 'running'
                ? '<button class="inline-button-warn" type="button" data-pause-id="' + job.id + '" title="' + escapeHtml(i18n.t('job_action.pause')) + '">' + i18n.t('job_action.pause') + '</button>'
                : job.status === 'paused'
                    ? '<button class="inline-button-warn" type="button" data-resume-id="' + job.id + '" title="' + escapeHtml(i18n.t('job_action.resume')) + '">' + i18n.t('job_action.resume') + '</button>'
                    : '';
            const cancelButton = (job.status === 'queued' || job.status === 'running' || job.status === 'paused')
                ? '<button class="inline-button" type="button" data-cancel-id="' + job.id + '" title="' + escapeHtml(i18n.t('job_action.cancel')) + '">' + i18n.t('job_action.cancel') + '</button>'
                : '';
            const moveNextButton = job.status === 'queued'
                ? '<button class="inline-button-warn" type="button" data-move-next-id="' + job.id + '" title="' + escapeHtml(i18n.t('job_action.convert_next')) + '">' + i18n.t('job_action.next') + '</button>'
                : '';
            const retryButton = (job.status === 'failed' || job.status === 'cancelled')
                ? '<button class="inline-button-warn" type="button" data-retry-id="' + job.id + '" title="' + escapeHtml(i18n.t('job_action.retry')) + '">' + i18n.t('job_action.retry') + '</button>'
                : '';
            const clearButton = (job.status !== 'running' && job.status !== 'paused' && job.status !== 'cancelling')
                ? '<button class="inline-button" type="button" data-clear-id="' + job.id + '" title="' + escapeHtml(i18n.t('job_action.clear_title')) + '">' + i18n.t('job_action.clear') + '</button>'
                : '';
            const downloadButton = (job.status === 'succeeded' && job.output_file)
                ? '<a class="inline-button inline-button-download" href="/download?path=' + encodeURIComponent(job.output_file) + (state.auth.token ? '&token=' + encodeURIComponent(state.auth.token) : '') + '" title="' + escapeHtml(i18n.t('job_action.download_title')) + '" download>' + i18n.t('job_action.download') + '</a>'
                : '';

            var actionBtns = [moveNextButton, pauseButton, cancelButton, retryButton, downloadButton, clearButton].filter(Boolean).join(' ');

            var isChecked = state.selectedJobs.has(job.id) ? ' checked' : '';

            var mainRow = '<tr class="jt-row' + activeClass + '" data-job-id="' + job.id + '">'
                + '<td class="jt-select-cell"><input type="checkbox" class="jt-select-cb" data-select-job="' + job.id + '"' + isChecked + '></td>'
                + '<td class="jt-name" title="' + escapeHtml(basename(job.input_file)) + '">' + escapeHtml(basename(job.input_file)) + '</td>'
                + '<td><span class="badge badge-sm ' + escapeHtml(job.status) + '">' + escapeHtml(i18n.t('job_status.' + job.status)) + '</span></td>'
                + '<td class="jt-progress"><div class="progress-track"><div class="progress-fill progress-fill-' + escapeHtml(job.status) + '" style="width:' + progress.toFixed(1) + '%"></div></div><span class="jt-progress-label">' + escapeHtml(progressLabel) + '</span></td>'
                + '<td class="jt-codec">' + escapeHtml(resolvePresetLabel(job)) + '</td>'
                + '<td class="jt-size">' + escapeHtml(formatBytes(job.input_size_bytes)) + '</td>'
                + '<td class="jt-eta">' + escapeHtml(etaLabel || '\u2014') + '</td>'
                + '<td class="jt-submitted">' + escapeHtml(submitted) + '</td>'
                + '<td class="jt-actions">' + actionBtns + '</td>'
                + '</tr>';

            // Detail row — two-column layout: source (left) / output (right)
            var elapsed = formatElapsed(job.started_at, job.finished_at);

            var srcCol = '<div class="jt-detail-col">'
                + '<div class="jt-detail-col-title">' + i18n.t('job_detail.source_title') + '</div>'
                + '<div class="job-detail"><div class="job-detail-label">' + i18n.t('job_detail.size_label') + '</div><div class="job-detail-value">' + escapeHtml(formatBytes(job.input_size_bytes)) + '</div></div>'
                + '<div class="job-detail"><div class="job-detail-label">' + i18n.t('job_detail.path_label') + '</div><div class="job-detail-value job-detail-code">' + escapeHtml(job.input_file) + '</div></div>'
                + renderMediaSection(i18n.t('job_detail.media_label'), job.input_media)
                + '</div>';

            var outCol = '<div class="jt-detail-col">'
                + '<div class="jt-detail-col-title">' + i18n.t('job_detail.output_title') + '</div>'
                + '<div class="job-detail"><div class="job-detail-label">' + i18n.t('job_detail.size_label') + '</div><div class="job-detail-value">' + escapeHtml(formatBytes(job.output_size_bytes)) + '</div></div>'
                + (job.output_file ? '<div class="job-detail"><div class="job-detail-label">' + i18n.t('job_detail.path_label') + '</div><div class="job-detail-value job-detail-code">' + escapeHtml(job.output_file) + '</div></div>' : '')
                + renderMediaSection(i18n.t('job_detail.media_label'), job.output_media)
                + '</div>';

            var footerDetails = '<div class="jt-detail-footer">'
                + '<div class="job-detail"><div class="job-detail-label">' + i18n.t('job_detail.profile_label') + '</div><div class="job-detail-value">' + escapeHtml(resolvePresetLabel(job)) + '</div></div>'
                + '<div class="job-detail"><div class="job-detail-label">' + i18n.t('job_detail.submitted_label') + '</div><div class="job-detail-value">' + escapeHtml(submitted) + '</div></div>'
                + '<div class="job-detail"><div class="job-detail-label">' + i18n.t('job_detail.compression_label') + '</div><div class="job-detail-value">' + escapeHtml(formatCompression(job.compression_percent)) + '</div></div>'
                + (elapsed ? '<div class="job-detail"><div class="job-detail-label">' + i18n.t('job_detail.duration_label') + '</div><div class="job-detail-value">' + escapeHtml(elapsed) + '</div></div>' : '')
                + '<div class="job-detail jt-detail-message"><div class="job-detail-label">' + i18n.t('job_detail.message_label') + '</div><div class="job-detail-value job-detail-code">' + escapeHtml(job.message || i18n.t('job_detail.no_message')) + '</div></div>'
                + '</div>';

            var detailRow = '<tr class="jt-detail-row' + (isOpen ? '' : ' jt-detail-hidden') + '" data-detail-for="' + job.id + '">'
                + '<td colspan="9"><div class="jt-detail-inner">'
                + '<div class="jt-detail-columns">' + srcCol + outCol + '</div>'
                + footerDetails
                + '</div></td></tr>';

            return mainRow + detailRow;
        }).join('');

        jobsContainer.innerHTML = '<table class="jobs-table"><colgroup>'
            + '<col class="jt-col-select">'
            + '<col class="jt-col-name"><col class="jt-col-status"><col class="jt-col-progress">'
            + '<col class="jt-col-codec"><col class="jt-col-size"><col class="jt-col-eta">'
            + '<col class="jt-col-submitted"><col class="jt-col-actions">'
            + '</colgroup>' + thead + '<tbody>' + rows + '</tbody></table>';

        // Sort header clicks
        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('[data-sort-col]'),
            function (th) {
                th.style.cursor = 'pointer';
                th.addEventListener('click', function () {
                    var col = th.dataset.sortCol;
                    if (state.jobSortColumn === col) {
                        state.jobSortAsc = !state.jobSortAsc;
                    } else {
                        state.jobSortColumn = col;
                        state.jobSortAsc = true;
                    }
                    renderJobs(state.lastJobs);
                });
            }
        );

        // Select-all checkbox
        var selectAllCb = jobsContainer.querySelector('#jt-select-all');
        if (selectAllCb) {
            selectAllCb.addEventListener('change', function () {
                selectAllVisibleJobs(selectAllCb.checked);
            });
        }

        // Individual row checkboxes
        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('.jt-select-cb'),
            function (cb) {
                cb.addEventListener('change', function () {
                    toggleJobSelection(cb.dataset.selectJob, cb.checked);
                });
            }
        );

        // Row click to toggle detail
        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('.jt-row'),
            function (row) {
                row.style.cursor = 'pointer';
                row.addEventListener('click', function (event) {
                    if (event.target && (event.target.closest('button') || event.target.closest('input[type="checkbox"]'))) return;
                    var jobId = row.dataset.jobId;
                    state.activeQueueJobId = jobId;
                    var detailRow = jobsContainer.querySelector('[data-detail-for="' + jobId + '"]');
                    if (detailRow) {
                        var isOpen = !detailRow.classList.contains('jt-detail-hidden');
                        detailRow.classList.toggle('jt-detail-hidden', isOpen);
                        state.expandedJobs[jobId] = !isOpen;
                        persistExpandedJobs();
                    }
                    updateActiveQueueSelection();
                    updateToggleExpandButton();
                });
            }
        );

        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('[data-pause-id]'),
            function (button) {
                button.addEventListener('click', async function () {
                    button.disabled = true;
                    button.textContent = i18n.t('job_action.pausing');
                    try {
                        const response = await fetchJson(`/jobs/${button.dataset.pauseId}/pause`, { method: 'POST' });
                        setFormStatus(response.message || i18n.t('toast.conversion_paused'), 'ok');
                        await refreshJobs();
                    } catch (error) {
                        setFormStatus(error.message, 'error');
                        button.disabled = false;
                        button.textContent = i18n.t('job_action.pause');
                    }
                });
            }
        );

        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('[data-resume-id]'),
            function (button) {
                button.addEventListener('click', async function () {
                    button.disabled = true;
                    button.textContent = i18n.t('job_action.resuming');
                    try {
                        const response = await fetchJson(`/jobs/${button.dataset.resumeId}/resume`, { method: 'POST' });
                        setFormStatus(response.message || i18n.t('toast.conversion_resumed'), 'ok');
                        await refreshJobs();
                    } catch (error) {
                        setFormStatus(error.message, 'error');
                        button.disabled = false;
                        button.textContent = i18n.t('job_action.resume');
                    }
                });
            }
        );

        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('[data-cancel-id]'),
            function (button) {
                button.addEventListener('click', async function () {
                    button.disabled = true;
                    button.textContent = i18n.t('job_action.cancelling');
                    try {
                        const response = await fetchJson(`/jobs/${button.dataset.cancelId}`, { method: 'DELETE' });
                        setFormStatus(response.message || i18n.t('toast.cancellation_requested'), 'ok');
                        await refreshJobs();
                    } catch (error) {
                        setFormStatus(error.message, 'error');
                        button.disabled = false;
                        button.textContent = i18n.t('job_action.cancel');
                    }
                });
            }
        );

        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('[data-clear-id]'),
            function (button) {
                button.addEventListener('click', async function () {
                    var confirmed = await showConfirm({ title: i18n.t('confirm.remove_job_title'), message: i18n.t('confirm.remove_job_message'), ok: i18n.t('confirm.remove_job_ok') });
                    if (!confirmed) return;
                    button.disabled = true;
                    try {
                        await fetchJson(`/jobs/${button.dataset.clearId}?purge=1`, { method: 'DELETE' });
                        setFormStatus(i18n.t('toast.job_removed'), 'ok');
                        await refreshJobs();
                    } catch (error) {
                        setFormStatus(error.message, 'error');
                        button.disabled = false;
                    }
                });
            }
        );

        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('[data-retry-id]'),
            function (button) {
                button.addEventListener('click', async function () {
                    button.disabled = true;
                    button.textContent = i18n.t('job_action.retrying');
                    try {
                        const response = await fetchJson(`/jobs/${button.dataset.retryId}/retry`, { method: 'POST' });
                        setFormStatus(response.message || i18n.t('toast.job_queued_retry'), 'ok');
                        await refreshJobs();
                    } catch (error) {
                        setFormStatus(error.message, 'error');
                        button.disabled = false;
                        button.textContent = i18n.t('job_action.retry');
                    }
                });
            }
        );

        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('[data-move-next-id]'),
            function (button) {
                button.addEventListener('click', async function () {
                    button.disabled = true;
                    button.textContent = i18n.t('job_action.moving');
                    try {
                        await fetchJson(`/jobs/${button.dataset.moveNextId}/move-next`, { method: 'POST' });
                        setFormStatus(i18n.t('toast.job_promoted'), 'ok');
                        await refreshJobs();
                    } catch (error) {
                        setFormStatus(error.message, 'error');
                        button.disabled = false;
                        button.textContent = i18n.t('job_action.convert_next');
                    }
                });
            }
        );

        updateActiveQueueSelection();
        updateToggleExpandButton();
        updateActivityBadge(sortedJobs);
        updateBulkActionsBar();
    }

    function updateActivityBadge(jobs) {
        var pending = jobs.filter(function (j) { return j.status === 'queued' || j.status === 'running' || j.status === 'paused'; }).length;
        if (navActivityBadge) {
            navActivityBadge.hidden = !pending;
            navActivityBadge.textContent = String(pending);
        }
    }

    // ── System Monitor ──

    var sysmonTimer = null;

    function formatBytesShort(bytes) {
        if (bytes == null || !Number.isFinite(bytes) || bytes <= 0) return '—';
        var units = ['B', 'KB', 'MB', 'GB', 'TB'];
        var i = 0;
        var v = bytes;
        while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
        return v.toFixed(i === 0 ? 0 : 1) + ' ' + units[i];
    }

    function pctBar(used, total, label) {
        var pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
        var cls = pct > 90 ? ' sysmon-bar-crit' : pct > 75 ? ' sysmon-bar-warn' : '';
        return '<div class="sysmon-metric">'
            + '<div class="sysmon-metric-head"><span>' + escapeHtml(label) + '</span><span>' + pct.toFixed(1) + '%</span></div>'
            + '<div class="sysmon-bar"><div class="sysmon-bar-fill' + cls + '" style="width:' + pct.toFixed(1) + '%"></div></div>'
            + '<div class="sysmon-metric-detail">' + formatBytesShort(used) + ' / ' + formatBytesShort(total) + '</div>'
            + '</div>';
    }

    function renderSysmon(data) {
        var sections = [];

        // CPU
        if (data.load != null || data.cpu_count) {
            var cpuHtml = '<div class="sysmon-section"><div class="sysmon-section-title">' + i18n.t('sysmon.cpu') + '</div>';
            if (data.cpu_count) cpuHtml += '<div class="sysmon-kv"><span class="sysmon-kv-label">' + i18n.t('sysmon.cores') + '</span><span>' + data.cpu_count + '</span></div>';
            if (data.load) cpuHtml += '<div class="sysmon-kv"><span class="sysmon-kv-label">' + i18n.t('sysmon.load_average') + '</span><span>' + data.load.join(' / ') + '</span></div>';
            if (data.cpu_temp != null) cpuHtml += '<div class="sysmon-kv"><span class="sysmon-kv-label">' + i18n.t('sysmon.temperature') + '</span><span>' + data.cpu_temp + ' °C</span></div>';
            cpuHtml += '</div>';
            sections.push(cpuHtml);
        }

        // Memory
        if (data.memory) {
            sections.push('<div class="sysmon-section"><div class="sysmon-section-title">' + i18n.t('sysmon.memory') + '</div>'
                + pctBar(data.memory.used, data.memory.total, i18n.t('sysmon.ram'))
                + '</div>');
        }

        // GPUs
        if (data.gpus && data.gpus.length) {
            var gpuHtml = '<div class="sysmon-section"><div class="sysmon-section-title">' + i18n.t('sysmon.gpu') + '</div>';
            data.gpus.forEach(function (gpu) {
                gpuHtml += '<div class="sysmon-gpu">';
                gpuHtml += '<div class="sysmon-kv"><span class="sysmon-kv-label">' + escapeHtml(gpu.name) + '</span></div>';
                if (gpu.mem_total_mib != null && gpu.mem_used_mib != null) {
                    gpuHtml += pctBar(gpu.mem_used_mib * 1048576, gpu.mem_total_mib * 1048576, i18n.t('sysmon.vram'));
                }
                var meta = [];
                if (gpu.utilization_pct != null) meta.push('Load ' + gpu.utilization_pct + '%');
                if (gpu.temp_c != null) meta.push(gpu.temp_c + ' °C');
                if (gpu.fan_pct != null) meta.push('Fan ' + gpu.fan_pct + '%');
                if (meta.length) gpuHtml += '<div class="sysmon-metric-detail">' + escapeHtml(meta.join(' · ')) + '</div>';
                gpuHtml += '</div>';
            });
            gpuHtml += '</div>';
            sections.push(gpuHtml);
        }

        // Disks
        if (data.disks && data.disks.length) {
            var diskHtml = '<div class="sysmon-section"><div class="sysmon-section-title">' + i18n.t('sysmon.disks') + '</div>';
            data.disks.forEach(function (d) {
                diskHtml += pctBar(d.used, d.total, d.mount)
                    + '<div class="sysmon-metric-detail">' + escapeHtml(d.device) + '</div>';
            });
            diskHtml += '</div>';
            sections.push(diskHtml);
        }

        sysmonContainer.innerHTML = sections.length
            ? '<div class="sysmon-grid">' + sections.join('') + '</div>'
            : '<div class="empty">No system data available.</div>';
    }

    async function refreshSysmon() {
        try {
            var data = await fetchJson('/system/stats');
            renderSysmon(data);
        } catch (_) {
            sysmonContainer.innerHTML = '<div class="empty">Failed to load system stats.</div>';
        }
    }

    function startSysmonPolling() {
        if (sysmonTimer) return;
        refreshSysmon();
        sysmonTimer = setInterval(refreshSysmon, 5000);
    }

    function stopSysmonPolling() {
        if (sysmonTimer) { clearInterval(sysmonTimer); sysmonTimer = null; }
    }

    /* ── Notifications ── */

    var notifList = document.getElementById('notif-channels-list');
    var notifEditor = document.getElementById('notif-editor');
    var notifEditorLegend = document.getElementById('notif-editor-legend');
    var notifForm = document.getElementById('notif-form');
    var notifStatus = document.getElementById('notif-status');
    var notifIdInput = document.getElementById('notif-id');
    var notifTypeInput = document.getElementById('notif-type');
    var notifNameInput = document.getElementById('notif-name');
    var notifEnabledInput = document.getElementById('notif-enabled');
    var notifTestBtn = document.getElementById('notif-test-btn');
    var notifCancelBtn = document.getElementById('notif-cancel-btn');
    var notifAddTelegram = document.getElementById('notif-add-telegram');
    var notifAddWebhook = document.getElementById('notif-add-webhook');

    function loadNotifChannels() {
        fetchJson('/config/notifications').then(function (data) {
            if (!data || !data.channels) return;
            renderNotifChannels(data.channels);
        });
    }

    function renderNotifChannels(channels) {
        if (!channels.length) {
            notifList.innerHTML = '<div class="empty">' + i18n.t('notif.no_channels') + '</div>';
            return;
        }
        notifList.innerHTML = '<table class="users-table">'
            + '<thead><tr><th>' + i18n.t('notif.col_type') + '</th><th>' + i18n.t('notif.col_name') + '</th><th>' + i18n.t('notif.col_events') + '</th><th>' + i18n.t('notif.col_status') + '</th><th></th></tr></thead>'
            + '<tbody>'
            + channels.map(function (ch) {
                var typeLabel = ch.type === 'telegram' ? '&#x2708; Telegram' : '&#x1F517; Webhook';
                var evts = (ch.events || []).map(function (e) { return e.replace('job_', ''); }).join(', ') || i18n.t('notif.events_none');
                var statusHtml = ch.enabled
                    ? '<span class="chip chip-ok">' + i18n.t('notif.enabled') + '</span>'
                    : '<span class="chip chip-muted">' + i18n.t('notif.disabled') + '</span>';
                return '<tr>'
                    + '<td>' + typeLabel + '</td>'
                    + '<td>' + escapeHtml(ch.name || '—') + '</td>'
                    + '<td>' + escapeHtml(evts) + '</td>'
                    + '<td>' + statusHtml + '</td>'
                    + '<td class="actions-cell">'
                    + '<button class="ghost notif-test-list-btn" data-id="' + ch.id + '" title="' + i18n.t('notif.test_tooltip') + '">' + i18n.t('notif.test') + '</button> '
                    + '<button class="ghost notif-edit-btn" data-id="' + ch.id + '" title="' + i18n.t('common.edit') + '">' + i18n.t('common.edit') + '</button> '
                    + '<button class="ghost danger-text notif-delete-btn" data-id="' + ch.id + '" title="' + i18n.t('common.delete') + '">' + i18n.t('common.delete') + '</button>'
                    + '</td>'
                    + '</tr>';
            }).join('')
            + '</tbody></table>';
    }

    notifList.addEventListener('click', function (e) {
        var btn = e.target.closest('.notif-test-list-btn');
        if (btn) { testNotifChannel(btn, btn.dataset.id); return; }
        btn = e.target.closest('.notif-edit-btn');
        if (btn) { editNotifChannel(btn.dataset.id); return; }
        btn = e.target.closest('.notif-delete-btn');
        if (btn) { deleteNotifChannel(btn.dataset.id); return; }
    });

    function openNotifEditor(type, channel) {
        notifEditor.hidden = false;
        scrollAndHighlight(notifEditor);
        notifForm.className = 'notif-form-' + type;
        notifTypeInput.value = type;
        notifIdInput.value = (channel && channel.id) || '';
        notifNameInput.value = (channel && channel.name) || '';
        notifEnabledInput.checked = channel ? channel.enabled : true;
        notifEditorLegend.textContent = channel ? i18n.t('notif.edit_channel') : i18n.t('notif.new_channel', { type: type.charAt(0).toUpperCase() + type.slice(1) });

        // Telegram fields
        var botTokenInput = document.getElementById('notif-bot-token');
        var chatIdInput = document.getElementById('notif-chat-id');
        botTokenInput.value = (channel && channel.config && channel.config.bot_token) || '';
        chatIdInput.value = (channel && channel.config && channel.config.chat_id) || '';

        // Webhook fields
        var urlInput = document.getElementById('notif-webhook-url');
        var headersInput = document.getElementById('notif-webhook-headers');
        urlInput.value = (channel && channel.config && channel.config.url) || '';
        var hdrs = (channel && channel.config && channel.config.headers) || {};
        headersInput.value = Object.keys(hdrs).length ? JSON.stringify(hdrs, null, 2) : '';

        // Events checkboxes
        var events = (channel && channel.events) || ['job_succeeded', 'job_failed'];
        notifForm.querySelectorAll('input[name="events"]').forEach(function (cb) {
            cb.checked = events.indexOf(cb.value) !== -1;
        });

        setStatus(notifStatus, '');
        notifTestBtn.style.display = channel ? '' : 'none';
        resetDirtyTracker('notif-form');
    }

    function closeNotifEditor() {
        notifEditor.hidden = true;
        notifForm.reset();
        resetDirtyTracker('notif-form');
    }

    function editNotifChannel(id) {
        fetchJson('/config/notifications').then(function (data) {
            if (!data || !data.channels) return;
            var ch = null;
            for (var i = 0; i < data.channels.length; i++) {
                if (data.channels[i].id === id) { ch = data.channels[i]; break; }
            }
            if (ch) openNotifEditor(ch.type, ch);
        });
    }

    function deleteNotifChannel(id) {
        showConfirm({ title: i18n.t('confirm.delete_channel_title'), message: i18n.t('confirm.delete_channel_message'), ok: i18n.t('confirm.delete_channel_ok') }).then(function (confirmed) {
            if (!confirmed) return;
            fetchJson('/config/notifications/' + id, { method: 'DELETE' }).then(function () {
                closeNotifEditor();
                loadNotifChannels();
            }).catch(function (err) {
                showAlert({ title: 'Error', message: err.message });
            });
        });
    }

    function testNotifChannel(triggerBtn, id) {
        var origText = triggerBtn.innerHTML;
        triggerBtn.disabled = true;
        triggerBtn.innerHTML = '&#x23F3;';
        fetchJson('/config/notifications/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: id }),
        }).then(function (result) {
            triggerBtn.innerHTML = result.ok ? '&#x2705;' : '&#x274C;';
            setTimeout(function () { triggerBtn.innerHTML = origText; triggerBtn.disabled = false; }, 2000);
        }).catch(function () {
            triggerBtn.innerHTML = '&#x274C;';
            setTimeout(function () { triggerBtn.innerHTML = origText; triggerBtn.disabled = false; }, 2000);
        });
    }

    notifAddTelegram.addEventListener('click', function () { openNotifEditor('telegram', null); });
    notifAddWebhook.addEventListener('click', function () { openNotifEditor('webhook', null); });
    notifCancelBtn.addEventListener('click', closeNotifEditor);

    notifForm.addEventListener('submit', function (e) {
        e.preventDefault();
        setStatus(notifStatus, i18n.t('toast.saving'));
        var type = notifTypeInput.value;
        var config = {};
        if (type === 'telegram') {
            config.bot_token = document.getElementById('notif-bot-token').value.trim();
            config.chat_id = document.getElementById('notif-chat-id').value.trim();
        } else {
            config.url = document.getElementById('notif-webhook-url').value.trim();
            var headersRaw = document.getElementById('notif-webhook-headers').value.trim();
            if (headersRaw) {
                try { config.headers = JSON.parse(headersRaw); } catch (_e) {
                    setStatus(notifStatus, i18n.t('toast.invalid_json_headers'), 'error');
                    return;
                }
            }
        }
        var events = [];
        notifForm.querySelectorAll('input[name="events"]:checked').forEach(function (cb) {
            events.push(cb.value);
        });
        var payload = {
            id: notifIdInput.value || undefined,
            type: type,
            name: notifNameInput.value.trim(),
            enabled: notifEnabledInput.checked,
            config: config,
            events: events,
        };
        fetchJson('/config/notifications', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function (result) {
            setStatus(notifStatus, i18n.t('toast.channel_saved'), 'ok');
            resetDirtyTracker('notif-form');
            notifIdInput.value = result.id || notifIdInput.value;
            notifTestBtn.style.display = '';
            loadNotifChannels();
        }).catch(function (err) {
            setStatus(notifStatus, err.message, 'error');
        });
    });

    notifTestBtn.addEventListener('click', function () {
        var id = notifIdInput.value;
        if (!id) { setStatus(notifStatus, i18n.t('toast.save_channel_first'), 'error'); return; }
        setStatus(notifStatus, i18n.t('toast.sending_test'));
        fetchJson('/config/notifications/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: id }),
        }).then(function (result) {
            setStatus(notifStatus, result.message || i18n.t('toast.test_sent'), result.ok ? 'ok' : 'error');
        }).catch(function (err) {
            setStatus(notifStatus, err.message, 'error');
        });
    });

    /* ── Log viewer ── */

    var logTabViewer = document.getElementById('log-tab-viewer');
    var logTabFiles = document.getElementById('log-tab-files');
    var logTabs = document.querySelectorAll('[data-log-tab]');
    var logFilesTableWrap = document.getElementById('log-files-table-wrap');
    var logFilesRefreshBtn = document.getElementById('log-files-refresh');
    var logFilesClearBtn = document.getElementById('log-files-clear');

    logTabs.forEach(function (tab) {
        tab.addEventListener('click', function () {
            logTabs.forEach(function (t) { t.classList.remove('active'); });
            tab.classList.add('active');
            var target = tab.dataset.logTab;
            if (target === 'viewer') {
                logTabViewer.removeAttribute('hidden');
                logTabViewer.style.display = '';
                logTabFiles.setAttribute('hidden', '');
                logTabFiles.style.display = 'none';
                loadLogFiles();
                loadLogs();
                startLogPolling();
            } else {
                stopLogPolling();
                logTabViewer.setAttribute('hidden', '');
                logTabViewer.style.display = 'none';
                logTabFiles.removeAttribute('hidden');
                logTabFiles.style.display = '';
                loadLogFilesTable();
            }
        });
    });

    function loadLogFilesTable() {
        fetchJson('/system/logs/files').then(function (data) {
            if (!data || !data.files) return;
            renderLogFilesTable(data.files);
        });
    }

    function renderLogFilesTable(files) {
        if (!files.length) {
            logFilesTableWrap.innerHTML = '<div class="empty">' + i18n.t('system.logs.no_files') + '</div>';
            return;
        }
        var html = '<table class="log-files-table">'
            + '<thead><tr><th>' + i18n.t('system.logs.col_filename') + '</th><th>' + i18n.t('system.logs.col_size') + '</th><th>' + i18n.t('system.logs.col_modified') + '</th><th></th></tr></thead>'
            + '<tbody>';
        files.forEach(function (f) {
            var mod = f.modified ? formatIsoTimestamp(f.modified) : '–';
            var size = formatBytes(f.size || 0);
            var isActive = f.name === 'clutch.log';
            var downloadUrl = '/system/logs/download?file=' + encodeURIComponent(f.name);
            if (state.auth.token) downloadUrl += '&token=' + encodeURIComponent(state.auth.token);
            var actions = '<a href="' + downloadUrl + '" class="ghost" download>' + i18n.t('system.logs.download') + '</a>';
            if (!isActive) {
                actions += ' <button class="ghost danger-text" data-delete-logfile="' + escapeHtml(f.name) + '">' + i18n.t('system.logs.delete') + '</button>';
            }
            html += '<tr>'
                + '<td>' + escapeHtml(f.name) + (isActive ? ' <span class="chip">' + i18n.t('system.logs.active_chip') + '</span>' : '') + '</td>'
                + '<td>' + size + '</td>'
                + '<td>' + mod + '</td>'
                + '<td class="actions-cell">' + actions + '</td>'
                + '</tr>';
        });
        html += '</tbody></table>';
        logFilesTableWrap.innerHTML = html;
    }

    if (logFilesTableWrap) {
        logFilesTableWrap.addEventListener('click', function (e) {
            var btn = e.target.closest('[data-delete-logfile]');
            if (!btn) return;
            var name = btn.dataset.deleteLogfile;
            showConfirm({ title: i18n.t('confirm.delete_log_file_title'), message: i18n.t('confirm.delete_log_file_message', { name: name }), ok: i18n.t('confirm.delete_log_file_ok') }).then(function (confirmed) {
                if (!confirmed) return;
                fetchJson('/system/logs/files?file=' + encodeURIComponent(name), { method: 'DELETE' }).then(function () {
                    loadLogFilesTable();
                });
            });
        });
    }

    if (logFilesRefreshBtn) {
        logFilesRefreshBtn.addEventListener('click', function () { loadLogFilesTable(); });
    }

    if (logFilesClearBtn) {
        logFilesClearBtn.addEventListener('click', function () {
            showConfirm({ title: i18n.t('confirm.clear_log_files_title'), message: i18n.t('confirm.clear_log_files_message'), ok: i18n.t('confirm.clear_log_files_ok') }).then(function (confirmed) {
                if (!confirmed) return;
                fetchJson('/system/logs/files', { method: 'DELETE' }).then(function () {
                    loadLogFilesTable();
                });
            });
        });
    }

    var logLevelFilter = document.getElementById('log-level-filter');
    var logSearch = document.getElementById('log-search');
    var logFileSelect = document.getElementById('log-file-select');
    var logRefreshBtn = document.getElementById('log-refresh');
    var logAutoRefresh = document.getElementById('log-auto-refresh');
    var logEntriesEl = document.getElementById('log-entries');
    var logPagination = document.getElementById('log-pagination');
    var logStaleWarning = document.getElementById('log-stale-warning');
    var logTimer = null;
    var logCurrentPage = 1;
    var logPageSize = 200;

    function loadLogFiles() {
        fetchJson('/system/logs/files').then(function (data) {
            if (!data || !data.files) return;
            var oldVal = logFileSelect.value;
            logFileSelect.innerHTML = '<option value="">Current</option>';
            data.files.forEach(function (f) {
                if (f.name === 'clutch.log') return;
                var opt = document.createElement('option');
                opt.value = f.name;
                opt.textContent = f.name.replace('clutch.log.', '');
                logFileSelect.appendChild(opt);
            });
            if (oldVal) logFileSelect.value = oldVal;
        });
    }

    function loadLogs(page) {
        if (page !== undefined) logCurrentPage = page;
        var params = '?page=' + logCurrentPage + '&limit=' + logPageSize;
        if (logLevelFilter.value) params += '&level=' + encodeURIComponent(logLevelFilter.value);
        if (logSearch.value.trim()) params += '&search=' + encodeURIComponent(logSearch.value.trim());
        if (logFileSelect.value) params += '&file=' + encodeURIComponent(logFileSelect.value);

        fetchJson('/system/logs' + params).then(function (data) {
            if (!data) return;
            renderLogEntries(data.entries || []);
            renderLogPagination(data.total || 0, data.page || 1, data.limit || logPageSize);
            renderLogStaleWarning(data.file_modified);
        });
    }

    function renderLogEntries(entries) {
        if (!entries.length) {
            logEntriesEl.innerHTML = '<div class="empty">' + i18n.t('system.logs.no_entries') + '</div>';
            return;
        }
        var html = '';
        entries.forEach(function (e) {
            html += '<div class="log-row">'
                + '<span class="log-ts">' + escapeHtml(formatIsoTimestamp(e.timestamp, true) || e.timestamp || '') + '</span>'
                + '<span class="log-lvl log-lvl-' + escapeHtml(e.level || 'INFO') + '">' + escapeHtml(e.level || '') + '</span>'
                + '<span class="log-src">' + escapeHtml(e.source || '') + '</span>'
                + '<span class="log-msg">' + escapeHtml(e.message || '') + '</span>'
                + '</div>';
        });
        logEntriesEl.innerHTML = html;
    }

    function renderLogPagination(total, page, limit) {
        var totalPages = Math.max(1, Math.ceil(total / limit));
        if (totalPages <= 1) { logPagination.innerHTML = ''; return; }
        var html = '<button type="button"' + (page <= 1 ? ' disabled' : '') + ' data-logpage="' + (page - 1) + '">&laquo; ' + i18n.t('pagination.prev') + '</button>';
        html += '<span>' + i18n.t('pagination.page_info', { page: page, totalPages: totalPages, total: total }) + '</span>';
        html += '<button type="button"' + (page >= totalPages ? ' disabled' : '') + ' data-logpage="' + (page + 1) + '">' + i18n.t('pagination.next') + ' &raquo;</button>';
        logPagination.innerHTML = html;
    }

    function renderLogStaleWarning(fileModified) {
        if (!logStaleWarning || !fileModified) {
            if (logStaleWarning) logStaleWarning.hidden = true;
            return;
        }
        var modDate = new Date(fileModified);
        if (Number.isNaN(modDate.getTime())) {
            logStaleWarning.hidden = true;
            return;
        }
        var ageMs = Date.now() - modDate.getTime();
        var STALE_THRESHOLD = 10 * 60 * 1000; // 10 minutes
        if (ageMs > STALE_THRESHOLD) {
            var agoMinutes = Math.floor(ageMs / 60000);
            var agoText;
            if (agoMinutes < 60) {
                agoText = agoMinutes + 'm';
            } else if (agoMinutes < 1440) {
                agoText = Math.floor(agoMinutes / 60) + 'h ' + (agoMinutes % 60) + 'm';
            } else {
                agoText = Math.floor(agoMinutes / 1440) + 'd ' + Math.floor((agoMinutes % 1440) / 60) + 'h';
            }
            logStaleWarning.innerHTML = '&#x26A0; ' + i18n.t('system.logs.stale_warning', {
                time: formatIsoTimestamp(fileModified),
                ago: agoText,
            });
            logStaleWarning.hidden = false;
        } else {
            logStaleWarning.hidden = true;
        }
    }

    logPagination.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-logpage]');
        if (btn) loadLogs(parseInt(btn.dataset.logpage, 10));
    });
    logLevelFilter.addEventListener('change', function () {
        loadLogs(1);
    });
    logFileSelect.addEventListener('change', function () { loadLogs(1); });
    logRefreshBtn.addEventListener('click', function () { loadLogs(); });

    var logSearchTimeout;
    logSearch.addEventListener('input', function () {
        clearTimeout(logSearchTimeout);
        logSearchTimeout = setTimeout(function () { loadLogs(1); }, 400);
    });

    function startLogPolling() {
        stopLogPolling();
        if (logAutoRefresh.checked) {
            logTimer = setInterval(function () { loadLogs(); }, 5000);
        }
    }

    function stopLogPolling() {
        if (logTimer) { clearInterval(logTimer); logTimer = null; }
    }

    logAutoRefresh.addEventListener('change', function () {
        if (logAutoRefresh.checked) startLogPolling();
        else stopLogPolling();
    });

    /* ── Tasks history ── */

    var tasksTableWrap = document.getElementById('tasks-table-wrap');
    var tasksPagination = document.getElementById('tasks-pagination');
    var tasksStatusFilter = document.getElementById('tasks-status-filter');
    var tasksSearch = document.getElementById('tasks-search');
    var tasksRefreshBtn = document.getElementById('tasks-refresh');
    var tasksCurrentPage = 1;
    var tasksPageSize = 50;
    var tasksSortCol = 'submitted';
    var tasksSortDir = 'desc';

    function loadTasks(page) {
        if (page !== undefined) tasksCurrentPage = page;
        var params = '?page=' + tasksCurrentPage + '&limit=' + tasksPageSize;
        if (tasksStatusFilter.value) params += '&status=' + encodeURIComponent(tasksStatusFilter.value);
        if (tasksSearch.value.trim()) params += '&search=' + encodeURIComponent(tasksSearch.value.trim());
        fetchJson('/system/tasks' + params).then(function (data) {
            if (!data) return;
            renderTasks(data.tasks || []);
            renderTasksPagination(data.total || 0, data.page || 1, data.limit || tasksPageSize);
        });
    }

    function renderTasks(tasks) {
        if (!tasks.length) {
            tasksTableWrap.innerHTML = '<div class="empty">' + i18n.t('system.no_tasks') + '</div>';
            return;
        }

        var cols = [
            { key: 'name', label: i18n.t('table.name') },
            { key: 'status', label: i18n.t('table.status') },
            { key: 'codec', label: i18n.t('table.codec') },
            { key: 'size', label: i18n.t('table.size') },
            { key: 'duration', label: i18n.t('table.duration') },
            { key: 'submitted', label: i18n.t('table.submitted') },
        ];

        var thead = '<thead><tr>' + cols.map(function (c) {
            var cls = tasksSortCol === c.key ? ' class="jt-sorted"' : '';
            return '<th' + cls + ' data-tasks-sort="' + c.key + '">' + c.label + buildTaskSortIndicator(c.key) + '</th>';
        }).join('') + '</tr></thead>';

        // Sort locally
        var sorted = tasks.slice().sort(function (a, b) {
            var va, vb;
            switch (tasksSortCol) {
                case 'name': va = baseName(a.input_file); vb = baseName(b.input_file); break;
                case 'status': va = a.status || ''; vb = b.status || ''; break;
                case 'codec': va = resolvePresetLabel(a); vb = resolvePresetLabel(b); break;
                case 'size': va = Number(a.input_size_bytes || 0); vb = Number(b.input_size_bytes || 0); break;
                case 'duration':
                    va = taskDuration(a); vb = taskDuration(b); break;
                case 'submitted':
                default:
                    va = a.submitted_at || ''; vb = b.submitted_at || ''; break;
            }
            var cmp = va < vb ? -1 : va > vb ? 1 : 0;
            return tasksSortDir === 'asc' ? cmp : -cmp;
        });

        var tbody = '<tbody>' + sorted.map(function (t) {
            var name = baseName(t.input_file);
            var statusCls = 'status-badge status-' + (t.status || 'queued');
            var sizeIn = formatBytes(Number(t.input_size_bytes || 0));
            var sizeOut = t.output_size_bytes ? formatBytes(Number(t.output_size_bytes)) : '–';
            var comp = t.compression_percent != null ? ' (' + Number(t.compression_percent).toFixed(1) + '%)' : '';
            var dur = taskDurationLabel(t);
            var sub = formatIsoTimestamp(t.submitted_at) || t.submitted_display || '';
            var rowCls = t.status === 'failed' ? ' class="task-row-failed"' : '';
            return '<tr' + rowCls + '>'
                + '<td title="' + escapeHtml(t.input_file || '') + '">' + escapeHtml(name) + '</td>'
                + '<td><span class="' + statusCls + '">' + escapeHtml(i18n.t('job_status.' + (t.status || 'queued'))) + '</span></td>'
                + '<td>' + escapeHtml(resolvePresetLabel(t)) + '</td>'
                + '<td>' + sizeIn + ' → ' + sizeOut + comp + '</td>'
                + '<td>' + dur + '</td>'
                + '<td>' + escapeHtml(sub) + '</td>'
                + '</tr>';
        }).join('') + '</tbody>';

        tasksTableWrap.innerHTML = '<table class="tasks-table jt-table">' + thead + tbody + '</table>';
    }

    function baseName(path) {
        if (!path) return '–';
        return path.replace(/\\/g, '/').split('/').pop() || path;
    }

    function taskDuration(t) {
        if (!t.started_at || !t.finished_at) return 0;
        return new Date(t.finished_at) - new Date(t.started_at);
    }

    function taskDurationLabel(t) {
        var ms = taskDuration(t);
        if (!ms) return '–';
        var secs = Math.floor(ms / 1000);
        if (secs < 60) return secs + 's';
        var mins = Math.floor(secs / 60);
        secs = secs % 60;
        if (mins < 60) return mins + 'm ' + secs + 's';
        var hrs = Math.floor(mins / 60);
        mins = mins % 60;
        return hrs + 'h ' + mins + 'm';
    }

    function buildTaskSortIndicator(key) {
        if (tasksSortCol !== key) return '';
        return tasksSortDir === 'asc' ? ' &#x25B2;' : ' &#x25BC;';
    }

    function renderTasksPagination(total, page, limit) {
        var totalPages = Math.max(1, Math.ceil(total / limit));
        if (totalPages <= 1) { tasksPagination.innerHTML = ''; return; }
        var html = '<button type="button"' + (page <= 1 ? ' disabled' : '') + ' data-taskpage="' + (page - 1) + '">&laquo; ' + i18n.t('pagination.prev') + '</button>';
        html += '<span>' + i18n.t('pagination.page_info', { page: page, totalPages: totalPages, total: total }) + '</span>';
        html += '<button type="button"' + (page >= totalPages ? ' disabled' : '') + ' data-taskpage="' + (page + 1) + '">' + i18n.t('pagination.next') + ' &raquo;</button>';
        tasksPagination.innerHTML = html;
    }

    tasksStatusFilter.addEventListener('change', function () { loadTasks(1); });
    tasksRefreshBtn.addEventListener('click', function () { loadTasks(); });

    var tasksSearchTimeout;
    tasksSearch.addEventListener('input', function () {
        clearTimeout(tasksSearchTimeout);
        tasksSearchTimeout = setTimeout(function () { loadTasks(1); }, 400);
    });

    tasksPagination.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-taskpage]');
        if (btn) loadTasks(parseInt(btn.dataset.taskpage, 10));
    });

    if (tasksTableWrap) {
        tasksTableWrap.addEventListener('click', function (e) {
            var th = e.target.closest('[data-tasks-sort]');
            if (!th) return;
            var col = th.dataset.tasksSort;
            if (tasksSortCol === col) {
                tasksSortDir = tasksSortDir === 'asc' ? 'desc' : 'asc';
            } else {
                tasksSortCol = col;
                tasksSortDir = col === 'submitted' ? 'desc' : 'asc';
            }
            loadTasks();
        });
    }

    /* ── Auth / Users ── */

    var sidebarUser = document.getElementById('sidebar-user');
    var sidebarUserName = document.getElementById('sidebar-user-name');
    var sidebarUserRole = document.getElementById('sidebar-user-role');
    var sidebarAvatar = document.getElementById('sidebar-avatar');
    var sidebarSignOutBtn = document.getElementById('sidebar-sign-out-btn');
    var navSettingsGroup = document.getElementById('nav-settings-group');
    var navSystemGroup = document.getElementById('nav-system-group');
    var usersList = document.getElementById('users-list');
    var userFormSection = document.getElementById('user-form-section');
    var userFormLegend = document.getElementById('user-form-legend');
    var userForm = document.getElementById('user-form');
    var userFormId = document.getElementById('user-form-id');
    var userFormUsername = document.getElementById('user-form-username');
    var userFormEmail = document.getElementById('user-form-email');
    var userFormPassword = document.getElementById('user-form-password');
    var userFormPasswordRow = document.getElementById('user-form-password-row');
    var userFormSetPasswordRow = document.getElementById('user-form-set-password-row');
    var userFormRole = document.getElementById('user-form-role');
    var userFormSubmit = document.getElementById('user-form-submit');
    var userFormCancel = document.getElementById('user-form-cancel');
    var userFormStatus = document.getElementById('user-form-status');
    var addUserBtn = document.getElementById('add-user-btn');
    var changePasswordForm = document.getElementById('change-password-form');
    var changePasswordStatus = document.getElementById('change-password-status');
    var smtpForm = document.getElementById('smtp-form');
    var smtpStatus = document.getElementById('smtp-status');
    var adminTokensList = document.getElementById('admin-tokens-list');
    var adminTokensStatus = document.getElementById('admin-tokens-status');

    /* ── Avatar helper ── */

    function userInitials(name) {
        var parts = String(name || '?').trim().split(/[\s._-]+/);
        if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
        return String(name || '?').substring(0, 2).toUpperCase();
    }

    function avatarColor(name) {
        var hash = 0;
        var s = String(name || '');
        for (var i = 0; i < s.length; i++) hash = ((hash << 5) - hash + s.charCodeAt(i)) | 0;
        var hue = ((hash % 360) + 360) % 360;
        return 'hsl(' + hue + ', 45%, 45%)';
    }

    function renderAvatar(el, user) {
        if (!el || !user) return;
        var initials = userInitials(user.username);
        el.style.background = avatarColor(user.username);
        el.textContent = initials;
        // Try Gravatar if email is available
        if (user.email) {
            var img = new Image();
            var emailHash = simpleHash(user.email.trim().toLowerCase());
            img.src = 'https://www.gravatar.com/avatar/' + emailHash + '?s=96&d=404';
            img.onload = function () {
                el.textContent = '';
                el.appendChild(img);
            };
            // On error, keep initials (default)
        }
    }

    // Simple string hash for Gravatar (produces hex string; not MD5 but serves as cache key)
    // For proper Gravatar we need MD5 — include a minimal implementation
    function simpleHash(str) {
        return md5(str);
    }

    // Minimal MD5 implementation for Gravatar
    function md5(string) {
        function md5cycle(x, k) {
            var a = x[0], b = x[1], c = x[2], d = x[3];
            a = ff(a, b, c, d, k[0], 7, -680876936); d = ff(d, a, b, c, k[1], 12, -389564586);
            c = ff(c, d, a, b, k[2], 17, 606105819); b = ff(b, c, d, a, k[3], 22, -1044525330);
            a = ff(a, b, c, d, k[4], 7, -176418897); d = ff(d, a, b, c, k[5], 12, 1200080426);
            c = ff(c, d, a, b, k[6], 17, -1473231341); b = ff(b, c, d, a, k[7], 22, -45705983);
            a = ff(a, b, c, d, k[8], 7, 1770035416); d = ff(d, a, b, c, k[9], 12, -1958414417);
            c = ff(c, d, a, b, k[10], 17, -42063); b = ff(b, c, d, a, k[11], 22, -1990404162);
            a = ff(a, b, c, d, k[12], 7, 1804603682); d = ff(d, a, b, c, k[13], 12, -40341101);
            c = ff(c, d, a, b, k[14], 17, -1502002290); b = ff(b, c, d, a, k[15], 22, 1236535329);
            a = gg(a, b, c, d, k[1], 5, -165796510); d = gg(d, a, b, c, k[6], 9, -1069501632);
            c = gg(c, d, a, b, k[11], 14, 643717713); b = gg(b, c, d, a, k[0], 20, -373897302);
            a = gg(a, b, c, d, k[5], 5, -701558691); d = gg(d, a, b, c, k[10], 9, 38016083);
            c = gg(c, d, a, b, k[15], 14, -660478335); b = gg(b, c, d, a, k[4], 20, -405537848);
            a = gg(a, b, c, d, k[9], 5, 568446438); d = gg(d, a, b, c, k[14], 9, -1019803690);
            c = gg(c, d, a, b, k[3], 14, -187363961); b = gg(b, c, d, a, k[8], 20, 1163531501);
            a = gg(a, b, c, d, k[13], 5, -1444681467); d = gg(d, a, b, c, k[2], 9, -51403784);
            c = gg(c, d, a, b, k[7], 14, 1735328473); b = gg(b, c, d, a, k[12], 20, -1926607734);
            a = hh(a, b, c, d, k[5], 4, -378558); d = hh(d, a, b, c, k[8], 11, -2022574463);
            c = hh(c, d, a, b, k[11], 16, 1839030562); b = hh(b, c, d, a, k[14], 23, -35309556);
            a = hh(a, b, c, d, k[1], 4, -1530992060); d = hh(d, a, b, c, k[4], 11, 1272893353);
            c = hh(c, d, a, b, k[7], 16, -155497632); b = hh(b, c, d, a, k[10], 23, -1094730640);
            a = hh(a, b, c, d, k[13], 4, 681279174); d = hh(d, a, b, c, k[0], 11, -358537222);
            c = hh(c, d, a, b, k[3], 16, -722521979); b = hh(b, c, d, a, k[6], 23, 76029189);
            a = hh(a, b, c, d, k[9], 4, -640364487); d = hh(d, a, b, c, k[12], 11, -421815835);
            c = hh(c, d, a, b, k[15], 16, 530742520); b = hh(b, c, d, a, k[2], 23, -995338651);
            a = ii(a, b, c, d, k[0], 6, -198630844); d = ii(d, a, b, c, k[7], 10, 1126891415);
            c = ii(c, d, a, b, k[14], 15, -1416354905); b = ii(b, c, d, a, k[5], 21, -57434055);
            a = ii(a, b, c, d, k[12], 6, 1700485571); d = ii(d, a, b, c, k[3], 10, -1894986606);
            c = ii(c, d, a, b, k[10], 15, -1051523); b = ii(b, c, d, a, k[1], 21, -2054922799);
            a = ii(a, b, c, d, k[8], 6, 1873313359); d = ii(d, a, b, c, k[15], 10, -30611744);
            c = ii(c, d, a, b, k[6], 15, -1560198380); b = ii(b, c, d, a, k[13], 21, 1309151649);
            a = ii(a, b, c, d, k[4], 6, -145523070); d = ii(d, a, b, c, k[11], 10, -1120210379);
            c = ii(c, d, a, b, k[2], 15, 718787259); b = ii(b, c, d, a, k[9], 21, -343485551);
            x[0] = add32(a, x[0]); x[1] = add32(b, x[1]); x[2] = add32(c, x[2]); x[3] = add32(d, x[3]);
        }
        function cmn(q, a, b, x, s, t) { a = add32(add32(a, q), add32(x, t)); return add32((a << s) | (a >>> (32 - s)), b); }
        function ff(a, b, c, d, x, s, t) { return cmn((b & c) | ((~b) & d), a, b, x, s, t); }
        function gg(a, b, c, d, x, s, t) { return cmn((b & d) | (c & (~d)), a, b, x, s, t); }
        function hh(a, b, c, d, x, s, t) { return cmn(b ^ c ^ d, a, b, x, s, t); }
        function ii(a, b, c, d, x, s, t) { return cmn(c ^ (b | (~d)), a, b, x, s, t); }
        function md5blk(s) {
            var md5blks = [], i;
            for (i = 0; i < 64; i += 4) {
                md5blks[i >> 2] = s.charCodeAt(i) + (s.charCodeAt(i + 1) << 8) + (s.charCodeAt(i + 2) << 16) + (s.charCodeAt(i + 3) << 24);
            }
            return md5blks;
        }
        function md5blk_array(a) {
            var md5blks = [], i;
            for (i = 0; i < 64; i += 4) {
                md5blks[i >> 2] = a[i] + (a[i + 1] << 8) + (a[i + 2] << 16) + (a[i + 3] << 24);
            }
            return md5blks;
        }
        var hex_chr = '0123456789abcdef'.split('');
        function rhex(n) {
            var s = '', j = 0;
            for (; j < 4; j++) s += hex_chr[(n >> (j * 8 + 4)) & 0x0f] + hex_chr[(n >> (j * 8)) & 0x0f];
            return s;
        }
        function hex(x) { for (var i = 0; i < x.length; i++) x[i] = rhex(x[i]); return x.join(''); }
        function add32(a, b) { return (a + b) & 0xFFFFFFFF; }

        var n = string.length, state = [1732584193, -271733879, -1732584194, 271733878], i;
        for (i = 64; i <= n; i += 64) md5cycle(state, md5blk(string.substring(i - 64, i)));
        string = string.substring(i - 64);
        var tail = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0];
        for (i = 0; i < string.length; i++) tail[i >> 2] |= string.charCodeAt(i) << ((i % 4) << 3);
        tail[i >> 2] |= 0x80 << ((i % 4) << 3);
        if (i > 55) { md5cycle(state, tail); tail = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]; }
        tail[14] = n * 8;
        md5cycle(state, tail);
        return hex(state);
    }

    /* ── Sidebar group toggle ── */

    function isCollapsedSidebar() {
        return window.matchMedia('(max-width: 920px)').matches &&
               !window.matchMedia('(max-width: 640px)').matches;
    }

    function closeAllFlyouts() {
        sidebar.querySelectorAll('.sidebar-group.flyout-open').forEach(function (g) {
            g.classList.remove('flyout-open');
        });
    }

    (function initSidebarGroups() {
        var toggles = sidebar.querySelectorAll('.sidebar-group-toggle');
        toggles.forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                var group = btn.closest('.sidebar-group');
                if (!group) return;

                if (isCollapsedSidebar()) {
                    // Flyout mode: toggle flyout-open, accordion
                    e.stopPropagation();
                    var wasOpen = group.classList.contains('flyout-open');
                    closeAllFlyouts();
                    if (!wasOpen) group.classList.add('flyout-open');
                } else {
                    // Normal mode: toggle inline sub-menu, accordion
                    var wasOpen = group.classList.contains('open');
                    sidebar.querySelectorAll('.sidebar-group.open').forEach(function (g) {
                        g.classList.remove('open');
                    });
                    if (!wasOpen) group.classList.add('open');
                }
            });
        });

        // Close flyout when clicking outside
        document.addEventListener('mousedown', function (e) {
            if (!sidebar.contains(e.target)) {
                closeAllFlyouts();
            }
        });

        // Close flyout on navigation
        window.addEventListener('hashchange', function () {
            closeAllFlyouts();
        });
    })();

    /* ── User Settings page ── */

    var userSettingsAvatar = document.getElementById('user-settings-avatar');
    var userSettingsUsername = document.getElementById('user-settings-username');
    var userSettingsEmail = document.getElementById('user-settings-email');
    var userSettingsRole = document.getElementById('user-settings-role');
    var userSettingsTheme = document.getElementById('user-settings-theme');
    var userSettingsDateFormat = document.getElementById('user-settings-date-format');

    function populateUserSettings() {
        var user = state.auth.user;
        if (!user) return;
        if (userSettingsAvatar) renderAvatar(userSettingsAvatar, user);
        if (userSettingsUsername) userSettingsUsername.value = user.username;
        if (userSettingsEmail) userSettingsEmail.value = user.email || '';
        if (userSettingsRole) userSettingsRole.textContent = i18n.t('system.users.role_' + user.role);
        if (userSettingsTheme) userSettingsTheme.value = state.theme;
        // Load user preferences from server
        if (state.auth.enabled && state.auth.token) {
            fetchJson('/auth/me/preferences').then(function (prefs) {
                if (userSettingsDateFormat) userSettingsDateFormat.value = prefs.date_format || '';
                // Apply user date format override (user pref > server default)
                if (prefs.date_format) state.dateFormat = prefs.date_format;
            }).catch(function () { /* ignore */ });
        }
    }

    if (userSettingsTheme) {
        userSettingsTheme.addEventListener('change', function () {
            applyTheme(userSettingsTheme.value);
            persistTheme(userSettingsTheme.value);
            if (themeSelect) themeSelect.value = userSettingsTheme.value;
            // Also persist theme to server
            if (state.auth.enabled && state.auth.token) {
                fetchJson('/auth/me/preferences', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ theme: userSettingsTheme.value }),
                }).catch(function () { /* ignore */ });
            }
        });
    }

    if (userSettingsDateFormat) {
        userSettingsDateFormat.addEventListener('change', function () {
            var fmt = userSettingsDateFormat.value;
            if (fmt) state.dateFormat = fmt;
            if (state.auth.enabled && state.auth.token) {
                fetchJson('/auth/me/preferences', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ date_format: fmt }),
                }).then(function () {
                    showToast(i18n.t('toast.date_format_saved'));
                    // Re-render jobs to reflect new format
                    refreshJobs();
                }).catch(function (err) { showToast(err.message, 'error'); });
            }
        });
    }

    // ── Language selectors ──
    var generalLanguageSelect = document.getElementById('general-language');
    var userSettingsLanguageSelect = document.getElementById('user-settings-language');

    if (generalLanguageSelect) {
        generalLanguageSelect.addEventListener('change', async function () {
            await i18n.setLanguage(generalLanguageSelect.value);
            if (userSettingsLanguageSelect) userSettingsLanguageSelect.value = generalLanguageSelect.value;
            updateAutoRefreshButton();
            refreshAll();
        });
    }

    if (userSettingsLanguageSelect) {
        userSettingsLanguageSelect.addEventListener('change', async function () {
            await i18n.setLanguage(userSettingsLanguageSelect.value);
            if (generalLanguageSelect) generalLanguageSelect.value = userSettingsLanguageSelect.value;
            updateAutoRefreshButton();
            refreshAll();
        });
    }

    // ── Personal API Tokens (User Settings) ──
    var userTokensList = document.getElementById('user-tokens-list');
    var userCreateTokenBtn = document.getElementById('user-create-token-btn');
    var userTokensStatus = document.getElementById('user-tokens-status');

    async function refreshUserTokens() {
        if (!state.auth.enabled || !userTokensList) return;
        try {
            var data = await fetchJson('/auth/tokens');
            renderUserTokensList(data.tokens || []);
        } catch (_) {
            if (userTokensList) userTokensList.innerHTML = '<div class="empty">Could not load tokens.</div>';
        }
    }

    function renderUserTokensList(tokens) {
        if (!userTokensList) return;
        if (!tokens.length) {
            userTokensList.innerHTML = '<div class="empty">' + i18n.t('auth.no_tokens') + '</div>';
            return;
        }
        userTokensList.innerHTML = '<table class="users-table">'
            + '<thead><tr><th>' + i18n.t('table.name') + '</th><th>' + i18n.t('table.created') + '</th><th>' + i18n.t('table.expires') + '</th><th></th></tr></thead>'
            + '<tbody>'
            + tokens.map(function (t) {
                return '<tr>'
                    + '<td>' + escapeHtml(t.name || i18n.t('auth.unnamed_token')) + '</td>'
                    + '<td>' + escapeHtml(formatIsoTimestamp(t.created_at) || String(t.created_at || '').substring(0, 10)) + '</td>'
                    + '<td>' + escapeHtml(formatIsoTimestamp(t.expires_at) || String(t.expires_at || '').substring(0, 10)) + '</td>'
                    + '<td class="actions-cell"><button class="ghost danger-text" data-delete-user-token="' + t.id + '">' + i18n.t('common.revoke') + '</button></td>'
                    + '</tr>';
            }).join('')
            + '</tbody></table>';
    }

    if (userTokensList) {
        userTokensList.addEventListener('click', function (e) {
            var tokenId = e.target.dataset.deleteUserToken;
            if (tokenId) {
                showConfirm({ title: i18n.t('confirm.revoke_token_title'), message: i18n.t('confirm.revoke_token_message'), ok: i18n.t('confirm.revoke_token_ok') }).then(function (confirmed) {
                    if (!confirmed) return;
                    fetchJson('/auth/tokens/' + tokenId, { method: 'DELETE' })
                        .then(function () { refreshUserTokens(); showToast(i18n.t('toast.token_revoked')); })
                        .catch(function (err) { showToast(err.message, 'error'); });
                });
            }
        });
    }

    if (userCreateTokenBtn) {
        userCreateTokenBtn.addEventListener('click', function () {
            showPrompt({ title: i18n.t('auth.create_token_title'), message: i18n.t('auth.create_token_message'), placeholder: i18n.t('auth.token_placeholder'), ok: i18n.t('common.create') }).then(function (name) {
                if (name === null) return;
                fetchJson('/auth/tokens', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name || 'API token', days: 365 }),
                })
                    .then(function (data) {
                        setStatus(userTokensStatus, i18n.t('toast.token_created', { token: data.token }), 'ok');
                        refreshUserTokens();
                    })
                    .catch(function (err) { setStatus(userTokensStatus, err.message, 'error'); });
            });
        });
    }

    /* ── Sidebar sign-out ── */

    function doSignOut() {
        fetchJson('/auth/logout', { method: 'POST' }).catch(function () { /* ignore */ });
        state.auth.token = '';
        state.auth.user = null;
        try { localStorage.removeItem(tokenStorageKey); } catch (_) { /* noop */ }
        window.location.replace('/login');
    }

    if (sidebarSignOutBtn) {
        sidebarSignOutBtn.addEventListener('click', doSignOut);
    }

    /* ── User popup menu ── */

    var sidebarUserPopup = document.getElementById('sidebar-user-popup');
    var sidebarUserToggle = document.getElementById('sidebar-user-toggle');

    if (sidebarUserToggle) {
        sidebarUserToggle.addEventListener('click', function (e) {
            if (!sidebarUserPopup) return;
            e.stopPropagation();
            sidebarUserPopup.hidden = !sidebarUserPopup.hidden;
        });
    }

    // Close popup when clicking outside
    document.addEventListener('mousedown', function (e) {
        if (sidebarUserPopup && !sidebarUserPopup.hidden && sidebarUser && !sidebarUser.contains(e.target)) {
            sidebarUserPopup.hidden = true;
        }
    });

    // Close popup on navigation
    window.addEventListener('hashchange', function () {
        if (sidebarUserPopup) sidebarUserPopup.hidden = true;
    });

    function getStoredToken() {
        try { return localStorage.getItem(tokenStorageKey) || ''; } catch (_) { return ''; }
    }

    function initAuth() {
        // If the URL hash contains a password-reset token, redirect to /login preserving the hash
        var currentHash = window.location.hash || '';
        if (currentHash.indexOf('reset-password?token=') !== -1) {
            window.location.replace('/login' + currentHash);
            return Promise.reject(new Error('redirecting'));
        }
        state.auth.token = getStoredToken();
        return fetchJson('/auth/status').then(function (data) {
            state.auth.enabled = data.auth_enabled;
            if (!data.auth_enabled) {
                // Auth disabled — treat as anonymous admin
                state.auth.user = { id: 0, username: 'admin', email: '', role: 'admin' };
                renderAuthUI();
                return;
            }
            if (!state.auth.token) {
                window.location.replace('/login');
                throw new Error(i18n.t('auth.login_required'));
            }
            return fetchJson('/auth/me').then(function (me) {
                state.auth.user = me.user;
                renderAuthUI();
            }).catch(function () {
                state.auth.token = '';
                try { localStorage.removeItem(tokenStorageKey); } catch (_) { /* noop */ }
                window.location.replace('/login');
                throw new Error(i18n.t('auth.session_expired'));
            });
        });
    }

    function renderAuthUI() {
        var user = state.auth.user;
        if (!user) {
            if (sidebarUser) sidebarUser.hidden = true;
            if (navSettingsGroup) navSettingsGroup.hidden = true;
            if (navSystemGroup) navSystemGroup.hidden = true;
            return;
        }
        if (!state.auth.enabled) {
            // Auth disabled — show everything, hide user widget
            if (sidebarUser) sidebarUser.hidden = true;
            if (navSettingsGroup) {
                navSettingsGroup.hidden = false;
                navSettingsGroup.querySelectorAll('.sidebar-sub-link').forEach(function (link) {
                    link.parentElement.hidden = false;
                });
                navSettingsGroup.querySelectorAll('.sidebar-flyout a').forEach(function (link) {
                    link.hidden = false;
                });
            }
            if (navSystemGroup) navSystemGroup.hidden = false;
            if (addUserBtn) addUserBtn.style.display = 'none';
            return;
        }
        if (sidebarUser) {
            sidebarUser.hidden = false;
            sidebarUserName.textContent = user.username;
            sidebarUserRole.textContent = user.role;
            renderAvatar(sidebarAvatar, user);
        }
        // Settings and System groups visibility
        var isAdmin = user.role === 'admin';
        if (navSettingsGroup) {
            // Settings group is always visible (for User sub-page), but admin-only sub-links are hidden
            navSettingsGroup.hidden = false;
            var settingsSubLinks = navSettingsGroup.querySelectorAll('.sidebar-sub-link');
            settingsSubLinks.forEach(function (link) {
                var page = link.dataset.page;
                if (page === 'settings/user') {
                    link.parentElement.hidden = false;
                } else {
                    link.parentElement.hidden = !isAdmin;
                }
            });
            // Also hide admin-only flyout links
            var settingsFlyoutLinks = navSettingsGroup.querySelectorAll('.sidebar-flyout a');
            settingsFlyoutLinks.forEach(function (link) {
                var page = link.dataset.page;
                if (page === 'settings/user') {
                    link.hidden = false;
                } else {
                    link.hidden = !isAdmin;
                }
            });
        }
        if (navSystemGroup) navSystemGroup.hidden = !isAdmin;
        // Add user button only for admin
        if (addUserBtn) {
            addUserBtn.style.display = isAdmin ? '' : 'none';
        }
    }

    async function refreshUsers() {
        if (!state.auth.enabled) return;
        var user = state.auth.user;
        if (!user) return;
        if (user.role === 'admin') {
            try {
                var data = await fetchJson('/auth/users');
                renderUsersList(data.users || []);
            } catch (err) {
                if (usersList) usersList.innerHTML = '<div class="empty">' + escapeHtml(err.message) + '</div>';
            }
        } else {
            if (usersList) usersList.innerHTML = '<div class="empty">' + i18n.t('system.users.only_admins') + '</div>';
        }
    }

    function renderUsersList(users) {
        if (!usersList) return;
        if (!users.length) {
            usersList.innerHTML = '<div class="empty">' + i18n.t('system.users.no_users') + '</div>';
            return;
        }
        var currentId = state.auth.user ? state.auth.user.id : 0;
        var isAdmin = state.auth.user && state.auth.user.role === 'admin';
        usersList.innerHTML = '<table class="users-table">'
            + '<thead><tr><th></th><th>' + i18n.t('table.username') + '</th><th>' + i18n.t('table.email') + '</th><th>' + i18n.t('table.role') + '</th><th></th></tr></thead>'
            + '<tbody>'
            + users.map(function (u) {
                var actions = '';
                if (isAdmin) {
                    actions = '<button class=\"ghost\" data-edit-user=\"' + u.id + '\">' + i18n.t('common.edit') + '</button>';
                    if (u.id !== currentId) {
                        actions += ' <button class=\"ghost danger-text\" data-delete-user=\"' + u.id + '\">' + i18n.t('common.delete') + '</button>';
                    }
                }
                var bg = avatarColor(u.username);
                var initials = userInitials(u.username);
                var avatarHtml = '<span class="user-avatar user-avatar-sm" data-avatar-user="' + escapeHtml(u.username) + '" data-avatar-email="' + escapeHtml(u.email || '') + '" style="background:' + bg + '">' + escapeHtml(initials) + '</span>';
                var roleKey = 'system.users.role_' + u.role;
                return '<tr>'
                    + '<td class="avatar-cell">' + avatarHtml + '</td>'
                    + '<td>' + escapeHtml(u.username) + (u.id === currentId ? ' <span class="chip">' + i18n.t('system.users.you') + '</span>' : '') + '</td>'
                    + '<td>' + escapeHtml(u.email) + '</td>'
                    + '<td><span class="chip">' + escapeHtml(i18n.t(roleKey)) + '</span></td>'
                    + '<td class="actions-cell">' + actions + '</td>'
                    + '</tr>';
            }).join('')
            + '</tbody></table>';
        // Attempt Gravatar for each avatar
        usersList.querySelectorAll('[data-avatar-user]').forEach(function (el) {
            var email = el.dataset.avatarEmail;
            if (!email) return;
            var img = new Image();
            var emailHash = simpleHash(email.trim().toLowerCase());
            img.src = 'https://www.gravatar.com/avatar/' + emailHash + '?s=56&d=404';
            img.onload = function () { el.textContent = ''; el.appendChild(img); };
        });
    }

    if (usersList) {
        usersList.addEventListener('click', function (e) {
            var editId = e.target.dataset.editUser;
            var deleteId = e.target.dataset.deleteUser;
            if (editId) {
                openEditUser(Number(editId));
            }
            if (deleteId) {
                confirmDeleteUser(Number(deleteId));
            }
        });
    }

    function openNewUser() {
        if (!userFormSection) return;
        userFormSection.hidden = false;
        scrollAndHighlight(userFormSection);
        userFormLegend.textContent = i18n.t('system.users.new_user');
        userFormId.value = '';
        userFormUsername.value = '';
        userFormEmail.value = '';
        userFormPassword.value = '';
        userFormPassword.required = true;
        userFormPasswordRow.style.display = '';
        if (userFormSetPasswordRow) userFormSetPasswordRow.hidden = true;
        userFormRole.value = 'viewer';
        userFormSubmit.textContent = i18n.t('common.create');
        setStatus(userFormStatus, '');
    }

    function openEditUser(userId) {
        fetchJson('/auth/users').then(function (data) {
            var users = data.users || [];
            var user = null;
            for (var i = 0; i < users.length; i++) {
                if (users[i].id === userId) { user = users[i]; break; }
            }
            if (!user) return;
            if (!userFormSection) return;
            userFormSection.hidden = false;
            scrollAndHighlight(userFormSection);
            userFormLegend.textContent = i18n.t('system.users.edit_user');
            userFormId.value = String(user.id);
            userFormUsername.value = user.username;
            userFormEmail.value = user.email;
            userFormPassword.value = '';
            userFormPassword.required = false;
            userFormPasswordRow.style.display = 'none';
            userFormRole.value = user.role;
            userFormSubmit.textContent = i18n.t('common.save');
            // Show admin set-password field when editing other users
            if (userFormSetPasswordRow) {
                userFormSetPasswordRow.hidden = false;
                var setPassInput = document.getElementById('user-form-set-password');
                if (setPassInput) setPassInput.value = '';
            }
            setStatus(userFormStatus, '');
        });
    }

    function confirmDeleteUser(userId) {
        showConfirm({ title: i18n.t('confirm.delete_user_title'), message: i18n.t('confirm.delete_user_message'), ok: i18n.t('confirm.delete_user_ok') })
            .then(function (confirmed) {
                if (!confirmed) return;
                fetchJson('/auth/users/' + userId, { method: 'DELETE' })
                    .then(function () { refreshUsers(); showToast(i18n.t('toast.user_deleted')); })
                    .catch(function (err) { showToast(err.message, 'error'); });
            });
    }

    if (addUserBtn) {
        addUserBtn.addEventListener('click', openNewUser);
    }

    if (userFormCancel) {
        userFormCancel.addEventListener('click', function () {
            if (userFormSection) userFormSection.hidden = true;
        });
    }

    if (userForm) {
        userForm.addEventListener('submit', async function (e) {
            e.preventDefault();
            var id = userFormId.value;
            var payload = {
                username: userFormUsername.value.trim(),
                email: userFormEmail.value.trim(),
                role: userFormRole.value,
            };

            if (id) {
                // Edit existing user — include admin set-password if provided
                var setPass = document.getElementById('user-form-set-password');
                if (setPass && setPass.value) {
                    payload.set_password = setPass.value;
                }
                try {
                    await fetchJson('/auth/users/' + id, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                    userFormSection.hidden = true;
                    showToast(i18n.t('toast.user_updated'));
                    refreshUsers();
                } catch (err) {
                    setStatus(userFormStatus, err.message, 'error');
                }
            } else {
                // Create new user
                payload.password = userFormPassword.value;
                try {
                    await fetchJson('/auth/users', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                    userFormSection.hidden = true;
                    showToast(i18n.t('toast.user_created'));
                    refreshUsers();
                } catch (err) {
                    setStatus(userFormStatus, err.message, 'error');
                }
            }
        });
    }

    if (changePasswordForm) {
        changePasswordForm.addEventListener('submit', async function (e) {
            e.preventDefault();
            var newPwd = document.getElementById('cp-new').value;
            var confirmPwd = document.getElementById('cp-confirm').value;
            if (newPwd !== confirmPwd) {
                setStatus(changePasswordStatus, i18n.t('toast.passwords_mismatch'), 'error');
                return;
            }
            try {
                var result = await fetchJson('/auth/me/password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        old_password: document.getElementById('cp-old').value,
                        new_password: newPwd,
                    }),
                });
                setStatus(changePasswordStatus, result.message || i18n.t('toast.password_changed'), 'ok');
                changePasswordForm.reset();
                // Token invalidated server-side; redirect to login after short delay
                setTimeout(function () {
                    state.auth.token = '';
                    try { localStorage.removeItem(tokenStorageKey); } catch (_) { /* noop */ }
                    window.location.replace('/login');
                }, 1500);
            } catch (err) {
                setStatus(changePasswordStatus, err.message, 'error');
            }
        });
    }

    // SMTP
    async function refreshSmtp() {
        if (!state.auth.user || state.auth.user.role !== 'admin') return;
        try {
            var cfg = await fetchJson('/auth/smtp');
            if (smtpForm) {
                smtpForm.elements.host.value = cfg.host || '';
                smtpForm.elements.port.value = cfg.port || 587;
                smtpForm.elements.username.value = cfg.username || '';
                smtpForm.elements.password.value = '';
                smtpForm.elements.password.placeholder = cfg.password ? '(unchanged)' : '';
                smtpForm.elements.use_tls.checked = cfg.use_tls !== false;
                smtpForm.elements.from_address.value = cfg.from_address || '';
                resetDirtyTracker('smtp-form');
            }
        } catch (_) { /* noop */ }
    }

    if (smtpForm) {
        smtpForm.addEventListener('submit', async function (e) {
            e.preventDefault();
            setStatus(smtpStatus, i18n.t('toast.saving'));
            var fd = new FormData(smtpForm);
            var payload = {
                host: fd.get('host') || '',
                port: Number(fd.get('port') || 587),
                username: fd.get('username') || '',
                use_tls: smtpForm.elements.use_tls.checked,
                from_address: fd.get('from_address') || '',
            };
            var pwd = fd.get('password');
            if (pwd) payload.password = pwd;
            try {
                await fetchJson('/auth/smtp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                setStatus(smtpStatus, i18n.t('toast.smtp_saved'), 'ok');
                resetDirtyTracker('smtp-form');
            } catch (err) {
                setStatus(smtpStatus, err.message, 'error');
            }
        });
    }

    var smtpTestBtn = document.getElementById('smtp-test-btn');
    if (smtpTestBtn) {
        smtpTestBtn.addEventListener('click', async function () {
            var recipient = (state.auth.user && state.auth.user.email) || '';
            if (!recipient) {
                setStatus(smtpStatus, i18n.t('toast.no_recipient_email'), 'error');
                return;
            }
            setStatus(smtpStatus, i18n.t('toast.sending_test_email'));
            try {
                var res = await fetchJson('/auth/smtp/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ recipient: recipient }),
                });
                setStatus(smtpStatus, res.message || i18n.t('toast.test_email_sent'), 'ok');
            } catch (err) {
                setStatus(smtpStatus, err.message, 'error');
            }
        });
    }

    // Admin: All API Tokens
    async function refreshAdminTokens() {
        if (!state.auth.enabled || !state.auth.user || state.auth.user.role !== 'admin') return;
        try {
            var data = await fetchJson('/auth/tokens/all');
            renderAdminTokensList(data.tokens || []);
        } catch (_) {
            if (adminTokensList) adminTokensList.innerHTML = '<div class="empty">Could not load tokens.</div>';
        }
    }

    function renderAdminTokensList(tokens) {
        if (!adminTokensList) return;
        if (!tokens.length) {
            adminTokensList.innerHTML = '<div class="empty">' + i18n.t('auth.no_tokens') + '</div>';
            return;
        }
        adminTokensList.innerHTML = '<table class="users-table">'
            + '<thead><tr><th>' + i18n.t('table.user') + '</th><th>' + i18n.t('table.name') + '</th><th>' + i18n.t('table.created') + '</th><th>' + i18n.t('table.expires') + '</th><th></th></tr></thead>'
            + '<tbody>'
            + tokens.map(function (t) {
                return '<tr>'
                    + '<td>' + escapeHtml(t.username || '—') + '</td>'
                    + '<td>' + escapeHtml(t.name || i18n.t('auth.unnamed_token')) + '</td>'
                    + '<td>' + escapeHtml(formatIsoTimestamp(t.created_at) || String(t.created_at || '').substring(0, 10)) + '</td>'
                    + '<td>' + escapeHtml(formatIsoTimestamp(t.expires_at) || String(t.expires_at || '').substring(0, 10)) + '</td>'
                    + '<td class="actions-cell"><button class="ghost danger-text" data-admin-delete-token="' + t.id + '">' + i18n.t('common.revoke') + '</button></td>'
                    + '</tr>';
            }).join('')
            + '</tbody></table>';
    }

    if (adminTokensList) {
        adminTokensList.addEventListener('click', function (e) {
            var tokenId = e.target.dataset.adminDeleteToken;
            if (tokenId) {
                showConfirm({ title: i18n.t('confirm.revoke_token_title'), message: i18n.t('confirm.revoke_token_message'), ok: i18n.t('confirm.revoke_token_ok') }).then(function (confirmed) {
                    if (!confirmed) return;
                    fetchJson('/auth/tokens/' + tokenId, { method: 'DELETE' })
                        .then(function () { refreshAdminTokens(); showToast(i18n.t('toast.token_revoked')); })
                        .catch(function (err) { showToast(err.message, 'error'); });
                });
            }
        });
    }

    async function refreshSummary() {
        const payload = await fetchJson('/config');
        renderMeta(payload);
        applySummaryToForms(payload);
        renderWatchers(payload.watchers || []);
    }

    async function refreshJobs() {
        const payload = await fetchJson('/jobs');
        renderJobs(payload.jobs || []);
    }

    async function refreshAll() {
        try {
            await Promise.all([refreshSummary(), refreshJobs()]);
        } catch (error) {
            setFormStatus(error.message, 'error');
        }
    }

    form.addEventListener('submit', async function (event) {
        event.preventDefault();
        submitButton.disabled = true;
        setFormStatus(i18n.t('jobs.queueing'));

        const formData = new FormData(form);
        const presetId = formData.get('preset_id') || '';
        const payload = {
            input_file: formData.get('input_file'),
            input_kind: formData.get('input_kind') || 'file',
            recursive: formData.get('recursive') === 'on',
            filter_pattern: formData.get('filter_pattern') || '',
            output_dir: formData.get('output_dir'),
            codec: presetId ? null : formData.get('codec'),
            encode_speed: presetId ? null : formData.get('encode_speed'),
            preset_id: presetId || null,
            audio_passthrough: formData.get('audio_passthrough') === 'on',
            delete_source: formData.get('delete_source') === 'on',
            force: formData.get('force') === 'on',
            verbose: formData.get('verbose') === 'on',
            submitted_display: buildSubmittedDisplay(new Date()),
        };

        try {
            const response = await fetchJson('/jobs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            form.reset();
            clearInputSelection();
            resetDirtyTracker('job-form');
            setFormStatus(response.message || i18n.t('toast.job_queued', { id: response.id }), 'ok');
            await refreshJobs();
        } catch (error) {
            setFormStatus(error.message, 'error');
            submitButton.disabled = false;
        }
    });

    settingsForm.addEventListener('submit', async function (event) {
        event.preventDefault();
        settingsButton.disabled = true;
        setStatus(settingsStatus, i18n.t('toast.saving_settings'));
        syncAllowedRootsField();

        const formData = new FormData(settingsForm);
        const payload = {
            allowed_roots: state.allowedRoots.slice(),
            worker_count: Number(formData.get('worker_count') || 1),
            gpu_devices: formData.get('gpu_devices') || '',
            default_job_settings: {
                output_dir: formData.get('default_output_dir'),
                codec: formData.get('default_codec'),
                encode_speed: formData.get('default_encode_speed'),
                audio_passthrough: formData.get('default_audio_passthrough') === 'on',
                delete_source: formData.get('default_delete_source') === 'on',
                force: formData.get('default_force') === 'on',
                verbose: formData.get('default_verbose') === 'on',
                default_preset_id: formData.get('default_preset_id') || '',
            },
        };

        try {
            await fetchJson('/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            setStatus(settingsStatus, i18n.t('toast.settings_saved'), 'ok');
            resetDirtyTracker('settings-form');
            await refreshSummary();
        } catch (error) {
            setStatus(settingsStatus, error.message, 'error');
            settingsButton.disabled = false;
        }
    });

    // Save log settings
    var saveLogSettingsBtn = document.getElementById('save-log-settings');
    var logSettingsStatus = document.getElementById('log-settings-status');
    if (saveLogSettingsBtn) {
        saveLogSettingsBtn.addEventListener('click', async function () {
            var logLevelEl = document.getElementById('settings-log-level');
            var logRetentionEl = document.getElementById('settings-log-retention');
            var payload = {
                log_level: logLevelEl ? logLevelEl.value : 'INFO',
                log_retention_days: logRetentionEl ? Number(logRetentionEl.value) : 30,
            };
            setStatus(logSettingsStatus, i18n.t('toast.saving'));
            try {
                await fetchJson('/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                setStatus(logSettingsStatus, i18n.t('toast.log_settings_saved'), 'ok');
                resetDirtyTracker('log-settings');
            } catch (err) {
                setStatus(logSettingsStatus, err.message, 'error');
            }
        });
    }

    watcherForm.addEventListener('submit', async function (event) {
        event.preventDefault();
        watcherButton.disabled = true;
        var isEditing = state.editingWatcherId !== null;
        setStatus(watcherStatus, isEditing ? 'Updating watcher...' : 'Adding watcher...');

        const formData = new FormData(watcherForm);
        const presetIdW = formData.get('preset_id') || '';
        const codecVal = presetIdW ? '' : (formData.get('codec') || '');
        const speedVal = presetIdW ? '' : (formData.get('encode_speed') || '');
        const payload = {
            directory: formData.get('directory'),
            recursive: formData.get('recursive') === 'on',
            poll_interval: Number(formData.get('poll_interval') || 5),
            settle_time: Number(formData.get('settle_time') || 30),
            delete_source: formData.get('delete_source') === 'on',
            output_dir: (formData.get('output_dir') || '').trim(),
            codec: codecVal,
            encode_speed: speedVal,
            preset_id: presetIdW || null,
            audio_passthrough: formData.get('audio_passthrough') === 'on' ? true : null,
            force: formData.get('force') === 'on' ? true : null,
        };

        try {
            if (isEditing) {
                await fetchJson(`/watchers/${state.editingWatcherId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                setStatus(watcherStatus, i18n.t('toast.watcher_updated'), 'ok');
            } else {
                await fetchJson('/watchers', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                setStatus(watcherStatus, i18n.t('toast.watcher_added'), 'ok');
            }
            resetWatcherForm();
            await refreshSummary();
        } catch (error) {
            setStatus(watcherStatus, error.message, 'error');
            watcherButton.disabled = false;
        }
    });

    cancelEditWatcherButton.addEventListener('click', function () {
        resetWatcherForm();
        setStatus(watcherStatus, '', '');
    });

    refreshButton.addEventListener('click', function () {
        refreshAll();
    });

    jobsFilterText.addEventListener('input', function () {
        renderJobs(state.lastJobs);
    });

    jobsFilterStatus.addEventListener('change', function () {
        renderJobs(state.lastJobs);
    });

    var jobsFilterClear = document.getElementById('jobs-filter-clear');
    if (jobsFilterClear) {
        jobsFilterClear.addEventListener('click', function () {
            jobsFilterText.value = '';
            jobsFilterStatus.value = '';
            renderJobs(state.lastJobs);
        });
    }

    toggleExpandJobsButton.addEventListener('click', function () {
        var details = jobsContainer.querySelectorAll('.jt-detail-row');
        var anyOpen = false;
        Array.prototype.forEach.call(details, function (row) {
            if (!row.classList.contains('jt-detail-hidden')) anyOpen = true;
        });
        var collapse = anyOpen;
        state.expandedJobs = {};
        Array.prototype.forEach.call(details, function (row) {
            row.classList.toggle('jt-detail-hidden', collapse);
            var jobId = row.dataset.detailFor;
            if (jobId) state.expandedJobs[jobId] = !collapse;
        });
        persistExpandedJobs();
        updateToggleExpandButton();
    });

    browseInputFileButton.addEventListener('click', function () {
        openPathBrowser({
            target: 'input_file',
            selection: 'file',
            scope: 'allowed',
            path: inputFileField.value || '',
            eyebrow: '',
            title: i18n.t('browser.title_select_file'),
        });
    });

    browseInputDirectoryButton.addEventListener('click', function () {
        openPathBrowser({
            target: 'input_directory',
            selection: 'directory',
            scope: 'allowed',
            path: inputKindField.value === 'directory' ? inputFileField.value || '' : '',
            eyebrow: '',
            title: i18n.t('browser.title_choose_folder'),
        });
    });

    clearInputFileButton.addEventListener('click', function () {
        clearInputSelection();
    });

    addAllowedRootButton.addEventListener('click', function () {
        openPathBrowser({
            target: 'allowed_root',
            selection: 'directory',
            scope: 'all',
            path: '',
            eyebrow: '',
            title: i18n.t('browser.title_add_root'),
        });
    });

    browseWatcherDirectoryButton.addEventListener('click', function () {
        openPathBrowser({
            target: 'watcher_directory',
            selection: 'directory',
            scope: 'allowed',
            path: watcherDirectoryField.value || '',
            eyebrow: '',
            title: i18n.t('browser.title_watcher_source'),
        });
    });

    clearWatcherDirectoryButton.addEventListener('click', function () {
        setWatcherDirectory('');
    });

    browseWatcherOutputDirButton.addEventListener('click', function () {
        openPathBrowser({
            target: 'watcher_output_directory',
            selection: 'directory',
            scope: 'all',
            path: watcherOutputDirField.value || '',
            eyebrow: '',
            title: i18n.t('browser.title_watcher_output'),
        });
    });

    clearWatcherOutputDirButton.addEventListener('click', function () {
        setWatcherOutputDir('');
    });

    browseOutputDirButton.addEventListener('click', function () {
        openPathBrowser({
            target: 'output_directory',
            selection: 'directory',
            scope: 'all',
            path: outputDirField.value || '',
            eyebrow: '',
            title: i18n.t('browser.title_select_dest'),
        });
    });

    clearOutputDirButton.addEventListener('click', function () {
        outputDirField.value = '';
        outputDirField.dispatchEvent(new Event('change', { bubbles: true }));
    });

    browseDefaultOutputDirButton.addEventListener('click', function () {
        openPathBrowser({
            target: 'default_output_directory',
            selection: 'directory',
            scope: 'all',
            path: defaultOutputDirField.value || '',
            eyebrow: '',
            title: i18n.t('browser.title_default_dest'),
        });
    });

    clearDefaultOutputDirButton.addEventListener('click', function () {
        defaultOutputDirField.value = '';
        defaultOutputDirField.dispatchEvent(new Event('change', { bubbles: true }));
    });

    browserUpButton.addEventListener('click', function () {
        if (state.browser.parent || state.browser.currentPath) {
            loadBrowserPath(state.browser.parent, { resetFilter: true, focusFilter: true });
        }
    });

    browserShowHidden.addEventListener('change', function () {
        state.browser.showHidden = browserShowHidden.checked;
        loadBrowserPath(state.browser.currentPath || '', { resetFilter: false, focusFilter: true });
    });

    browserFilter.addEventListener('input', function () {
        state.browser.filterQuery = browserFilter.value || '';
        renderBrowserEntries();
    });

    browserSelectCurrentButton.addEventListener('click', function () {
        if (!state.browser.currentPath) {
            return;
        }
        selectBrowserPath(state.browser.currentPath);
    });

    closeBrowserButton.addEventListener('click', function () {
        closePathBrowser();
    });

    Array.prototype.forEach.call(
        document.querySelectorAll('[data-close-browser]'),
        function (element) {
            element.addEventListener('click', function () {
                closePathBrowser();
            });
        }
    );

    /* ── Sidebar Events ── */

    sidebarToggle.addEventListener('click', function () {
        var isOpen = sidebar.classList.toggle('open');
        sidebarOverlay.hidden = !isOpen;
    });

    sidebarOverlay.addEventListener('click', function () {
        closeSidebar();
    });

    window.addEventListener('hashchange', function () {
        navigateTo(getPageFromHash());
    });

    scheduleEnabled.addEventListener('change', function () {
        updateScheduleSections();
    });

    scheduleMode.addEventListener('change', function () {
        updateScheduleSections();
    });

    priceProvider.addEventListener('change', function () {
        updatePriceSections();
        if (priceProvider.value) {
            loadPriceChart();
        }
    });

    priceStrategy.addEventListener('change', function () {
        updatePriceSections();
    });

    addScheduleRuleButton.addEventListener('click', function () {
        state.scheduleRules.push(makeDefaultRule());
        renderScheduleRules();
        // Mark schedule as dirty since rules changed
        if (saveScheduleButton) saveScheduleButton.disabled = false;
    });

    saveScheduleButton.addEventListener('click', function () {
        saveSchedule();
    });

    document.addEventListener('keydown', function (event) {
        if (browserModal.hidden || event.altKey || event.ctrlKey || event.metaKey) {
            return;
        }

        if (event.key === 'Escape') {
            event.preventDefault();
            closePathBrowser();
            return;
        }

        if (event.key === 'ArrowDown') {
            event.preventDefault();
            moveBrowserSelection(1);
            return;
        }

        if (event.key === 'ArrowUp') {
            event.preventDefault();
            moveBrowserSelection(-1);
            return;
        }

        if (event.key !== 'Enter') {
            return;
        }

        if (event.target && typeof event.target.closest === 'function'
            && event.target.closest('button, select, textarea, input[type="checkbox"]')) {
            return;
        }

        event.preventDefault();
        activateBrowserSelection();
    });

    // Arrow Down from filter input jumps focus to first job row
    // Arrow Right from filter input jumps focus to clear button
    jobsFilterText.addEventListener('keydown', function (event) {
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            if (state.queueJobIds.length) {
                state.activeQueueJobId = state.queueJobIds[0];
                updateActiveQueueSelection();
                scrollActiveQueueJobIntoView();
                jobsFilterText.blur();
            }
        }
        if (event.key === 'ArrowRight') {
            var pos = jobsFilterText.selectionStart;
            if (pos === jobsFilterText.value.length) {
                event.preventDefault();
                jobsFilterClear.focus();
            }
        }
    });

    // Left Arrow from clear button returns to filter input
    // Down Arrow from clear button jumps to first job row
    jobsFilterClear.addEventListener('keydown', function (event) {
        if (event.key === 'ArrowLeft') {
            event.preventDefault();
            jobsFilterText.focus();
        }
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            if (state.queueJobIds.length) {
                state.activeQueueJobId = state.queueJobIds[0];
                updateActiveQueueSelection();
                scrollActiveQueueJobIntoView();
                jobsFilterClear.blur();
            }
        }
    });

    document.addEventListener('keydown', function (event) {
        if (!browserModal.hidden || !confirmModal.hidden || event.altKey || event.ctrlKey || event.metaKey) {
            return;
        }

        // Only handle queue keys when the activity page is visible
        var activityPage = document.getElementById('page-activity');
        if (!activityPage || activityPage.hidden) return;

        if (isInteractiveTarget(event.target)) {
            return;
        }

        if (event.key === 'ArrowDown') {
            event.preventDefault();
            moveQueueSelection(1);
            return;
        }

        if (event.key === 'ArrowUp') {
            event.preventDefault();
            // If on the first row, jump back to the filter input
            var firstId = state.queueJobIds.length ? state.queueJobIds[0] : '';
            if (state.activeQueueJobId === firstId) {
                jobsFilterText.focus();
            } else {
                moveQueueSelection(-1);
            }
            return;
        }

        if (event.key === 'ArrowRight') {
            event.preventDefault();
            if (state.activeQueueJobId) {
                var dr = jobsContainer.querySelector('[data-detail-for="' + state.activeQueueJobId + '"]');
                if (dr && dr.classList.contains('jt-detail-hidden')) {
                    dr.classList.remove('jt-detail-hidden');
                    state.expandedJobs[state.activeQueueJobId] = true;
                    persistExpandedJobs();
                    updateToggleExpandButton();
                }
            }
            return;
        }

        if (event.key === 'ArrowLeft') {
            event.preventDefault();
            if (state.activeQueueJobId) {
                var dr = jobsContainer.querySelector('[data-detail-for="' + state.activeQueueJobId + '"]');
                if (dr && !dr.classList.contains('jt-detail-hidden')) {
                    dr.classList.add('jt-detail-hidden');
                    state.expandedJobs[state.activeQueueJobId] = false;
                    persistExpandedJobs();
                    updateToggleExpandButton();
                }
            }
            return;
        }

        if (event.key === 'Enter') {
            event.preventDefault();
            if (state.queueJobIds.length) {
                toggleActiveQueueJob();
            }
            return;
        }

        if (event.key === ' ') {
            event.preventDefault();
            if (state.activeQueueJobId) {
                var isSelected = state.selectedJobs.has(state.activeQueueJobId);
                toggleJobSelection(state.activeQueueJobId, !isSelected);
                var cb = jobsContainer.querySelector('.jt-select-cb[data-select-job="' + state.activeQueueJobId + '"]');
                if (cb) cb.checked = !isSelected;
            }
            return;
        }

        if (event.key === 'Delete') {
            event.preventDefault();
            if (state.selectedJobs.size > 0) {
                bulkAction('clear');
                return;
            }
            if (!state.activeQueueJobId) return;
            var clearBtn = jobsContainer.querySelector('[data-clear-id="' + state.activeQueueJobId + '"]');
            if (clearBtn && !clearBtn.disabled) {
                clearBtn.click();
            }
            return;
        }

        if (event.key === 'PageUp') {
            event.preventDefault();
            if (state.queueJobIds.length) {
                state.activeQueueJobId = state.queueJobIds[0];
                updateActiveQueueSelection();
                scrollActiveQueueJobIntoView();
            }
            return;
        }

        if (event.key === 'PageDown') {
            event.preventDefault();
            if (state.queueJobIds.length) {
                state.activeQueueJobId = state.queueJobIds[state.queueJobIds.length - 1];
                updateActiveQueueSelection();
                scrollActiveQueueJobIntoView();
            }
            return;
        }
    });

    clearJobsButton.addEventListener('click', function (event) {
        event.stopPropagation();
        var menu = clearJobsDropdown.querySelector('.dropdown-menu');
        menu.hidden = !menu.hidden;
    });

    document.addEventListener('mousedown', function (event) {
        var menu = clearJobsDropdown.querySelector('.dropdown-menu');
        if (menu && !menu.hidden && !clearJobsDropdown.contains(event.target)) {
            menu.hidden = true;
        }
    });

    var clearModeLabels = { finished: 'finished', queued: 'queued', all: 'inactive' };
    Array.prototype.forEach.call(
        clearJobsDropdown.querySelectorAll('[data-clear-mode]'),
        function (button) {
            button.addEventListener('click', async function (event) {
                event.stopPropagation();
                var mode = button.dataset.clearMode;
                var label = clearModeLabels[mode] || 'inactive';

                clearJobsDropdown.querySelector('.dropdown-menu').hidden = true;

                try {
                    const result = await fetchJson(`/jobs?mode=${mode}`, { method: 'DELETE' });
                    const deletedCount = Number(result.deleted || 0);
                    setFormStatus(i18n.t('toast.removed_jobs', { count: deletedCount, label: label }), 'ok');
                    await refreshJobs();
                } catch (error) {
                    setFormStatus(error.message, 'error');
                }
            });
        }
    );

    // ── Bulk action button handlers ──
    if (bulkCancelBtn) bulkCancelBtn.addEventListener('click', function () { bulkAction('cancel'); });
    if (bulkRetryBtn) bulkRetryBtn.addEventListener('click', function () { bulkAction('retry'); });
    if (bulkClearBtn) bulkClearBtn.addEventListener('click', function () { bulkAction('clear'); });
    if (bulkDeselectBtn) bulkDeselectBtn.addEventListener('click', function () {
        state.selectedJobs.clear();
        var cbs = jobsContainer.querySelectorAll('.jt-select-cb');
        cbs.forEach(function (cb) { cb.checked = false; });
        updateBulkActionsBar();
    });

    themeSelect.addEventListener('change', function () {
        applyTheme(themeSelect.value);
        persistTheme(themeSelect.value);
        // Sync user settings theme selector
        if (userSettingsTheme) userSettingsTheme.value = themeSelect.value;
    });

    // ── General Settings Save ──
    var generalSaveBtn = document.getElementById('general-settings-save');
    var generalSaveStatus = document.getElementById('general-settings-status');
    if (generalSaveBtn) {
        generalSaveBtn.addEventListener('click', async function () {
            var authEl = document.getElementById('general-auth-enabled');
            var dateEl = document.getElementById('general-date-format');
            var tzEl = document.getElementById('general-timezone');
            var portEl = document.getElementById('general-listen-port');
            var uploadDirEl = document.getElementById('general-upload-dir');
            var maxUploadEl = document.getElementById('general-max-upload-size');
            var payload = {
                auth_enabled: authEl ? authEl.checked : undefined,
                default_date_format: dateEl ? dateEl.value : undefined,
                display_timezone: tzEl ? tzEl.value.trim() : undefined,
                listen_port: portEl ? Number(portEl.value) : undefined,
                upload_dir: uploadDirEl ? uploadDirEl.value.trim() : undefined,
                max_upload_size_bytes: maxUploadEl ? Number(maxUploadEl.value || 0) * 1024 * 1024 : undefined,
            };
            var oldPort = Number(window.location.port) || (window.location.protocol === 'https:' ? 443 : 80);
            var newPort = portEl ? Number(portEl.value) : oldPort;
            var oldTz = state.displayTimezone || '';
            var newTz = tzEl ? tzEl.value.trim() : oldTz;
            generalSaveBtn.disabled = true;
            if (generalSaveStatus) setStatus(generalSaveStatus, '');
            try {
                var result = await fetchJson('/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (newPort !== oldPort) {
                    showToast(i18n.t('toast.port_changed', { port: newPort }), 'ok');
                    setTimeout(function () {
                        var url = window.location.protocol + '//' + window.location.hostname + ':' + newPort + window.location.pathname + window.location.hash;
                        window.location.href = url;
                    }, 2000);
                    return;
                }
                if (newTz !== oldTz) {
                    showToast(i18n.t('toast.general_saved'), 'ok');
                    setTimeout(function () { window.location.reload(); }, 1000);
                    return;
                }
                applySummaryToForms(result);
                renderMeta(result);
                if (generalSaveStatus) setStatus(generalSaveStatus, i18n.t('toast.saved'), 'ok');
                showToast(i18n.t('toast.general_saved'), 'ok');
            } catch (err) {
                if (generalSaveStatus) setStatus(generalSaveStatus, i18n.t('toast.error'), 'error');
                showToast(i18n.t('toast.general_failed'), 'error');
                generalSaveBtn.disabled = false;
            }
        });
    }

    // ── Binary Paths helpers ──
    var _binaryNames = ['HandBrakeCLI', 'mediainfo', 'mkvpropedit', 'mkvmerge'];

    function applyBinaryPaths(paths) {
        _binaryNames.forEach(function (name) {
            var el = document.getElementById('bin-' + name);
            if (el) {
                el.value = paths[name] || '';
                el.classList.toggle('input-missing', !paths[name]);
            }
        });
    }

    function updateMissingBinariesBanner(missing) {
        var banner = document.getElementById('banner-missing-binaries');
        if (banner) banner.hidden = !missing || missing.length === 0;
    }

    function collectBinaryPaths() {
        var paths = {};
        _binaryNames.forEach(function (name) {
            var el = document.getElementById('bin-' + name);
            if (el) paths[name] = el.value.trim();
        });
        return paths;
    }

    // ── Binary Paths Save ──
    var binSaveBtn = document.getElementById('binaries-settings-save');
    var binDetectBtn = document.getElementById('binaries-settings-detect');
    var binStatus = document.getElementById('binaries-settings-status');

    if (binSaveBtn) {
        binSaveBtn.addEventListener('click', async function () {
            binSaveBtn.disabled = true;
            if (binStatus) setStatus(binStatus, '');
            try {
                var result = await fetchJson('/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ binary_paths: collectBinaryPaths() }),
                });
                applySummaryToForms(result);
                renderMeta(result);
                if (binStatus) setStatus(binStatus, i18n.t('toast.saved'), 'ok');
                showToast(i18n.t('toast.binaries_saved'), 'ok');
            } catch (err) {
                if (binStatus) setStatus(binStatus, i18n.t('toast.error'), 'error');
                showToast(i18n.t('toast.binaries_failed'), 'error');
            } finally {
                binSaveBtn.disabled = false;
            }
        });
    }

    if (binDetectBtn) {
        binDetectBtn.addEventListener('click', async function () {
            binDetectBtn.disabled = true;
            if (binStatus) setStatus(binStatus, '');
            try {
                var result = await fetchJson('/config/detect-binaries', { method: 'POST' });
                applyBinaryPaths(result.binary_paths || {});
                updateMissingBinariesBanner(result.missing_binaries || []);
                if (binStatus) setStatus(binStatus, i18n.t('toast.binaries_detected'), 'ok');
                showToast(i18n.t('toast.binaries_detected'), 'ok');
            } catch (err) {
                if (binStatus) setStatus(binStatus, i18n.t('toast.error'), 'error');
                showToast(i18n.t('toast.binaries_detect_failed'), 'error');
            } finally {
                binDetectBtn.disabled = false;
            }
        });
    }

    releaseButton.addEventListener('click', async function () {
        if (state.release.update_in_progress) {
            return;
        }

        if (state.release.update_available) {
            const targetVersion = state.release.remote_version || 'latest';

            // Docker: show pull instructions instead of in-app upgrade
            if (state.release.runtime_environment && state.release.runtime_environment.toLowerCase().indexOf('docker') !== -1) {
                await showAlert({
                    title: i18n.t('release.docker_upgrade_title'),
                    message: i18n.t('release.docker_upgrade_message', { version: targetVersion }),
                    ok: i18n.t('release.docker_upgrade_ok'),
                });
                return;
            }

            const confirmed = await showConfirm({
                title: i18n.t('confirm.install_update_title'),
                message: i18n.t('confirm.install_update_message', { version: targetVersion }),
                ok: i18n.t('confirm.install_update_ok'),
            });
            if (!confirmed) {
                return;
            }

            releaseButton.disabled = true;
            releaseButton.dataset.busy = 'true';
            showToast(i18n.t('toast.installing_update', { version: targetVersion }));

            try {
                const payload = await fetchJson('/updates/upgrade', { method: 'POST' });
                renderReleaseControl(payload.update_info || {
                    local_version: state.release.local_version,
                    remote_version: targetVersion,
                    update_available: true,
                    changelog: state.release.changelog,
                    checked_at: state.release.checked_at,
                    last_error: '',
                    update_in_progress: true,
                });
                showToast(payload.message || i18n.t('toast.installing_update', { version: targetVersion }), 'ok', 0);
                waitForReleaseRestart(targetVersion);
            } catch (error) {
                renderReleaseControl(state.release);
                showToast(error.message, 'error');
            }
            return;
        }

        releaseButton.disabled = true;

        try {
            const payload = await fetchJson('/updates/check', { method: 'POST' });
            renderReleaseControl(payload);
            if (payload.last_error) {
                showToast(payload.last_error, 'error');
            } else if (payload.update_available) {
                showToast(i18n.t('toast.update_available', { local: payload.local_version, remote: payload.remote_version }), 'ok');
                // Force-refresh changelog so it picks up newer remote versions
                changelogLastFetched = 0;
                loadFullChangelog(true);
            } else {
                showToast(i18n.t('toast.already_up_to_date', { version: payload.local_version }), 'ok');
                // Also refresh changelog in case it was stale
                changelogLastFetched = 0;
                loadFullChangelog(true);
            }
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            if (!state.release.update_in_progress) {
                releaseButton.disabled = false;
                releaseButton.dataset.busy = 'false';
            }
        }
    });

    toggleAutoRefreshButton.addEventListener('click', function () {
        state.autoRefresh = !state.autoRefresh;
        updateAutoRefreshButton();
        if (state.autoRefresh) {
            scheduleRefresh();
        } else if (state.timerId) {
            clearInterval(state.timerId);
            state.timerId = null;
        }
    });

    function scheduleRefresh() {
        if (state.timerId) {
            clearInterval(state.timerId);
        }
        state.timerId = setInterval(function () {
            if (state.autoRefresh) {
                refreshJobs().catch(function (error) {
                    setFormStatus(error.message, 'error');
                });
            }
        }, 2000);
    }

    if (systemThemeQuery && typeof systemThemeQuery.addEventListener === 'function') {
        systemThemeQuery.addEventListener('change', function () {
            if (!getStoredTheme()) {
                applyTheme(getPreferredTheme());
            }
        });
    }

    applyTheme(getPreferredTheme());
    renderReleaseControl(state.release);
    clearInputSelection();
    setWatcherDirectory('');

    if (startupParams.get('notice')) {
        setFormStatus(startupParams.get('notice'), 'ok');
        history.replaceState(null, '', window.location.pathname + window.location.hash);
    } else if (startupParams.get('error')) {
        setFormStatus(startupParams.get('error'), 'error');
        history.replaceState(null, '', window.location.pathname + window.location.hash);
    }

    initCustomSelects();

    // ── Setup dirty tracking for all save/submit forms ──
    setupFormDirtyTracking('settings-form', settingsForm, settingsButton);
    setupFormDirtyTracking('watcher-form', watcherForm, watcherButton);
    setupFormDirtyTracking('smtp-form', document.getElementById('smtp-form'),
        document.querySelector('#smtp-form .primary[type="submit"]'));
    setupFormDirtyTracking('notif-form', document.getElementById('notif-form'),
        document.querySelector('#notif-form .primary[type="submit"]'));

    // Schedule: tracked by individual element IDs
    setupIdsDirtyTracking('schedule', [
        'schedule-enabled', 'schedule-mode', 'schedule-priority', 'schedule-pause-behavior',
        'price-provider', 'price-bidding-zone', 'price-entsoe-key',
        'price-strategy', 'price-threshold', 'price-cheapest-hours',
    ], saveScheduleButton);

    // General settings
    setupIdsDirtyTracking('general-settings', [
        'general-auth-enabled', 'general-date-format', 'general-timezone', 'general-listen-port',
        'general-upload-dir', 'general-max-upload-size',
    ], document.getElementById('general-settings-save'));

    // Log settings
    setupIdsDirtyTracking('log-settings', [
        'settings-log-level', 'settings-log-retention',
    ], document.getElementById('save-log-settings'));

    // Job form: the source path is required so it starts empty; enable submit only when form has content
    setupFormDirtyTracking('job-form', form, submitButton);

    document.addEventListener('mousedown', function (e) {
        if (!e.target.closest('.custom-select')) {
            closeAllCustomSelects();
        }
    });

    // ── Scroll-to-top button for Changelog page ──
    (function () {
        var contentEl = document.getElementById('content');
        var scrollBtn = document.getElementById('changelog-scroll-top');
        if (!contentEl || !scrollBtn) return;

        function onScroll() {
            var changelogPage = document.getElementById('page-system-changelog');
            if (!changelogPage || changelogPage.hidden) {
                scrollBtn.classList.remove('visible');
                return;
            }
            var scrollTop = contentEl.scrollTop || document.documentElement.scrollTop || 0;
            if (scrollTop > 120) {
                scrollBtn.classList.add('visible');
            } else {
                scrollBtn.classList.remove('visible');
            }
        }

        contentEl.addEventListener('scroll', onScroll);
        window.addEventListener('scroll', onScroll);

        scrollBtn.addEventListener('click', function () {
            contentEl.scrollTo({ top: 0, behavior: 'smooth' });
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }());

    /* ── Presets editor ── */
    var presetsState = {
        custom: [],
        official: [],
        officialGroups: [],
        editing: null,            // null = not editing; object = current preset draft
        loadedOfficial: false,
        quickAccess: [],
    };

    function presetEl(id) { return document.getElementById(id); }

    function categoryLabel(cat) {
        var key = 'settings.presets.category.' + (cat || 'other').toLowerCase().replace(/[^a-z0-9]+/g, '_');
        var translated = i18n.t(key);
        if (translated && translated !== key) return translated;
        return cat || i18n.t('settings.presets.category.other') || 'Other';
    }

    var BUILTIN_PRESETS = [
        { name: 'nvenc_h265', description: 'NVIDIA GPU H.265 encoder — best balance of speed and quality.', encoder: 'nvenc_h265', speeds: 'fast / normal / slow' },
        { name: 'nvenc_h264', description: 'NVIDIA GPU H.264 encoder — broad device compatibility.', encoder: 'nvenc_h264', speeds: 'fast / normal / slow' },
        { name: 'av1', description: 'AV1 software encoder — smallest files, very slow.', encoder: 'av1', speeds: 'fast / normal / slow' },
        { name: 'x265', description: 'CPU H.265 encoder — great quality, slower than NVENC.', encoder: 'x265', speeds: 'fast / normal / slow' },
    ];

    function renderBuiltinCard(preset) {
        var card = document.createElement('div');
        card.className = 'preset-card preset-card-readonly';
        var header = document.createElement('div');
        header.className = 'preset-card-header';
        var name = document.createElement('div');
        name.className = 'preset-card-name';
        name.textContent = preset.name;
        header.appendChild(name);
        card.appendChild(header);
        var desc = document.createElement('p');
        desc.className = 'preset-card-desc';
        desc.textContent = preset.description;
        card.appendChild(desc);
        var badges = document.createElement('div');
        badges.className = 'preset-card-badges';
        var bb = document.createElement('span');
        bb.className = 'preset-badge builtin';
        bb.textContent = i18n.t('settings.presets.builtin_badge') || 'Built-in';
        badges.appendChild(bb);
        var eb = document.createElement('span');
        eb.className = 'preset-badge';
        eb.textContent = preset.encoder;
        badges.appendChild(eb);
        if (preset.speeds) {
            var sb = document.createElement('span');
            sb.className = 'preset-badge';
            sb.textContent = preset.speeds;
            badges.appendChild(sb);
        }
        card.appendChild(badges);
        return card;
    }

    function renderCustomPresets() {
        var container = presetEl('custom-presets-container');
        if (!container) return;
        container.innerHTML = '';
        // Always show built-in quick-access presets as read-only cards first
        BUILTIN_PRESETS.forEach(function (bp) {
            container.appendChild(renderBuiltinCard(bp));
        });
        presetsState.custom.forEach(function (preset) {
            var card = document.createElement('div');
            card.className = 'preset-card';
            var header = document.createElement('div');
            header.className = 'preset-card-header';
            var name = document.createElement('div');
            name.className = 'preset-card-name';
            name.textContent = preset.name;
            header.appendChild(name);
            if (preset.base_preset) {
                var base = document.createElement('div');
                base.className = 'preset-card-base';
                base.textContent = '↳ ' + preset.base_preset;
                header.appendChild(base);
            }
            card.appendChild(header);
            if (preset.description) {
                var desc = document.createElement('p');
                desc.className = 'preset-card-desc';
                desc.textContent = preset.description;
                card.appendChild(desc);
            }
            var badges = document.createElement('div');
            badges.className = 'preset-card-badges';
            if (preset.quick_access) {
                var qb = document.createElement('span');
                qb.className = 'preset-badge quick';
                qb.textContent = i18n.t('settings.presets.quick_badge') || 'Quick access';
                badges.appendChild(qb);
            }
            var params = preset.params || {};
            var video = (params.video || {});
            if (video.encoder) {
                var enc = document.createElement('span');
                enc.className = 'preset-badge';
                enc.textContent = video.encoder;
                badges.appendChild(enc);
            }
            card.appendChild(badges);
            var actions = document.createElement('div');
            actions.className = 'preset-card-actions';
            var editBtn = document.createElement('button');
            editBtn.className = 'secondary small';
            editBtn.type = 'button';
            editBtn.textContent = i18n.t('settings.presets.edit') || 'Edit';
            editBtn.addEventListener('click', function () { openPresetEditor(preset); });
            actions.appendChild(editBtn);
            var exportBtn = document.createElement('button');
            exportBtn.className = 'ghost small';
            exportBtn.type = 'button';
            exportBtn.textContent = i18n.t('settings.presets.export') || 'Export';
            exportBtn.addEventListener('click', function () { exportPreset(preset.id); });
            actions.appendChild(exportBtn);
            var delBtn = document.createElement('button');
            delBtn.className = 'danger small';
            delBtn.type = 'button';
            delBtn.textContent = i18n.t('settings.presets.delete') || 'Delete';
            delBtn.addEventListener('click', function () { deletePreset(preset); });
            actions.appendChild(delBtn);
            card.appendChild(actions);
            container.appendChild(card);
        });
    }

    function renderOfficialPresets() {
        var container = presetEl('official-presets-container');
        if (!container) return;
        container.innerHTML = '';
        if (!presetsState.official.length) {
            var p = document.createElement('p');
            p.className = 'empty-state';
            p.textContent = i18n.t('settings.presets.no_official') || 'No official presets available.';
            container.appendChild(p);
            return;
        }
        // Group by category
        var groups = {};
        presetsState.official.forEach(function (preset) {
            var cat = preset.category || 'Other';
            if (!groups[cat]) groups[cat] = [];
            groups[cat].push(preset);
        });
        Object.keys(groups).sort().forEach(function (cat) {
            var details = document.createElement('details');
            details.className = 'preset-group';
            var summary = document.createElement('summary');
            var label = document.createElement('span');
            label.textContent = categoryLabel(cat);
            var count = document.createElement('span');
            count.className = 'preset-group-count';
            count.textContent = ' (' + groups[cat].length + ')';
            label.appendChild(count);
            summary.appendChild(label);
            details.appendChild(summary);
            var body = document.createElement('div');
            body.className = 'preset-group-body';
            groups[cat].forEach(function (preset) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'preset-group-item';
                var n = document.createElement('div');
                n.className = 'preset-group-item-name';
                n.textContent = preset.name;
                btn.appendChild(n);
                if (preset.description) {
                    var d = document.createElement('p');
                    d.className = 'preset-group-item-desc';
                    d.textContent = preset.description;
                    btn.appendChild(d);
                }
                btn.addEventListener('click', function () { cloneOfficialPreset(preset); });
                body.appendChild(btn);
            });
            details.appendChild(body);
            container.appendChild(details);
        });
    }

    function emptyDraft() {
        return {
            id: null,
            name: '',
            description: '',
            quick_access: false,
            base_preset: '',
            params: {
                video: { encoder: 'nvenc_h265', quality_mode: 'crf', quality_value: 22, encoder_preset: '', max_width: 0, max_height: 0, framerate_mode: 'same-as-source', framerate_value: 0, extra_options: '' },
                audio: { mode: 'passthrough', encoder: 'opus', bitrate: 0, mixdown: 'auto' },
                container: { format: 'mkv', chapter_markers: true },
                subtitles: { mode: 'all' },
                filters: { deinterlace: 'off', denoise: 'off' },
            },
        };
    }

    // Map HandBrake official preset encoder names to our curated select values.
    var _hbEncoderMap = {
        'x264': 'x264', 'x265': 'x265', 'x265_10bit': 'x265_10bit',
        'nvenc_h264': 'nvenc_h264', 'nvenc_h265': 'nvenc_h265',
        'nvenc_h265_10bit': 'nvenc_h265_10bit',
        'svt_av1': 'av1', 'svt_av1_10bit': 'av1',
        'nvenc_av1': 'av1_nvenc', 'qsv_av1': 'av1_qsv',
        'vp9': 'vp9', 'VP9': 'vp9', 'vp9_10bit': 'vp9',
        'qsv_h264': 'qsv_h264', 'qsv_h265': 'qsv_h265',
        'vt_h264': 'vt_h264', 'vt_h265': 'vt_h265',
        'mpeg2': 'x264', 'mpeg4': 'x264', 'theora': 'vp9',
    };
    var _hbContainerMap = {
        'av_mkv': 'mkv', 'av_mp4': 'mp4', 'mkv': 'mkv', 'mp4': 'mp4',
    };
    var _hbAudioMap = {
        'av_aac': 'aac', 'fdk_aac': 'aac', 'fdk_haac': 'aac',
        'copy:aac': 'aac', 'opus': 'opus', 'ac3': 'ac3',
        'copy:ac3': 'ac3', 'eac3': 'eac3', 'copy:eac3': 'eac3',
        'flac': 'opus', 'mp3': 'aac', 'vorbis': 'opus',
        'copy': 'opus',
    };

    // Infer encoder from official preset name when backend has no metadata.
    function _inferEncoderFromName(name) {
        if (!name) return '';
        var n = name.toLowerCase();
        if (/\bvp9\b/.test(n)) return 'vp9';
        if (/\bav1\b/.test(n)) return 'av1';
        if (/\bh\.?264\b|\bx264\b/.test(n)) return 'x264';
        if (/\bh\.?265\b|\bx265\b|\bhevc\b/.test(n)) return 'x265';
        return '';
    }
    function _inferContainerFromName(name) {
        if (!name) return '';
        var n = name.toLowerCase();
        if (/\bmkv\b|\bmatroska\b/.test(n)) return 'mkv';
        if (/\bmp4\b/.test(n)) return 'mp4';
        if (/\bwebm\b/.test(n)) return 'mkv';
        return '';
    }

    function openPresetEditor(preset) {
        var draft;
        if (preset && preset.id) {
            draft = JSON.parse(JSON.stringify(preset));
        } else if (preset && preset._fromCodec) {
            // Pre-filled from a built-in codec selection
            draft = preset;
            delete draft._fromCodec;
        } else if (preset && preset.params) {
            // Clone of a custom preset (has full params already)
            draft = JSON.parse(JSON.stringify(preset));
        } else if (preset) {
            // Cloning from official: map official fields into a draft
            draft = emptyDraft();
            draft.name = (preset.name || '') + ' (copy)';
            draft.description = preset.description || '';
            draft.base_preset = preset.name || '';
            // Map video encoder (from metadata, then fall back to name inference)
            var hbEnc = (preset.video_encoder || '').trim();
            if (hbEnc && _hbEncoderMap[hbEnc]) {
                draft.params.video.encoder = _hbEncoderMap[hbEnc];
            } else {
                var inferred = _inferEncoderFromName(preset.name);
                if (inferred) draft.params.video.encoder = inferred;
            }
            // Map quality
            if (preset.video_bitrate && Number(preset.video_bitrate) > 0) {
                draft.params.video.quality_mode = 'abr';
                draft.params.video.quality_value = Number(preset.video_bitrate);
            } else if (preset.video_quality != null && Number(preset.video_quality) > 0) {
                draft.params.video.quality_mode = 'crf';
                draft.params.video.quality_value = Number(preset.video_quality);
            }
            // Map container (from metadata, then fall back to name inference)
            var hbCont = (preset.container || '').trim();
            if (hbCont && _hbContainerMap[hbCont]) {
                draft.params.container.format = _hbContainerMap[hbCont];
            } else {
                var inferredCont = _inferContainerFromName(preset.name);
                if (inferredCont) draft.params.container.format = inferredCont;
            }
            // Map audio encoder (use first entry if comma-separated)
            var hbAudio = (preset.audio_encoder || '').split(',')[0].trim();
            if (hbAudio && _hbAudioMap[hbAudio]) {
                draft.params.audio.encoder = _hbAudioMap[hbAudio];
            }
        } else {
            draft = emptyDraft();
        }
        presetsState.editing = draft;
        // Clear stale wantedValue on all selects inside the editor so that
        // programmatic .value assignments below are not overridden by
        // syncTrigger reading a leftover wantedValue from a previous session.
        var editorContainer = presetEl('presets-editor-view');
        if (editorContainer) {
            Array.prototype.forEach.call(
                editorContainer.querySelectorAll('select[data-customized]'),
                function (sel) { delete sel.dataset.wantedValue; }
            );
        }
        // Fill form
        presetEl('preset-field-name').value = draft.name || '';
        presetEl('preset-field-description').value = draft.description || '';
        presetEl('preset-field-quick-access').checked = !!draft.quick_access;
        presetEl('preset-field-base').value = draft.base_preset || '';
        var v = draft.params.video || {};
        presetEl('preset-field-encoder').value = v.encoder || 'nvenc_h265';
        presetEl('preset-field-quality-mode').value = v.quality_mode || 'crf';
        presetEl('preset-field-quality-value').value = (v.quality_value != null ? v.quality_value : 22);
        presetEl('preset-field-encoder-preset').value = v.encoder_preset || '';
        presetEl('preset-field-max-width').value = v.max_width || 0;
        presetEl('preset-field-max-height').value = v.max_height || 0;
        presetEl('preset-field-framerate-mode').value = v.framerate_mode || 'same-as-source';
        presetEl('preset-field-framerate-value').value = v.framerate_value || 0;
        presetEl('preset-field-extra-options').value = v.extra_options || '';
        var a = draft.params.audio || {};
        presetEl('preset-field-audio-mode').value = a.mode || 'passthrough';
        presetEl('preset-field-audio-encoder').value = a.encoder || 'opus';
        presetEl('preset-field-audio-bitrate').value = a.bitrate || 0;
        presetEl('preset-field-audio-mixdown').value = a.mixdown || 'auto';
        var c = draft.params.container || {};
        presetEl('preset-field-container-format').value = c.format || 'mkv';
        presetEl('preset-field-chapter-markers').checked = c.chapter_markers !== false;
        presetEl('preset-field-subtitles').value = (draft.params.subtitles || {}).mode || 'all';
        var f = draft.params.filters || {};
        presetEl('preset-field-deinterlace').value = f.deinterlace || 'off';
        presetEl('preset-field-denoise').value = f.denoise || 'off';
        // Update title and button visibility
        var titleEl = presetEl('preset-editor-title');
        if (titleEl) {
            titleEl.textContent = draft.id
                ? (i18n.t('settings.presets.editor_title_edit') || 'Edit preset')
                : (i18n.t('settings.presets.editor_title_new') || 'New preset');
        }
        presetEl('preset-export-button').hidden = !draft.id;
        presetEl('preset-delete-button').hidden = !draft.id;
        presetEl('preset-editor-status').textContent = '';
        presetEl('presets-list-view').hidden = true;
        presetEl('presets-editor-view').hidden = false;
        syncAllCustomSelects();
    }

    function closePresetEditor() {
        presetsState.editing = null;
        presetEl('presets-editor-view').hidden = true;
        presetEl('presets-list-view').hidden = false;
    }

    function collectPresetFromForm() {
        var draft = presetsState.editing || emptyDraft();
        draft.name = presetEl('preset-field-name').value.trim();
        draft.description = presetEl('preset-field-description').value.trim();
        draft.quick_access = presetEl('preset-field-quick-access').checked;
        draft.params = {
            video: {
                encoder: presetEl('preset-field-encoder').value,
                quality_mode: presetEl('preset-field-quality-mode').value,
                quality_value: parseFloat(presetEl('preset-field-quality-value').value) || 0,
                encoder_preset: presetEl('preset-field-encoder-preset').value.trim(),
                max_width: parseInt(presetEl('preset-field-max-width').value, 10) || 0,
                max_height: parseInt(presetEl('preset-field-max-height').value, 10) || 0,
                framerate_mode: presetEl('preset-field-framerate-mode').value,
                framerate_value: parseFloat(presetEl('preset-field-framerate-value').value) || 0,
                extra_options: presetEl('preset-field-extra-options').value.trim(),
            },
            audio: {
                mode: presetEl('preset-field-audio-mode').value,
                encoder: presetEl('preset-field-audio-encoder').value,
                bitrate: parseInt(presetEl('preset-field-audio-bitrate').value, 10) || 0,
                mixdown: presetEl('preset-field-audio-mixdown').value,
            },
            container: {
                format: presetEl('preset-field-container-format').value,
                chapter_markers: presetEl('preset-field-chapter-markers').checked,
            },
            subtitles: { mode: presetEl('preset-field-subtitles').value },
            filters: {
                deinterlace: presetEl('preset-field-deinterlace').value,
                denoise: presetEl('preset-field-denoise').value,
            },
        };
        return draft;
    }

    async function savePreset() {
        var draft = collectPresetFromForm();
        if (!draft.name) {
            setStatus(presetEl('preset-editor-status'), i18n.t('settings.presets.error.name_required') || 'Name is required.', 'error');
            return;
        }
        var body = {
            name: draft.name,
            description: draft.description,
            quick_access: draft.quick_access,
            base_preset: draft.base_preset || null,
            params: draft.params,
        };
        try {
            if (draft.id) {
                await fetchJson('/presets/' + encodeURIComponent(draft.id), {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                showToast(i18n.t('settings.presets.toast.updated') || 'Preset updated', 'ok');
            } else {
                await fetchJson('/presets', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                showToast(i18n.t('settings.presets.toast.created') || 'Preset created', 'ok');
            }
            closePresetEditor();
            await refreshCustomPresets();
            await refreshQuickAccessPresets();
        } catch (err) {
            setStatus(presetEl('preset-editor-status'), err.message || String(err), 'error');
        }
    }

    async function deletePreset(preset) {
        if (!preset || !preset.id) return;
        var msg = (i18n.t('settings.presets.confirm.delete') || 'Delete preset "{name}"?').replace('{name}', preset.name);
        var confirmed = await showConfirm({
            title: i18n.t('settings.presets.confirm.delete_title') || 'Delete preset',
            message: msg,
            ok: i18n.t('settings.presets.confirm.delete_ok') || 'Delete',
        });
        if (!confirmed) return;
        try {
            await fetchJson('/presets/' + encodeURIComponent(preset.id), { method: 'DELETE' });
            showToast(i18n.t('settings.presets.toast.deleted') || 'Preset deleted', 'ok');
            if (presetsState.editing && presetsState.editing.id === preset.id) {
                closePresetEditor();
            }
            await refreshCustomPresets();
            await refreshQuickAccessPresets();
        } catch (err) {
            showToast(err.message || String(err), 'error');
        }
    }

    function exportPreset(id) {
        if (!id) return;
        var url = '/presets/' + encodeURIComponent(id) + '/export';
        if (state.auth.token) {
            // We need auth header → fetch + blob
            fetchJson(url).then(function (data) {
                var blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                var a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = 'preset-' + id + '.json';
                document.body.appendChild(a);
                a.click();
                a.remove();
                setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
            }).catch(function (err) {
                showToast(err.message || String(err), 'error');
            });
        } else {
            window.open(url, '_blank');
        }
    }

    async function importPreset(file) {
        if (!file) return;
        try {
            var text = await file.text();
            var doc = JSON.parse(text);
            await fetchJson('/presets/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ document: doc }),
            });
            showToast(i18n.t('settings.presets.toast.imported') || 'Preset imported', 'ok');
            await refreshCustomPresets();
            await refreshQuickAccessPresets();
        } catch (err) {
            showToast(err.message || String(err), 'error');
        }
    }

    function cloneOfficialPreset(preset) {
        openPresetEditor(preset);
    }

    async function refreshCustomPresets() {
        try {
            var resp = await fetchJson('/presets');
            presetsState.custom = (resp && resp.presets) || [];
            renderCustomPresets();
        } catch (err) {
            console.error('Failed to load custom presets', err);
        }
    }

    async function refreshOfficialPresets(forceRefresh) {
        var url = '/presets/official' + (forceRefresh ? '?refresh=1' : '');
        try {
            var resp = await fetchJson(url);
            // Backend returns {available, groups: [{category, presets: [...]}], error}
            // Flatten into a single array with category on each preset.
            var flat = [];
            var rawGroups = [];
            if (resp && resp.groups) {
                resp.groups.forEach(function (g) {
                    rawGroups.push({ name: g.category || 'Other', presets: g.presets || [] });
                    (g.presets || []).forEach(function (p) {
                        p.category = g.category || 'Other';
                        flat.push(p);
                    });
                });
            }
            presetsState.official = flat;
            presetsState.officialGroups = rawGroups;
            presetsState.loadedOfficial = true;
            renderOfficialPresets();
        } catch (err) {
            var container = presetEl('official-presets-container');
            if (container) {
                container.innerHTML = '';
                var p = document.createElement('p');
                p.className = 'empty-state';
                p.textContent = (i18n.t('settings.presets.error.official_load') || 'Could not load official presets: ') + (err.message || err);
                container.appendChild(p);
            }
        }
    }

    async function refreshQuickAccessPresets() {
        // Used to populate job/watcher preset selects
        try {
            var resp = await fetchJson('/presets');
            var all = (resp && resp.presets) || [];
            presetsState.quickAccess = all;
            populatePresetSelects(all);
        } catch (err) {
            // Silent
        }
    }

    function populatePresetSelects(presets) {
        ['job-preset-select', 'watcher-preset-select', 'settings-default-preset', 'upload-preset-select'].forEach(function (selectId) {
            var sel = document.getElementById(selectId);
            if (!sel) return;
            // Prefer a pending wanted value (set before options existed), then the current DOM value
            var current = sel.dataset.wantedValue || sel.value;
            // Keep the first (default) option, drop the rest
            while (sel.options.length > 1) sel.remove(1);
            // Group: quick-access first, then others (separator)
            var quick = presets.filter(function (p) { return p.quick_access; });
            var other = presets.filter(function (p) { return !p.quick_access; });
            if (quick.length) {
                var gQuick = document.createElement('optgroup');
                gQuick.label = i18n.t('settings.presets.optgroup.quick') || 'Quick access';
                quick.forEach(function (p) {
                    var o = document.createElement('option');
                    o.value = p.id; o.textContent = p.name;
                    gQuick.appendChild(o);
                });
                sel.appendChild(gQuick);
            }
            if (other.length) {
                var gOther = document.createElement('optgroup');
                gOther.label = i18n.t('settings.presets.optgroup.custom') || 'Custom presets';
                other.forEach(function (p) {
                    var o = document.createElement('option');
                    o.value = p.id; o.textContent = p.name;
                    gOther.appendChild(o);
                });
                sel.appendChild(gOther);
            }
            // Append official presets if the "show all" toggle is active for this select
            var showAllState = sel.dataset.showAllPresets === 'true';
            if (showAllState && presetsState.officialGroups && presetsState.officialGroups.length) {
                presetsState.officialGroups.forEach(function (group) {
                    var g = document.createElement('optgroup');
                    g.label = group.name || 'Official';
                    (group.presets || []).forEach(function (p) {
                        var o = document.createElement('option');
                        o.value = 'official:' + p.name;
                        o.textContent = p.name;
                        g.appendChild(o);
                    });
                    sel.appendChild(g);
                });
            }
            if (current) {
                sel.value = current;
                // Clear pending if it was successfully applied
                if (sel.value === current) delete sel.dataset.wantedValue;
            }
        });
        // Update default-hint labels on the first option of each select
        syncAllCustomSelects();
    }

    async function loadPresetsPage() {
        // Show dragons warning if not dismissed
        var dragonsEl = document.getElementById('presets-dragons-warning');
        if (dragonsEl) {
            var dismissed = false;
            try { dismissed = window.localStorage.getItem('clutch-presets-dragons-dismissed') === '1'; } catch (e) {}
            dragonsEl.hidden = dismissed;
            var cb = document.getElementById('presets-dragons-dismiss');
            if (cb && !cb.dataset.wired) {
                cb.dataset.wired = '1';
                cb.addEventListener('change', function () {
                    if (cb.checked) {
                        try { window.localStorage.setItem('clutch-presets-dragons-dismissed', '1'); } catch (e) {}
                        dragonsEl.hidden = true;
                    }
                });
            }
        }
        await refreshCustomPresets();
    }

    // Wire up preset editor controls
    (function wirePresetEditor() {
        // --- Wizard ---
        var wizardModal = document.getElementById('preset-wizard-modal');
        var wizardStepSource = document.getElementById('wizard-step-source');
        var wizardStepCodec = document.getElementById('wizard-step-codec');
        var wizardStepOfficial = document.getElementById('wizard-step-official');
        var wizardStepCustom = document.getElementById('wizard-step-custom');
        var wizardStepForm = document.getElementById('wizard-step-form');
        var wizardFormContainer = document.getElementById('wizard-form-container');
        var editorView = presetEl('presets-editor-view');
        var editorFieldsets = editorView ? Array.from(editorView.querySelectorAll('fieldset')) : [];

        function showWizardStep(step) {
            [wizardStepSource, wizardStepCodec, wizardStepOfficial, wizardStepCustom, wizardStepForm].forEach(function (s) {
                if (s) s.hidden = true;
            });
            if (step) step.hidden = false;
        }

        function openWizard() {
            if (!wizardModal) return;
            showWizardStep(wizardStepSource);
            wizardModal.hidden = false;
        }

        function closeWizard() {
            if (!wizardModal) return;
            wizardModal.hidden = true;
            // Move editor fieldsets back if they were in the wizard
            if (editorView && wizardFormContainer) {
                editorFieldsets.forEach(function (fs) { editorView.appendChild(fs); });
            }
        }

        function openEditorInWizard(preset) {
            // Fill form via existing logic
            openPresetEditor(preset);
            // Now move the editor fieldsets into the wizard form container
            if (wizardFormContainer && editorView) {
                wizardFormContainer.innerHTML = '';
                editorFieldsets.forEach(function (fs) { wizardFormContainer.appendChild(fs); });
            }
            // Hide the inline editor view (it was shown by openPresetEditor)
            if (editorView) editorView.hidden = true;
            presetEl('presets-list-view').hidden = false;
            // Hide export/delete buttons (new preset)
            presetEl('preset-export-button').hidden = true;
            presetEl('preset-delete-button').hidden = true;
            showWizardStep(wizardStepForm);
        }

        // "Create preset" button opens wizard
        var createBtn = document.getElementById('preset-create-wizard-btn');
        if (createBtn) createBtn.addEventListener('click', openWizard);

        // Close wizard
        var closeBtn = document.getElementById('wizard-close-btn');
        if (closeBtn) closeBtn.addEventListener('click', closeWizard);
        // Close on backdrop click
        if (wizardModal) {
            wizardModal.querySelector('.confirm-backdrop').addEventListener('click', closeWizard);
        }

        // Step 1: source cards
        if (wizardStepSource) {
            wizardStepSource.querySelectorAll('.wizard-card').forEach(function (card) {
                card.addEventListener('click', function () {
                    var source = card.dataset.wizardSource;
                    if (source === 'blank') {
                        openEditorInWizard(null);
                    } else if (source === 'codec') {
                        renderWizardCodecCards();
                        showWizardStep(wizardStepCodec);
                    } else if (source === 'official') {
                        renderWizardOfficialList();
                        showWizardStep(wizardStepOfficial);
                    } else if (source === 'custom') {
                        renderWizardCustomList();
                        showWizardStep(wizardStepCustom);
                    }
                });
            });
        }

        // Step 2a: codec cards
        function renderWizardCodecCards() {
            var container = document.getElementById('wizard-codec-cards');
            if (!container) return;
            container.innerHTML = '';
            BUILTIN_PRESETS.forEach(function (bp) {
                var card = document.createElement('button');
                card.type = 'button';
                card.className = 'wizard-card';
                card.innerHTML = '<span class="wizard-card-icon">🎬</span>' +
                    '<span class="wizard-card-title">' + escapeHtml(bp.name) + '</span>' +
                    '<span class="wizard-card-desc">' + escapeHtml(bp.description) + '</span>';
                card.addEventListener('click', function () {
                    var draft = emptyDraft();
                    draft.name = bp.name;
                    draft.params.video.encoder = bp.encoder;
                    draft._fromCodec = true;
                    openEditorInWizard(draft);
                });
                container.appendChild(card);
            });
        }

        // Back buttons
        var codecBackBtn = document.getElementById('wizard-codec-back');
        if (codecBackBtn) codecBackBtn.addEventListener('click', function () { showWizardStep(wizardStepSource); });
        var officialBackBtn = document.getElementById('wizard-official-back');
        if (officialBackBtn) officialBackBtn.addEventListener('click', function () { showWizardStep(wizardStepSource); });
        var customBackBtn = document.getElementById('wizard-custom-back');
        if (customBackBtn) customBackBtn.addEventListener('click', function () { showWizardStep(wizardStepSource); });
        var formBackBtn = document.getElementById('wizard-form-back');
        if (formBackBtn) formBackBtn.addEventListener('click', function () { showWizardStep(wizardStepSource); });

        // Step 2c: custom presets list
        function renderWizardCustomList() {
            var container = document.getElementById('wizard-custom-container');
            if (!container) return;
            container.innerHTML = '';
            var customs = presetsState.custom || [];
            if (!customs.length) {
                var p = document.createElement('p');
                p.className = 'empty-state';
                p.textContent = i18n.t('settings.presets.no_custom') || 'You have not created any custom presets yet.';
                container.appendChild(p);
                return;
            }
            customs.forEach(function (preset) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'preset-group-item';
                var n = document.createElement('div');
                n.className = 'preset-group-item-name';
                n.textContent = preset.name;
                btn.appendChild(n);
                if (preset.description) {
                    var d = document.createElement('p');
                    d.className = 'preset-group-item-desc';
                    d.textContent = preset.description;
                    btn.appendChild(d);
                }
                btn.addEventListener('click', function () {
                    // Clone: deep copy but clear id so it saves as new
                    var clone = JSON.parse(JSON.stringify(preset));
                    clone.id = null;
                    clone.name = preset.name + ' (copy)';
                    openEditorInWizard(clone);
                });
                container.appendChild(btn);
            });
        }

        // Step 2b: official presets list
        function renderWizardOfficialList() {
            var container = document.getElementById('wizard-official-container');
            if (!container) return;
            container.innerHTML = '';
            if (!presetsState.loadedOfficial) {
                var loading = document.createElement('p');
                loading.className = 'empty-state';
                loading.textContent = i18n.t('settings.presets.loading') || 'Loading official presets…';
                container.appendChild(loading);
                refreshOfficialPresets(false).then(function () { renderWizardOfficialList(); });
                return;
            }
            if (!presetsState.official.length) {
                var p = document.createElement('p');
                p.className = 'empty-state';
                p.textContent = i18n.t('settings.presets.no_official') || 'No official presets available.';
                container.appendChild(p);
                return;
            }
            // Group by category
            var groups = {};
            presetsState.official.forEach(function (preset) {
                var cat = preset.category || 'Other';
                if (!groups[cat]) groups[cat] = [];
                groups[cat].push(preset);
            });
            Object.keys(groups).sort().forEach(function (cat) {
                var details = document.createElement('details');
                details.className = 'preset-group';
                var summary = document.createElement('summary');
                var label = document.createElement('span');
                label.textContent = categoryLabel(cat);
                var count = document.createElement('span');
                count.className = 'preset-group-count';
                count.textContent = ' (' + groups[cat].length + ')';
                label.appendChild(count);
                summary.appendChild(label);
                details.appendChild(summary);
                var body = document.createElement('div');
                body.className = 'preset-group-body';
                groups[cat].forEach(function (preset) {
                    var btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'preset-group-item';
                    var n = document.createElement('div');
                    n.className = 'preset-group-item-name';
                    n.textContent = preset.name;
                    btn.appendChild(n);
                    if (preset.description) {
                        var d = document.createElement('p');
                        d.className = 'preset-group-item-desc';
                        d.textContent = preset.description;
                        btn.appendChild(d);
                    }
                    btn.addEventListener('click', function () { openEditorInWizard(preset); });
                    body.appendChild(btn);
                });
                details.appendChild(body);
                container.appendChild(details);
            });
        }

        // Wizard save button — delegates to the existing save logic
        var wizardSaveBtn = document.getElementById('wizard-form-save');
        if (wizardSaveBtn) wizardSaveBtn.addEventListener('click', async function () {
            await savePreset();
            // If save was successful, editing state is cleared
            if (!presetsState.editing) closeWizard();
        });

        // Keep existing save/cancel/export/delete for inline editor (editing existing presets)
        var saveBtn = presetEl('preset-save-button');
        if (saveBtn) saveBtn.addEventListener('click', savePreset);
        var cancelBtn = presetEl('preset-cancel-button');
        if (cancelBtn) cancelBtn.addEventListener('click', closePresetEditor);
        var exportBtn = presetEl('preset-export-button');
        if (exportBtn) exportBtn.addEventListener('click', function () {
            if (presetsState.editing && presetsState.editing.id) exportPreset(presetsState.editing.id);
        });
        var deleteBtn = presetEl('preset-delete-button');
        if (deleteBtn) deleteBtn.addEventListener('click', function () {
            if (presetsState.editing && presetsState.editing.id) {
                deletePreset(presetsState.editing);
            }
        });

        // Hide codec/speed rows in settings when a default preset is selected
        function toggleSettingsCodecSpeedRows(show) {
            var codecRow = document.getElementById('settings-default-codec-row');
            var speedRow = document.getElementById('settings-default-speed-row');
            if (codecRow) codecRow.hidden = !show;
            if (speedRow) speedRow.hidden = !show;
        }
        var settingsPresetSel = document.getElementById('settings-default-preset');
        if (settingsPresetSel) {
            settingsPresetSel.addEventListener('change', function () {
                toggleSettingsCodecSpeedRows(!settingsPresetSel.value);
            });
        }
        // Expose for applySummaryToForms
        window._clutchToggleSettingsCodecSpeedRows = toggleSettingsCodecSpeedRows;

        // "Show all presets" toggle checkboxes
        document.querySelectorAll('.show-all-presets-toggle input[type="checkbox"]').forEach(function (cb) {
            cb.addEventListener('change', async function () {
                var targetId = cb.dataset.target;
                var sel = document.getElementById(targetId);
                if (!sel) return;
                sel.dataset.showAllPresets = cb.checked ? 'true' : '';
                if (cb.checked && !presetsState.loadedOfficial) {
                    await refreshOfficialPresets(false);
                }
                populatePresetSelects(presetsState.quickAccess || []);
            });
        });

        // Hide codec/speed rows when a preset is selected (preset overrides them)
        ['job-preset-select', 'watcher-preset-select'].forEach(function (selId) {
            var sel = document.getElementById(selId);
            if (!sel) return;
            sel.addEventListener('change', function () {
                var form = sel.closest('form');
                if (!form) return;
                var hasPreset = !!sel.value;
                var codecSel = form.querySelector('select[name="codec"]');
                var speedSel = form.querySelector('select[name="encode_speed"]');
                if (codecSel) {
                    var codecRow = codecSel.closest('.field-row');
                    if (codecRow) codecRow.hidden = hasPreset;
                }
                if (speedSel) {
                    var speedRow = speedSel.closest('.field-row');
                    if (speedRow) speedRow.hidden = hasPreset;
                }
            });
        });

        // Hide upload codec/speed rows when a preset is selected
        var uploadPresetSel = document.getElementById('upload-preset-select');
        if (uploadPresetSel) {
            uploadPresetSel.addEventListener('change', function () {
                var hasPreset = !!uploadPresetSel.value;
                var codecRow = document.getElementById('upload-codec-row');
                var speedRow = document.getElementById('upload-speed-row');
                if (codecRow) codecRow.hidden = hasPreset;
                if (speedRow) speedRow.hidden = hasPreset;
            });
        }
    })();

    navigateTo(getPageFromHash());
    i18n.init().then(function () {
        // Sync language selectors with the detected/loaded language
        var currentLang = i18n.getLang();
        if (generalLanguageSelect) generalLanguageSelect.value = currentLang;
        if (userSettingsLanguageSelect) userSettingsLanguageSelect.value = currentLang;
        updateAutoRefreshButton();
        return initAuth();
    }).then(function () {
        navigateTo(getPageFromHash());
        refreshAll();
        refreshQuickAccessPresets();
        scheduleRefresh();
    }).catch(function () {
        // Auth redirect in progress — do not load dashboard data
    });

    // Debug helper: run __debugFakeUpgrade() in the browser console to
    // simulate the full update flow without actually installing anything.
    window.__debugFakeUpgrade = async function () {
        try {
            // Step 0: show a fake "update available" state with changelog
            // so we can verify it gets hidden once the upgrade starts.
            renderReleaseControl({
                local_version: state.release.local_version,
                remote_version: '999.0.0',
                update_available: true,
                changelog: '## v999.0.0\n- Fake changelog entry for testing\n- This should disappear when the upgrade starts',
                checked_at: new Date().toISOString(),
                last_error: '',
                update_in_progress: false,
            });
            showToast('Showing fake update available… upgrade starts in 3 s', 'ok', 0);
            await delay(3000);

            // Step 1: trigger the fake upgrade on the backend
            var payload = await fetchJson('/debug/fake-upgrade', { method: 'POST' });
            renderReleaseControl(payload.update_info || {
                local_version: state.release.local_version,
                remote_version: '999.0.0',
                update_available: true,
                changelog: '',
                checked_at: '',
                last_error: '',
                update_in_progress: true,
            });
            // renderReleaseControl hides changelog when update_in_progress,
            // but we want it visible until "Install complete" (step 6).
            if (changelogRow) changelogRow.hidden = false;
            showToast(payload.message || 'Simulated upgrade started…', 'ok', 0);

            // Step 2: poll for progress updates until done (no restart expected)
            for (var attempt = 0; attempt < 30; attempt++) {
                await delay(1000);
                try {
                    var cfg = await fetchJson('/config');
                    var info = cfg.update_info || {};
                    renderMeta(cfg);
                    renderReleaseControl(info);
                    // renderReleaseControl hides changelog when in_progress;
                    // override: keep it visible until step 6 ("Install complete")
                    if (info.update_in_progress && info.update_step < 6 && changelogRow) {
                        changelogRow.hidden = false;
                    }
                    if (!info.update_in_progress) {
                        showToast('Fake upgrade finished.', 'ok');
                        return;
                    }
                } catch (e) { /* server may be briefly unreachable */ }
            }
            showToast('Fake upgrade timed out.', 'error');
        } catch (err) {
            showToast(err.message, 'error');
        }
    };

    // ── Upload & Convert ────────────────────────────────────────────
    (function initUpload() {
        var fileInput = document.getElementById('upload-file-input');
        var dirInput = document.getElementById('upload-dir-input');
        var fileBtn = document.getElementById('upload-file-btn');
        var dirBtn = document.getElementById('upload-dir-btn');
        var submitBtn = document.getElementById('upload-submit-btn');
        var fileList = document.getElementById('upload-file-list');
        var patternRow = document.getElementById('upload-pattern-row');
        var patternInput = document.getElementById('upload-filter-pattern');
        var statusEl = document.getElementById('upload-status');

        if (!fileInput || !dirInput || !submitBtn) return;

        var pendingFiles = [];
        var isDirectory = false;

        function formatSize(bytes) {
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
            return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
        }

        function globToRegex(pattern) {
            if (!pattern) return null;
            var re = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&')
                .replace(/\*/g, '.*')
                .replace(/\?/g, '.');
            return new RegExp('^' + re + '$', 'i');
        }

        function renderFileList() {
            fileList.innerHTML = '';
            fileList.hidden = pendingFiles.length === 0;
            pendingFiles.forEach(function (f, idx) {
                var item = document.createElement('div');
                item.className = 'upload-file-item';
                item.id = 'upload-item-' + idx;
                item.innerHTML = '<span class="name" title="' + f.name + '">' + f.name + '</span>'
                    + '<span class="size">' + formatSize(f.size) + '</span>'
                    + '<div class="upload-progress-bar"><div class="fill" style="width:0%"></div></div>'
                    + '<span class="status"></span>';
                fileList.appendChild(item);
            });
            submitBtn.disabled = pendingFiles.length === 0;
        }

        function filterByPattern(files) {
            var pattern = patternInput ? patternInput.value.trim() : '';
            if (!pattern) return files;
            var re = globToRegex(pattern);
            if (!re) return files;
            return files.filter(function (f) { return re.test(f.name); });
        }

        fileBtn.addEventListener('click', function () { fileInput.click(); });
        dirBtn.addEventListener('click', function () { dirInput.click(); });

        fileInput.addEventListener('change', function () {
            isDirectory = false;
            if (patternRow) patternRow.hidden = true;
            pendingFiles = Array.from(fileInput.files || []);
            renderFileList();
        });

        dirInput.addEventListener('change', function () {
            isDirectory = true;
            if (patternRow) patternRow.hidden = false;
            var all = Array.from(dirInput.files || []);
            pendingFiles = filterByPattern(all);
            renderFileList();
        });

        if (patternInput) {
            patternInput.addEventListener('input', function () {
                if (!isDirectory) return;
                var all = Array.from(dirInput.files || []);
                pendingFiles = filterByPattern(all);
                renderFileList();
            });
        }

        function uploadFile(file, idx, settings) {
            return new Promise(function (resolve) {
                var formData = new FormData();
                formData.append('file', file);
                Object.keys(settings).forEach(function (k) { formData.append(k, settings[k]); });

                var xhr = new XMLHttpRequest();
                xhr.open('POST', '/upload-and-convert', true);
                if (state.auth && state.auth.token) {
                    xhr.setRequestHeader('Authorization', 'Bearer ' + state.auth.token);
                }

                var progressBar = document.querySelector('#upload-item-' + idx + ' .upload-progress-bar .fill');
                var statusSpan = document.querySelector('#upload-item-' + idx + ' .status');

                xhr.upload.addEventListener('progress', function (e) {
                    if (e.lengthComputable && progressBar) {
                        progressBar.style.width = Math.round((e.loaded / e.total) * 100) + '%';
                    }
                });

                xhr.addEventListener('load', function () {
                    if (xhr.status >= 200 && xhr.status < 300) {
                        if (progressBar) progressBar.style.width = '100%';
                        if (statusSpan) { statusSpan.textContent = '✓'; statusSpan.className = 'status ok'; }
                        try { resolve({ ok: true, data: JSON.parse(xhr.responseText) }); }
                        catch (_) { resolve({ ok: true, data: {} }); }
                    } else {
                        if (statusSpan) { statusSpan.className = 'status fail'; }
                        try {
                            var err = JSON.parse(xhr.responseText);
                            if (statusSpan) statusSpan.textContent = err.error || 'Error';
                            resolve({ ok: false, error: err.error || 'Upload failed' });
                        } catch (_) {
                            if (statusSpan) statusSpan.textContent = 'Error';
                            resolve({ ok: false, error: 'Upload failed' });
                        }
                    }
                });

                xhr.addEventListener('error', function () {
                    if (statusSpan) { statusSpan.textContent = 'Network error'; statusSpan.className = 'status fail'; }
                    resolve({ ok: false, error: 'Network error' });
                });

                xhr.send(formData);
            });
        }

        submitBtn.addEventListener('click', async function () {
            if (pendingFiles.length === 0) return;
            submitBtn.disabled = true;
            if (statusEl) setStatus(statusEl, i18n.t('upload.uploading') || 'Uploading…');

            var codecEl = document.getElementById('upload-codec');
            var speedEl = document.getElementById('upload-speed');
            var apEl = document.getElementById('upload-audio-passthrough');
            var dsEl = document.getElementById('upload-delete-source');
            var presetSelEl = document.getElementById('upload-preset-select');
            var presetId = presetSelEl ? presetSelEl.value : '';

            var settings = {
                codec: presetId ? '' : (codecEl ? codecEl.value : 'nvenc_h265'),
                encode_speed: presetId ? '' : (speedEl ? speedEl.value : 'normal'),
                audio_passthrough: apEl && apEl.checked ? 'true' : 'false',
                delete_source: dsEl && dsEl.checked ? 'true' : 'false',
            };
            if (presetId) settings.preset_id = presetId;

            var CONCURRENT = 2;
            var queue = pendingFiles.slice();
            var succeeded = 0;
            var failed = 0;
            var idx = 0;

            async function worker() {
                while (queue.length > 0) {
                    var file = queue.shift();
                    var i = idx++;
                    var result = await uploadFile(file, i, settings);
                    if (result.ok) succeeded++; else failed++;
                }
            }

            var workers = [];
            for (var w = 0; w < Math.min(CONCURRENT, queue.length); w++) {
                workers.push(worker());
            }
            await Promise.all(workers);

            var msg = i18n.t('upload.complete', { ok: succeeded, fail: failed })
                || succeeded + ' uploaded, ' + failed + ' failed';
            if (statusEl) setStatus(statusEl, msg, failed > 0 ? 'error' : 'ok');
            submitBtn.disabled = false;
            await refreshJobs();
        });
    })();
}());
