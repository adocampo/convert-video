(function () {
    const state = {
        autoRefresh: true,
        timerId: null,
        theme: 'light',
        allowedRoots: [],
        release: {
            local_version: '',
            remote_version: '',
            update_available: false,
            changelog: '',
            checked_at: '',
            last_error: '',
            update_in_progress: false,
        },
        expandedJobs: {},
        activeQueueJobId: '',
        queueJobIds: [],
        lastJobs: [],
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
    };

    const themeStorageKey = 'clutch-theme';
    const legacyThemeStorageKey = 'convert-video-theme';

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
    const form = document.getElementById('job-form');
    const inputFileField = document.getElementById('input-file');
    const inputKindField = document.getElementById('input-kind');
    const inputSelectionHint = document.getElementById('input-selection-hint');
    const inputRecursiveField = document.getElementById('input-recursive');
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

    function padNumber(value) {
        return String(value).padStart(2, '0');
    }

    function buildSubmittedDisplay(date) {
        return [
            date.getFullYear(),
            padNumber(date.getMonth() + 1),
            padNumber(date.getDate()),
        ].join('-') + ' ' + [
            padNumber(date.getHours()),
            padNumber(date.getMinutes()),
        ].join(':');
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
        if (gen.length) lines.push(`<div class="media-row"><span class="media-label">General</span> ${escapeHtml(gen.join(' · '))}</div>`);
        // Video tracks
        if (media.video && media.video.length) {
            media.video.forEach(function (v) {
                var parts = [];
                if (v.codec) parts.push(v.codec);
                if (v.resolution) parts.push(v.resolution);
                if (v.fps) parts.push(v.fps + ' fps');
                if (v.bitrate) parts.push(v.bitrate);
                if (v.bit_depth) parts.push(v.bit_depth + '-bit');
                lines.push(`<div class="media-row"><span class="media-label">Video</span> ${escapeHtml(parts.join(' · '))}</div>`);
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
                lines.push(`<div class="media-row"><span class="media-label">Audio</span> ${escapeHtml(parts.join(' · '))}</div>`);
            });
        }
        // Subtitle tracks
        if (media.subtitles && media.subtitles.length) {
            media.subtitles.forEach(function (s) {
                var parts = [];
                if (s.codec) parts.push(s.codec);
                if (s.lang) parts.push(s.lang);
                if (s.title) parts.push(s.title);
                if (s.forced) parts.push('forced');
                lines.push(`<div class="media-row"><span class="media-label">Subtitle</span> ${escapeHtml(parts.join(' · '))}</div>`);
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
            var current = selectEl.value;
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
                    selectEl.dispatchEvent(new Event('change', { bubbles: true }));
                    optionsPanel.hidden = true;
                    wrapper.classList.remove('open');
                    syncTrigger();
                });
                optionsPanel.appendChild(btn);
            });
        }

        function syncTrigger() {
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

    function showConfirm(options) {
        return new Promise(function (resolve) {
            confirmTitle.textContent = options.title || 'Confirm';
            confirmMessage.textContent = options.message || 'Are you sure?';
            confirmOkButton.textContent = options.ok || 'Ok';
            confirmModal.hidden = false;

            function cleanup() {
                confirmModal.hidden = true;
                confirmOkButton.removeEventListener('click', onOk);
                confirmCancelButton.removeEventListener('click', onCancel);
                backdrop.removeEventListener('click', onCancel);
            }

            var backdrop = confirmModal.querySelector('.confirm-backdrop');

            function onOk() { cleanup(); resolve(true); }
            function onCancel() { cleanup(); resolve(false); }

            confirmOkButton.addEventListener('click', onOk);
            confirmCancelButton.addEventListener('click', onCancel);
            backdrop.addEventListener('click', onCancel);
        });
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
        if (systemThemeQuery && systemThemeQuery.matches) {
            return 'dark';
        }
        return 'light';
    }

    function getAutoRefreshTitle() {
        if (state.autoRefresh) {
            return 'Automatic queue refresh is on. The dashboard reloads the queue every 2 seconds. Click to pause it.';
        }
        return 'Automatic queue refresh is off. Click to resume queue refresh every 2 seconds.';
    }

    function updateAutoRefreshButton() {
        if (!toggleAutoRefreshButton) {
            return;
        }
        toggleAutoRefreshButton.textContent = `Auto refresh: ${state.autoRefresh ? 'on' : 'off'}`;
        toggleAutoRefreshButton.setAttribute('title', getAutoRefreshTitle());
        toggleAutoRefreshButton.setAttribute('aria-label', getAutoRefreshTitle());
    }

    function delay(ms) {
        return new Promise(function (resolve) {
            window.setTimeout(resolve, ms);
        });
    }

    function formatIsoTimestamp(value) {
        if (!value) {
            return '';
        }

        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) {
            return String(value);
        }
        return buildSubmittedDisplay(parsed);
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
            return 'Installing the latest clutch release and restarting the service.';
        }

        if (updateInfo.update_available) {
            const heading = `New version available: ${updateInfo.local_version} -> ${updateInfo.remote_version}`;
            const changelog = markdownToPlainText(updateInfo.changelog);
            return changelog ? `${heading}\n\n${changelog}` : heading;
        }

        const checkedAt = formatIsoTimestamp(updateInfo.checked_at);
        return checkedAt
            ? `Check whether new versions are available. Last checked: ${checkedAt}.`
            : 'Check whether new versions are available.';
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
        };

        state.release = nextInfo;

        // Version display
        if (aboutVersion) {
            aboutVersion.textContent = nextInfo.local_version ? 'v' + nextInfo.local_version : '\u2014';
        }

        // Update button
        if (releaseButton && releaseLabel) {
            let label = 'Check for updates';
            if (nextInfo.update_in_progress) {
                label = 'Updating\u2026';
            } else if (nextInfo.update_available && nextInfo.remote_version) {
                label = 'Update to v' + nextInfo.remote_version;
            }

            releaseLabel.textContent = label;
            releaseButton.disabled = nextInfo.update_in_progress;
            releaseButton.dataset.busy = nextInfo.update_in_progress ? 'true' : 'false';
            releaseButton.classList.toggle('has-badge', nextInfo.update_available);
        }

        // Changelog text
        if (changelogRow && changelogText) {
            var cl = changelogToHtml(nextInfo.changelog);
            if (cl && nextInfo.update_available) {
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
                renderReleaseControl(payload.update_info || {});

                const updateInfo = payload.update_info || {};
                if (!updateInfo.update_in_progress && (!targetVersion || updateInfo.local_version === targetVersion)) {
                    showToast(`Service restarted on clutch ${updateInfo.local_version || targetVersion}.`, 'ok');
                    await refreshJobs();
                    return;
                }
            } catch (error) {
                lastError = error.message;
            }
        }

        showToast(
            lastError || 'The service is restarting. Reload the page in a few seconds if it does not reconnect automatically.',
            'error', 0
        );
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

        const response = await fetch(requestPath, requestOptions);
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
        inputRecursiveField.disabled = nextKind !== 'directory';
        inputFileField.setAttribute(
            'title',
            path
                ? `Selected source ${nextKind === 'directory' ? 'folder' : 'file'}: ${path}`
                : 'Source file or folder to convert. Use the chooser buttons to browse the source.'
        );
        if (nextKind !== 'directory') {
            inputRecursiveField.checked = false;
        }

        if (!path) {
            inputSelectionHint.textContent = 'Choose a single file or a folder on the source.';
            return;
        }

        if (nextKind === 'directory') {
            inputSelectionHint.textContent = 'Selected source folder. Enable the recursive option to include subdirectories.';
            return;
        }

        inputSelectionHint.textContent = 'Selected source file. Only this item will be queued.';
    }

    function clearInputSelection() {
        setInputSelection('', 'file');
    }

    function setWatcherDirectory(path) {
        watcherDirectoryField.value = path || '';
        watcherDirectoryField.setAttribute(
            'title',
            path
                ? `Selected source watch directory: ${path}`
                : 'Source directory to monitor for new files.'
        );
    }

    function setWatcherOutputDir(path) {
        watcherOutputDirField.value = path || '';
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
        watcherForm.elements.audio_passthrough.checked = false;
        watcherForm.elements.force.checked = false;
        syncAllCustomSelects();
        watcherButton.textContent = 'Add watcher';
        cancelEditWatcherButton.hidden = true;
        // Re-enable Edit/Remove buttons
        Array.prototype.forEach.call(
            watchersContainer.querySelectorAll('[data-edit-watcher], [data-remove-watcher]'),
            function (btn) { btn.disabled = false; }
        );
    }

    function syncAllowedRootsField() {
        settingsForm.elements.allowed_roots.value = state.allowedRoots.join('\n');
    }

    function renderAllowedRoots() {
        syncAllowedRootsField();

        if (!state.allowedRoots.length) {
            allowedRootsList.innerHTML = '<div class="empty">No allowed source roots configured. Add one to restrict what the service can access.</div>';
            return;
        }

        allowedRootsList.innerHTML = state.allowedRoots.map(function (root, index) {
            return `
                <div class="list-item">
                    <div class="job-name">Allowed source root ${index + 1}</div>
                    <div class="path-code" title="${escapeHtml(root)}">${escapeHtml(root)}</div>
                    <div class="actions">
                        <button class="ghost" type="button" data-remove-allowed-root="${index}" title="Remove this allowed source root from the service settings.">Remove</button>
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
                    setStatus(settingsStatus, 'Allowed source root removed. Save settings to apply.', 'ok');
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
            setStatus(settingsStatus, 'Allowed source root already present.', 'ok');
            return;
        }
        state.allowedRoots = state.allowedRoots.concat([normalized]);
        renderAllowedRoots();
        setStatus(settingsStatus, 'Allowed source root added. Save settings to apply.', 'ok');
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

    /* ── Sidebar Navigation ── */

    var validPages = ['activity', 'jobs', 'watchers', 'schedule', 'system'];

    function navigateTo(page) {
        if (validPages.indexOf(page) === -1) page = 'activity';
        validPages.forEach(function (p) {
            var section = document.getElementById('page-' + p);
            if (section) section.hidden = (p !== page);
        });
        var links = sidebar.querySelectorAll('.sidebar-link');
        links.forEach(function (link) {
            link.classList.toggle('active', link.dataset.page === page);
        });
        if (page === 'schedule' && priceProvider.value) {
            loadPriceChart();
        }
        if (page === 'watchers' || page === 'system') {
            initCustomSelects();
            syncAllCustomSelects();
        }
        if (page === 'system') {
            startSysmonPolling();
        } else {
            stopSysmonPolling();
        }
        closeSidebar();
    }

    function getPageFromHash() {
        var hash = window.location.hash.replace('#', '');
        return validPages.indexOf(hash) !== -1 ? hash : 'activity';
    }

    function closeSidebar() {
        sidebar.classList.remove('open');
        sidebarOverlay.hidden = true;
    }

    /* ── Schedule UI ── */

    var DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    var DAY_VALUES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

    function makeDefaultRule() {
        return { days: ['mon', 'tue', 'wed', 'thu', 'fri'], start: '00:00', end: '07:00', action: 'allow' };
    }

    function renderScheduleRules() {
        var rules = state.scheduleRules;
        if (!rules.length) {
            scheduleRulesList.innerHTML = '<div class="empty">No rules defined. Add a rule below.</div>';
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
                + '<label><span>From</span><input type="time" value="' + escapeHtml(rule.start || '00:00') + '" data-rule="' + index + '" data-field="start"></label>'
                + '<label><span>To</span><input type="time" value="' + escapeHtml(rule.end || '07:00') + '" data-rule="' + index + '" data-field="end"></label>'
                + '<label><span>Action</span><select data-rule="' + index + '" data-field="action">'
                + '<option value="allow"' + (rule.action === 'allow' ? ' selected' : '') + '>Allow</option>'
                + '<option value="block"' + (rule.action === 'block' ? ' selected' : '') + '>Block</option>'
                + '</select></label>'
                + '<button class="ghost" type="button" data-remove-rule="' + index + '" title="Remove this rule.">&times;</button>'
                + '</div></div>';
        }).join('');

        Array.prototype.forEach.call(
            scheduleRulesList.querySelectorAll('[data-remove-rule]'),
            function (btn) {
                btn.addEventListener('click', function () {
                    var idx = Number(btn.dataset.removeRule);
                    state.scheduleRules.splice(idx, 1);
                    renderScheduleRules();
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
                + label + ':00 — ' + pKwh.toFixed(5) + ' EUR/kWh">'
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
            cheapestRange = ' · Cheapest ' + cheapestCount + 'h: ' + ranges.join(', ');
        }

        var isRee = priceProvider.value === 'ree_pvpc';
        var priceLabel = isRee ? 'PVPC' : 'spot';
        var summary = 'Today\'s ' + priceLabel + ' prices — ' + prices.length + 'h loaded';
        if (currentPrice != null) {
            summary += ' · Now: ' + (currentPrice / 1000).toFixed(5) + ' EUR/kWh';
        }
        if (sorted.length) summary += ' · Min: ' + (sorted[0].price / 1000).toFixed(5) + ' · Max: ' + (sorted[sorted.length - 1].price / 1000).toFixed(5);
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
        var label = allowed ? 'Conversions allowed' : 'Conversions blocked';
        if (status.reason) label += ' — ' + status.reason;
        if (status.current_price != null) {
            label += ' (current: ' + (Number(status.current_price) / 1000).toFixed(5) + ' EUR/kWh)';
        }
        scheduleStatusBar.textContent = label;
    }

    function populateBiddingZones(zones) {
        if (!zones || !zones.length) return;
        state.biddingZones = zones;
        var current = priceBiddingZone.value;
        var options = '<option value="">Select zone</option>';
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
        setStatus(scheduleStatusEl, 'Saving schedule...');

        try {
            await fetchJson('/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ schedule_config: collectScheduleConfig() }),
            });
            setStatus(scheduleStatusEl, 'Schedule saved.', 'ok');
            await Promise.all([refreshSummary(), refreshJobs()]);
        } catch (error) {
            setStatus(scheduleStatusEl, error.message, 'error');
        } finally {
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
            setFormStatus('Source file selected.', 'ok');
        } else if (state.browser.target === 'input_directory') {
            setInputSelection(path, 'directory');
            setFormStatus('Source folder selected.', 'ok');
        } else if (state.browser.target === 'allowed_root') {
            addAllowedRoot(path);
        } else if (state.browser.target === 'watcher_directory') {
            setWatcherDirectory(path);
            setStatus(watcherStatus, 'Source watch directory selected.', 'ok');
        } else if (state.browser.target === 'watcher_output_directory') {
            setWatcherOutputDir(path);
            setStatus(watcherStatus, 'Watcher output directory selected.', 'ok');
        } else if (state.browser.target === 'output_directory') {
            outputDirField.value = path;
            setFormStatus('Destination folder selected.', 'ok');
        } else if (state.browser.target === 'default_output_directory') {
            defaultOutputDirField.value = path;
            setStatus(settingsStatus, 'Default destination folder selected.', 'ok');
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
            browserList.innerHTML = '<tr><td colspan="2" class="empty">No items in this directory.</td></tr>';
            return;
        }

        if (!entries.length) {
            state.browser.activeEntryIndex = -1;
            browserList.innerHTML = '<tr><td colspan="2" class="empty">No entries match the current filter.</td></tr>';
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
        browserUpButton.disabled = !payload.parent;
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
            sidebarVersion.textContent = 'v' + state.release.local_version;
        }
    }

    function applySummaryToForms(summary) {
        const defaults = summary.default_job_settings || {};
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
        watcherForm.elements.delete_source.checked = Boolean(defaults.delete_source);

        populateBiddingZones(summary.bidding_zones || []);
        applyScheduleToForm(summary.schedule_config, summary.schedule_status);
        syncAllCustomSelects();
    }

    function renderWatchers(watchers) {
        if (!watchers.length) {
            watchersContainer.innerHTML = '<div class="empty">No watchers configured.</div>';
            return;
        }

        var rows = watchers.map(function (watcher) {
            var overrides = [];
            if (watcher.output_dir) overrides.push('output: ' + escapeHtml(watcher.output_dir));
            if (watcher.codec) overrides.push('codec: ' + escapeHtml(watcher.codec));
            if (watcher.encode_speed) overrides.push('speed: ' + escapeHtml(watcher.encode_speed));
            if (watcher.audio_passthrough === true) overrides.push('audio passthrough');
            if (watcher.force === true) overrides.push('force');
            var overridesCell = overrides.length
                ? `<span class="watcher-overrides">${overrides.join(' | ')}</span>`
                : '<span class="watcher-details">—</span>';
            var isEditing = Boolean(state.editingWatcherId);
            var disabledAttr = isEditing ? ' disabled' : '';
            return `<tr>
                        <td><span class="watcher-dir" title="${escapeHtml(watcher.directory)}">${escapeHtml(watcher.directory)}</span></td>
                        <td class="watcher-details">recursive: ${escapeHtml(String(watcher.recursive))} | poll: ${escapeHtml(String(watcher.poll_interval))}s | settle: ${escapeHtml(String(watcher.settle_time))}s | delete src: ${escapeHtml(String(Boolean(watcher.delete_source)))}</td>
                        <td>${overridesCell}</td>
                        <td class="watcher-actions">
                            <button class="inline-button-warn" type="button" data-edit-watcher="${watcher.id}" title="Edit this watcher's settings."${disabledAttr}>Edit</button>
                            <button class="inline-button" type="button" data-remove-watcher="${watcher.id}" title="Stop monitoring this source directory."${disabledAttr}>Remove</button>
                        </td>
                    </tr>`;
        }).join('');

        watchersContainer.innerHTML =
            '<div class="watcher-section-header">Current watched directories</div>' +
            '<table class="watcher-table"><thead><tr><th>Directory</th><th>Settings</th><th>Overrides</th><th></th></tr></thead><tbody>' +
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
                    watcherForm.elements.audio_passthrough.checked = Boolean(watcher.audio_passthrough);
                    watcherForm.elements.force.checked = Boolean(watcher.force);
                    syncAllCustomSelects();
                    watcherButton.textContent = 'Update watcher';
                    cancelEditWatcherButton.hidden = false;
                    watcherForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    watcherForm.classList.remove('highlight-pulse');
                    void watcherForm.offsetWidth;
                    watcherForm.classList.add('highlight-pulse');
                    watcherForm.addEventListener('animationend', function () {
                        watcherForm.classList.remove('highlight-pulse');
                    }, { once: true });
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
                        title: 'Remove watcher',
                        message: 'Stop monitoring "' + dirName + '"? This will permanently remove this watcher configuration.',
                        ok: 'Remove',
                    });
                    if (!confirmed) return;
                    button.disabled = true;
                    try {
                        await fetchJson(`/watchers/${button.dataset.removeWatcher}`, { method: 'DELETE' });
                        setStatus(watcherStatus, 'Watcher removed.', 'ok');
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
                va = (a.codec || '') + '/' + (a.encode_speed || '');
                vb = (b.codec || '') + '/' + (b.encode_speed || '');
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
        return job.status === 'running' || job.status === 'paused' || job.status === 'queued' || job.status === 'cancelling';
    }

    function pruneExpandedJobs(jobs) {
        const nextExpanded = {};

        jobs.forEach(function (job) {
            if (Object.prototype.hasOwnProperty.call(state.expandedJobs, job.id)) {
                nextExpanded[job.id] = state.expandedJobs[job.id];
            }
        });

        state.expandedJobs = nextExpanded;
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
        updateToggleExpandButton();
    }

    function updateJobsCount(filtered, total) {
        if (!total) {
            jobsCount.textContent = '';
        } else if (filtered === total) {
            jobsCount.textContent = `${total} jobs`;
        } else {
            jobsCount.textContent = `${filtered} / ${total} jobs`;
        }
    }

    function updateToggleExpandButton() {
        var details = jobsContainer.querySelectorAll('.jt-detail-row');
        var anyOpen = false;
        Array.prototype.forEach.call(details, function (row) {
            if (!row.classList.contains('jt-detail-hidden')) anyOpen = true;
        });
        toggleExpandJobsButton.textContent = anyOpen ? 'Collapse all' : 'Expand all';
    }

    function buildSortIndicator(col) {
        if (state.jobSortColumn !== col) return '';
        return state.jobSortAsc ? ' ▲' : ' ▼';
    }

    function renderJobs(jobs) {
        state.lastJobs = jobs.slice();
        var filtered = filterJobs(jobs);
        updateJobsCount(filtered.length, jobs.length);
        if (!filtered.length) {
            state.expandedJobs = {};
            state.activeQueueJobId = '';
            state.queueJobIds = [];
            jobsContainer.innerHTML = jobs.length
                ? '<div class="empty">No jobs match the current filter.</div>'
                : '<div class="empty">No jobs yet.</div>';
            updateToggleExpandButton();
            return;
        }

        pruneExpandedJobs(filtered);

        const sortedJobs = sortJobs(filtered);
        ensureActiveQueueJob(sortedJobs);

        var headerCols = [
            { key: 'name', label: 'Name' },
            { key: 'status', label: 'Status' },
            { key: 'progress', label: 'Progress' },
            { key: 'codec', label: 'Codec' },
            { key: 'size', label: 'Size' },
            { key: 'eta', label: 'ETA' },
            { key: 'submitted', label: 'Submitted' },
        ];

        var thead = '<thead><tr>' + headerCols.map(function (c) {
            var cls = state.jobSortColumn === c.key ? ' class="jt-sorted"' : '';
            return '<th' + cls + ' data-sort-col="' + c.key + '">' + c.label + buildSortIndicator(c.key) + '</th>';
        }).join('') + '<th></th></tr></thead>';

        var rows = sortedJobs.map(function (job) {
            const rawProgress = Number(job.progress_percent == null ? 0 : job.progress_percent);
            const progress = Number.isFinite(rawProgress) ? Math.max(0, Math.min(rawProgress, 100)) : 0;
            const etaLabel = extractEtaLabel(job.message);
            let progressLabel = 'Done';

            if (job.status === 'queued') progressLabel = 'Waiting';
            else if (job.status === 'running') progressLabel = etaLabel ? progress.toFixed(1) + '% \u2013 ETA ' + etaLabel : progress.toFixed(1) + '%';
            else if (job.status === 'paused') progressLabel = progress.toFixed(1) + '% \u2013 Paused';
            else if (job.status === 'cancelling') progressLabel = 'Cancelling\u2026';
            else if (job.status === 'failed') progressLabel = 'Failed';
            else if (job.status === 'cancelled') progressLabel = 'Cancelled';
            else if (job.status === 'skipped') progressLabel = 'Skipped';
            else if (progress > 0) progressLabel = progress.toFixed(1) + '%';

            const submitted = job.submitted_display || job.submitted_at || '';
            const isOpen = shouldShowJobOpen(job);
            const isActive = job.id === state.activeQueueJobId;
            const activeClass = isActive ? ' jt-row-active' : '';

            // Action buttons
            const pauseButton = job.status === 'running'
                ? '<button class="inline-button-warn" type="button" data-pause-id="' + job.id + '" title="Pause">Pause</button>'
                : job.status === 'paused'
                    ? '<button class="inline-button-warn" type="button" data-resume-id="' + job.id + '" title="Resume">Resume</button>'
                    : '';
            const cancelButton = (job.status === 'queued' || job.status === 'running' || job.status === 'paused')
                ? '<button class="inline-button" type="button" data-cancel-id="' + job.id + '" title="Cancel">Cancel</button>'
                : '';
            const moveNextButton = job.status === 'queued'
                ? '<button class="inline-button-warn" type="button" data-move-next-id="' + job.id + '" title="Convert next">Next</button>'
                : '';
            const retryButton = (job.status === 'failed' || job.status === 'cancelled')
                ? '<button class="inline-button-warn" type="button" data-retry-id="' + job.id + '" title="Retry">Retry</button>'
                : '';
            const clearButton = (job.status !== 'running' && job.status !== 'paused' && job.status !== 'cancelling')
                ? '<button class="inline-button" type="button" data-clear-id="' + job.id + '" title="Remove from queue">Clear</button>'
                : '';

            var actionBtns = [moveNextButton, pauseButton, cancelButton, retryButton, clearButton].filter(Boolean).join(' ');

            var mainRow = '<tr class="jt-row' + activeClass + '" data-job-id="' + job.id + '">'
                + '<td class="jt-name" title="' + escapeHtml(basename(job.input_file)) + '">' + escapeHtml(basename(job.input_file)) + '</td>'
                + '<td><span class="badge badge-sm ' + escapeHtml(job.status) + '">' + escapeHtml(job.status) + '</span></td>'
                + '<td class="jt-progress"><div class="progress-track"><div class="progress-fill progress-fill-' + escapeHtml(job.status) + '" style="width:' + progress.toFixed(1) + '%"></div></div><span class="jt-progress-label">' + escapeHtml(progressLabel) + '</span></td>'
                + '<td class="jt-codec">' + escapeHtml(job.codec || '') + ' / ' + escapeHtml(job.encode_speed || '') + '</td>'
                + '<td class="jt-size">' + escapeHtml(formatBytes(job.input_size_bytes)) + '</td>'
                + '<td class="jt-eta">' + escapeHtml(etaLabel || '\u2014') + '</td>'
                + '<td class="jt-submitted">' + escapeHtml(submitted) + '</td>'
                + '<td class="jt-actions">' + actionBtns + '</td>'
                + '</tr>';

            // Detail row — two-column layout: source (left) / output (right)
            var elapsed = formatElapsed(job.started_at, job.finished_at);

            var srcCol = '<div class="jt-detail-col">'
                + '<div class="jt-detail-col-title">Source</div>'
                + '<div class="job-detail"><div class="job-detail-label">Size</div><div class="job-detail-value">' + escapeHtml(formatBytes(job.input_size_bytes)) + '</div></div>'
                + '<div class="job-detail"><div class="job-detail-label">Path</div><div class="job-detail-value job-detail-code">' + escapeHtml(job.input_file) + '</div></div>'
                + renderMediaSection('Media', job.input_media)
                + '</div>';

            var outCol = '<div class="jt-detail-col">'
                + '<div class="jt-detail-col-title">Output</div>'
                + '<div class="job-detail"><div class="job-detail-label">Size</div><div class="job-detail-value">' + escapeHtml(formatBytes(job.output_size_bytes)) + '</div></div>'
                + (job.output_file ? '<div class="job-detail"><div class="job-detail-label">Path</div><div class="job-detail-value job-detail-code">' + escapeHtml(job.output_file) + '</div></div>' : '')
                + renderMediaSection('Media', job.output_media)
                + '</div>';

            var footerDetails = '<div class="jt-detail-footer">'
                + '<div class="job-detail"><div class="job-detail-label">Profile</div><div class="job-detail-value">' + escapeHtml(job.codec) + ' / ' + escapeHtml(job.encode_speed) + '</div></div>'
                + '<div class="job-detail"><div class="job-detail-label">Submitted</div><div class="job-detail-value">' + escapeHtml(submitted) + '</div></div>'
                + '<div class="job-detail"><div class="job-detail-label">Compression</div><div class="job-detail-value">' + escapeHtml(formatCompression(job.compression_percent)) + '</div></div>'
                + (elapsed ? '<div class="job-detail"><div class="job-detail-label">Duration</div><div class="job-detail-value">' + escapeHtml(elapsed) + '</div></div>' : '')
                + '<div class="job-detail jt-detail-message"><div class="job-detail-label">Message</div><div class="job-detail-value job-detail-code">' + escapeHtml(job.message || 'No extra message.') + '</div></div>'
                + '</div>';

            var detailRow = '<tr class="jt-detail-row' + (isOpen ? '' : ' jt-detail-hidden') + '" data-detail-for="' + job.id + '">'
                + '<td colspan="8"><div class="jt-detail-inner">'
                + '<div class="jt-detail-columns">' + srcCol + outCol + '</div>'
                + footerDetails
                + '</div></td></tr>';

            return mainRow + detailRow;
        }).join('');

        jobsContainer.innerHTML = '<table class="jobs-table"><colgroup>'
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

        // Row click to toggle detail
        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('.jt-row'),
            function (row) {
                row.style.cursor = 'pointer';
                row.addEventListener('click', function (event) {
                    if (event.target && event.target.closest('button')) return;
                    var jobId = row.dataset.jobId;
                    state.activeQueueJobId = jobId;
                    var detailRow = jobsContainer.querySelector('[data-detail-for="' + jobId + '"]');
                    if (detailRow) {
                        var isOpen = !detailRow.classList.contains('jt-detail-hidden');
                        detailRow.classList.toggle('jt-detail-hidden', isOpen);
                        state.expandedJobs[jobId] = !isOpen;
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
                    button.textContent = 'Pausing...';
                    try {
                        const response = await fetchJson(`/jobs/${button.dataset.pauseId}/pause`, { method: 'POST' });
                        setFormStatus(response.message || 'Conversion paused.', 'ok');
                        await refreshJobs();
                    } catch (error) {
                        setFormStatus(error.message, 'error');
                        button.disabled = false;
                        button.textContent = 'Pause';
                    }
                });
            }
        );

        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('[data-resume-id]'),
            function (button) {
                button.addEventListener('click', async function () {
                    button.disabled = true;
                    button.textContent = 'Resuming...';
                    try {
                        const response = await fetchJson(`/jobs/${button.dataset.resumeId}/resume`, { method: 'POST' });
                        setFormStatus(response.message || 'Conversion resumed.', 'ok');
                        await refreshJobs();
                    } catch (error) {
                        setFormStatus(error.message, 'error');
                        button.disabled = false;
                        button.textContent = 'Resume';
                    }
                });
            }
        );

        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('[data-cancel-id]'),
            function (button) {
                button.addEventListener('click', async function () {
                    button.disabled = true;
                    button.textContent = 'Cancelling...';
                    try {
                        const response = await fetchJson(`/jobs/${button.dataset.cancelId}`, { method: 'DELETE' });
                        setFormStatus(response.message || 'Cancellation requested.', 'ok');
                        await refreshJobs();
                    } catch (error) {
                        setFormStatus(error.message, 'error');
                        button.disabled = false;
                        button.textContent = 'Cancel';
                    }
                });
            }
        );

        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('[data-clear-id]'),
            function (button) {
                button.addEventListener('click', async function () {
                    var confirmed = await showConfirm({ title: 'Remove job', message: 'Remove this job from the queue list?', ok: 'Remove' });
                    if (!confirmed) return;
                    button.disabled = true;
                    try {
                        await fetchJson(`/jobs/${button.dataset.clearId}?purge=1`, { method: 'DELETE' });
                        setFormStatus('Job removed from the queue.', 'ok');
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
                    button.textContent = 'Retrying...';
                    try {
                        const response = await fetchJson(`/jobs/${button.dataset.retryId}/retry`, { method: 'POST' });
                        setFormStatus(response.message || 'Job queued for retry.', 'ok');
                        await refreshJobs();
                    } catch (error) {
                        setFormStatus(error.message, 'error');
                        button.disabled = false;
                        button.textContent = 'Retry';
                    }
                });
            }
        );

        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('[data-move-next-id]'),
            function (button) {
                button.addEventListener('click', async function () {
                    button.disabled = true;
                    button.textContent = 'Moving...';
                    try {
                        await fetchJson(`/jobs/${button.dataset.moveNextId}/move-next`, { method: 'POST' });
                        setFormStatus('Job promoted to convert next.', 'ok');
                        await refreshJobs();
                    } catch (error) {
                        setFormStatus(error.message, 'error');
                        button.disabled = false;
                        button.textContent = 'Convert next';
                    }
                });
            }
        );

        updateActiveQueueSelection();
        updateToggleExpandButton();
        updateActivityBadge(sortedJobs);
    }

    function updateActivityBadge(jobs) {
        var active = jobs.filter(function (j) { return j.status === 'running' || j.status === 'paused'; }).length;
        if (navActivityBadge) {
            navActivityBadge.hidden = !active;
            navActivityBadge.textContent = String(active);
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
            var cpuHtml = '<div class="sysmon-section"><div class="sysmon-section-title">CPU</div>';
            if (data.cpu_count) cpuHtml += '<div class="sysmon-kv"><span class="sysmon-kv-label">Cores</span><span>' + data.cpu_count + '</span></div>';
            if (data.load) cpuHtml += '<div class="sysmon-kv"><span class="sysmon-kv-label">Load average</span><span>' + data.load.join(' / ') + '</span></div>';
            if (data.cpu_temp != null) cpuHtml += '<div class="sysmon-kv"><span class="sysmon-kv-label">Temperature</span><span>' + data.cpu_temp + ' °C</span></div>';
            cpuHtml += '</div>';
            sections.push(cpuHtml);
        }

        // Memory
        if (data.memory) {
            sections.push('<div class="sysmon-section"><div class="sysmon-section-title">Memory</div>'
                + pctBar(data.memory.used, data.memory.total, 'RAM')
                + '</div>');
        }

        // GPUs
        if (data.gpus && data.gpus.length) {
            var gpuHtml = '<div class="sysmon-section"><div class="sysmon-section-title">GPU</div>';
            data.gpus.forEach(function (gpu) {
                gpuHtml += '<div class="sysmon-gpu">';
                gpuHtml += '<div class="sysmon-kv"><span class="sysmon-kv-label">' + escapeHtml(gpu.name) + '</span></div>';
                if (gpu.mem_total_mib != null && gpu.mem_used_mib != null) {
                    gpuHtml += pctBar(gpu.mem_used_mib * 1048576, gpu.mem_total_mib * 1048576, 'VRAM');
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
            var diskHtml = '<div class="sysmon-section"><div class="sysmon-section-title">Disks</div>';
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
        setFormStatus('Queueing job...');

        const formData = new FormData(form);
        const payload = {
            input_file: formData.get('input_file'),
            input_kind: formData.get('input_kind') || 'file',
            recursive: formData.get('recursive') === 'on',
            output_dir: formData.get('output_dir'),
            codec: formData.get('codec'),
            encode_speed: formData.get('encode_speed'),
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
            setFormStatus(response.message || `Queued job ${response.id}`, 'ok');
            await refreshJobs();
        } catch (error) {
            setFormStatus(error.message, 'error');
        } finally {
            submitButton.disabled = false;
        }
    });

    settingsForm.addEventListener('submit', async function (event) {
        event.preventDefault();
        settingsButton.disabled = true;
        setStatus(settingsStatus, 'Saving settings...');
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
            },
        };

        try {
            await fetchJson('/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            setStatus(settingsStatus, 'Settings saved.', 'ok');
            await refreshSummary();
        } catch (error) {
            setStatus(settingsStatus, error.message, 'error');
        } finally {
            settingsButton.disabled = false;
        }
    });

    watcherForm.addEventListener('submit', async function (event) {
        event.preventDefault();
        watcherButton.disabled = true;
        var isEditing = state.editingWatcherId !== null;
        setStatus(watcherStatus, isEditing ? 'Updating watcher...' : 'Adding watcher...');

        const formData = new FormData(watcherForm);
        const codecVal = formData.get('codec') || '';
        const speedVal = formData.get('encode_speed') || '';
        const payload = {
            directory: formData.get('directory'),
            recursive: formData.get('recursive') === 'on',
            poll_interval: Number(formData.get('poll_interval') || 5),
            settle_time: Number(formData.get('settle_time') || 30),
            delete_source: formData.get('delete_source') === 'on',
            output_dir: (formData.get('output_dir') || '').trim(),
            codec: codecVal,
            encode_speed: speedVal,
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
                setStatus(watcherStatus, 'Watcher updated.', 'ok');
            } else {
                await fetchJson('/watchers', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                setStatus(watcherStatus, 'Watcher added.', 'ok');
            }
            resetWatcherForm();
            await refreshSummary();
        } catch (error) {
            setStatus(watcherStatus, error.message, 'error');
        } finally {
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
        updateToggleExpandButton();
    });

    browseInputFileButton.addEventListener('click', function () {
        openPathBrowser({
            target: 'input_file',
            selection: 'file',
            scope: 'allowed',
            path: inputFileField.value || '',
            eyebrow: '',
            title: 'Select source file',
        });
    });

    browseInputDirectoryButton.addEventListener('click', function () {
        openPathBrowser({
            target: 'input_directory',
            selection: 'directory',
            scope: 'allowed',
            path: inputKindField.value === 'directory' ? inputFileField.value || '' : '',
            eyebrow: '',
            title: 'Choose source folder',
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
            title: 'Add allowed root directory',
        });
    });

    browseWatcherDirectoryButton.addEventListener('click', function () {
        openPathBrowser({
            target: 'watcher_directory',
            selection: 'directory',
            scope: 'allowed',
            path: watcherDirectoryField.value || '',
            eyebrow: '',
            title: 'Choose watcher source directory',
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
            title: 'Select watcher output directory',
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
            title: 'Select destination folder',
        });
    });

    clearOutputDirButton.addEventListener('click', function () {
        outputDirField.value = '';
    });

    browseDefaultOutputDirButton.addEventListener('click', function () {
        openPathBrowser({
            target: 'default_output_directory',
            selection: 'directory',
            scope: 'all',
            path: defaultOutputDirField.value || '',
            eyebrow: '',
            title: 'Select default destination folder',
        });
    });

    clearDefaultOutputDirButton.addEventListener('click', function () {
        defaultOutputDirField.value = '';
    });

    browserUpButton.addEventListener('click', function () {
        if (state.browser.parent) {
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

    document.addEventListener('keydown', function (event) {
        if (!browserModal.hidden || event.altKey || event.ctrlKey || event.metaKey) {
            return;
        }

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
            moveQueueSelection(-1);
            return;
        }

        if (event.key !== 'Enter') {
            return;
        }

        if (!state.queueJobIds.length) {
            return;
        }

        event.preventDefault();
        toggleActiveQueueJob();
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
                    setFormStatus(`Removed ${deletedCount} ${label} job${deletedCount === 1 ? '' : 's'}.`, 'ok');
                    await refreshJobs();
                } catch (error) {
                    setFormStatus(error.message, 'error');
                }
            });
        }
    );

    themeSelect.addEventListener('change', function () {
        applyTheme(themeSelect.value);
        persistTheme(themeSelect.value);
    });

    releaseButton.addEventListener('click', async function () {
        if (state.release.update_in_progress) {
            return;
        }

        if (state.release.update_available) {
            const targetVersion = state.release.remote_version || 'latest';
            const confirmed = window.confirm(
                `Install clutch ${targetVersion} and restart the service now?\n\nAny active conversions will be stopped and returned to the queue from the beginning.`
            );
            if (!confirmed) {
                return;
            }

            releaseButton.disabled = true;
            releaseButton.dataset.busy = 'true';
            showToast(`Installing clutch ${targetVersion} and restarting the service...`);

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
                showToast(payload.message || `Installing clutch ${targetVersion} and restarting the service...`, 'ok', 0);
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
                showToast(`New version available: ${payload.local_version} \u2192 ${payload.remote_version}`, 'ok');
            } else {
                showToast(`clutch ${payload.local_version} is already up to date.`, 'ok');
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
        systemThemeQuery.addEventListener('change', function (event) {
            if (!getStoredTheme()) {
                applyTheme(event.matches ? 'dark' : 'light');
            }
        });
    }

    applyTheme(getPreferredTheme());
    renderReleaseControl(state.release);
    clearInputSelection();
    setWatcherDirectory('');
    updateAutoRefreshButton();

    if (startupParams.get('notice')) {
        setFormStatus(startupParams.get('notice'), 'ok');
        history.replaceState(null, '', window.location.pathname + window.location.hash);
    } else if (startupParams.get('error')) {
        setFormStatus(startupParams.get('error'), 'error');
        history.replaceState(null, '', window.location.pathname + window.location.hash);
    }

    initCustomSelects();

    document.addEventListener('mousedown', function (e) {
        if (!e.target.closest('.custom-select')) {
            closeAllCustomSelects();
        }
    });

    navigateTo(getPageFromHash());
    refreshAll();
    scheduleRefresh();
}());
