(function () {
    const state = {
        autoRefresh: true,
        timerId: null,
        theme: 'light',
        allowedRoots: [],
        expandedJobs: {},
        activeQueueJobId: '',
        queueJobIds: [],
        lastJobs: [],
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
    };

    const themeStorageKey = 'convert-video-theme';

    const statusPriority = {
        running: 0,
        cancelling: 1,
        queued: 2,
        failed: 3,
        cancelled: 4,
        skipped: 5,
        succeeded: 6,
    };

    const meta = document.getElementById('service-meta');
    const jobsContainer = document.getElementById('jobs-container');
    const form = document.getElementById('job-form');
    const inputFileField = document.getElementById('input-file');
    const inputKindField = document.getElementById('input-kind');
    const inputSelectionHint = document.getElementById('input-selection-hint');
    const inputRecursiveField = document.getElementById('input-recursive');
    const browseInputFileButton = document.getElementById('browse-input-file');
    const browseInputDirectoryButton = document.getElementById('browse-input-directory');
    const clearInputFileButton = document.getElementById('clear-input-file');
    const formStatus = document.getElementById('form-status');
    const settingsForm = document.getElementById('settings-form');
    const allowedRootsList = document.getElementById('allowed-roots-list');
    const addAllowedRootButton = document.getElementById('add-allowed-root');
    const settingsStatus = document.getElementById('settings-status');
    const watcherForm = document.getElementById('watcher-form');
    const watcherDirectoryField = document.getElementById('watcher-directory');
    const browseWatcherDirectoryButton = document.getElementById('browse-watcher-directory');
    const clearWatcherDirectoryButton = document.getElementById('clear-watcher-directory');
    const watcherStatus = document.getElementById('watcher-status');
    const watchersContainer = document.getElementById('watchers-container');
    const submitButton = document.getElementById('submit-button');
    const settingsButton = document.getElementById('settings-button');
    const watcherButton = document.getElementById('watcher-button');
    const refreshButton = document.getElementById('refresh-button');
    const clearJobsButton = document.getElementById('clear-jobs');
    const toggleAutoRefreshButton = document.getElementById('toggle-autorefresh');
    const toggleThemeButton = document.getElementById('toggle-theme');
    const themeLabel = document.getElementById('theme-label');
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

    function summarizeMessage(job) {
        if (job.status === 'running') {
            return job.message || 'Conversion in progress.';
        }
        if (job.status === 'queued') {
            return job.message || 'Waiting in queue.';
        }
        return job.message || job.input_file || '';
    }

    function setFormStatus(message, kind) {
        const effectiveKind = kind || '';
        formStatus.textContent = message || '';
        formStatus.className = effectiveKind ? `status-line ${effectiveKind}` : 'status-line';
    }

    function setStatus(target, message, kind) {
        const effectiveKind = kind || '';
        target.textContent = message || '';
        target.className = effectiveKind ? `status-line ${effectiveKind}` : 'status-line';
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
            if (storedTheme === 'light' || storedTheme === 'dark') {
                return storedTheme;
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

    function getThemeLabel(theme) {
        return theme === 'dark' ? 'Dark theme' : 'Light theme';
    }

    function getThemeToggleTitle(theme) {
        if (theme === 'dark') {
            return 'Current theme: dark. Click to switch the dashboard to the light theme.';
        }
        return 'Current theme: light. Click to switch the dashboard to the dark theme.';
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

    function applyTheme(theme) {
        const nextTheme = theme === 'dark' ? 'dark' : 'light';
        const switchLabel = getThemeLabel(nextTheme);
        const switchTitle = getThemeToggleTitle(nextTheme);

        state.theme = nextTheme;
        document.documentElement.setAttribute('data-theme', nextTheme);
        if (themeLabel) {
            themeLabel.textContent = switchLabel;
        }
        if (toggleThemeButton) {
            toggleThemeButton.setAttribute('aria-label', switchTitle);
            toggleThemeButton.setAttribute('title', switchTitle);
        }
    }

    function persistTheme(theme) {
        try {
            window.localStorage.setItem(themeStorageKey, theme);
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
        browserRoots.innerHTML = (roots || []).map(function (root, index) {
            return `<button class="ghost" type="button" data-browser-root="${index}" title="Jump to allowed source root: ${escapeHtml(root)}">${escapeHtml(root)}</button>`;
        }).join('');

        Array.prototype.forEach.call(
            browserRoots.querySelectorAll('[data-browser-root]'),
            function (button) {
                button.addEventListener('click', function () {
                    const index = Number(button.dataset.browserRoot);
                    if (!Number.isFinite(index) || !state.browser.roots[index]) {
                        return;
                    }
                    loadBrowserPath(state.browser.roots[index], { resetFilter: true, focusFilter: true });
                });
            }
        );
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
        browserRoots.innerHTML = '';
        browserList.innerHTML = '';
        browserCurrentPath.value = '';
        browserShowHidden.checked = false;
        browserFilter.value = '';
        state.browser.filterQuery = '';
        state.browser.activeEntryIndex = -1;
        setBrowserStatus('', '');
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
        const activeEntry = browserList.querySelector('.browser-entry-active');
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
            browserList.innerHTML = '<div class="empty">No matching items in this source directory.</div>';
            return;
        }

        if (!entries.length) {
            state.browser.activeEntryIndex = -1;
            browserList.innerHTML = '<div class="empty">No entries match the current filter.</div>';
            return;
        }

        browserList.innerHTML = entries.map(function (item) {
            const entry = item.entry;
            const originalIndex = item.originalIndex;
            const isActive = activeItem && originalIndex === activeItem.originalIndex;
            const activeClass = isActive ? ' browser-entry-active' : '';
            const openableClass = entry.kind === 'directory' ? ' browser-entry-openable' : '';
            const rowTitle = entry.kind === 'directory'
                ? 'Click to open this source folder.'
                : 'Click to select this source file.';
            const openButton = entry.kind === 'directory'
                ? `<button class="ghost" type="button" data-open-entry="${originalIndex}" title="Open this source folder.">Open</button>`
                : '';
            const selectButton = entry.selectable
                ? `<button class="${entry.kind === 'directory' ? 'secondary' : 'primary'}" type="button" data-select-entry="${originalIndex}" title="${entry.kind === 'directory' ? 'Use this source folder as the selected path.' : 'Select this source file.'}">${entry.kind === 'directory' ? 'Use' : 'Select'}</button>`
                : '';

            return `
                <div class="browser-entry${openableClass}${activeClass}" data-entry-index="${originalIndex}" aria-selected="${isActive ? 'true' : 'false'}" title="${rowTitle}">
                    <div class="browser-entry-main">
                        <div class="browser-entry-kind">${escapeHtml(entry.kind)}</div>
                        <div class="browser-entry-name">${escapeHtml(entry.name)}</div>
                        <div class="browser-entry-path">${escapeHtml(entry.path)}</div>
                    </div>
                    <div class="actions">
                        ${openButton}
                        ${selectButton}
                    </div>
                </div>`;
        }).join('');

        Array.prototype.forEach.call(
            browserList.querySelectorAll('[data-open-entry]'),
            function (button) {
                button.addEventListener('click', function () {
                    const index = Number(button.dataset.openEntry);
                    if (!Number.isFinite(index) || !state.browser.entries[index]) {
                        return;
                    }
                    loadBrowserPath(state.browser.entries[index].path, { resetFilter: true, focusFilter: true });
                });
            }
        );

        Array.prototype.forEach.call(
            browserList.querySelectorAll('[data-select-entry]'),
            function (button) {
                button.addEventListener('click', function () {
                    const index = Number(button.dataset.selectEntry);
                    if (!Number.isFinite(index) || !state.browser.entries[index]) {
                        return;
                    }
                    selectBrowserPath(state.browser.entries[index].path);
                });
            }
        );

        Array.prototype.forEach.call(
            browserList.querySelectorAll('[data-entry-index]'),
            function (row) {
                row.addEventListener('click', function (event) {
                    if (event.target && event.target.closest('button')) {
                        return;
                    }
                    const index = Number(row.dataset.entryIndex);
                    if (!Number.isFinite(index) || !state.browser.entries[index]) {
                        return;
                    }
                    state.browser.activeEntryIndex = index;
                    if (state.browser.entries[index].kind === 'directory') {
                        loadBrowserPath(state.browser.entries[index].path, { resetFilter: true, focusFilter: true });
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
        setBrowserStatus(payload.restricted ? 'Browsing within allowed source roots.' : 'Browsing the source filesystem.', '');
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
        const allowedRootsLabel = (summary.allowed_roots || []).join(', ') || 'unrestricted';
        const workerCount = Number(summary.worker_count || 1);
        const configuredGpuDevices = Array.isArray(summary.gpu_devices) ? summary.gpu_devices : [];
        const visibleGpuDevices = Array.isArray(summary.visible_nvidia_gpus) ? summary.visible_nvidia_gpus : [];
        const configuredGpuLabel = configuredGpuDevices.length ? configuredGpuDevices.join(', ') : 'auto';
        const visibleGpuLabel = visibleGpuDevices.length
            ? visibleGpuDevices.map(function (gpu) {
                var label = gpu.name || String(gpu.index);
                if (gpu.memory) label += ' (' + gpu.memory + ')';
                return label;
            }).join(', ')
            : 'none detected';
        const visibleGpuTitle = visibleGpuDevices.length
            ? visibleGpuDevices.map(function (gpu) {
                return `${gpu.index}: ${gpu.name}`;
            }).join(' | ')
            : 'No NVIDIA GPUs detected by the service process.';
        chips.push(`<span class="chip">Allowed source roots: ${escapeHtml(allowedRootsLabel)}</span>`);
        chips.push(`<span class="chip">Watchers: ${escapeHtml(String((summary.watchers || []).length))}</span>`);
        chips.push(`<span class="chip">Workers: ${escapeHtml(String(workerCount))} on shared queue</span>`);
        chips.push(`<span class="chip" title="Configured NVENC GPU indices for queued jobs.">NVENC GPUs: ${escapeHtml(configuredGpuLabel)}</span>`);
        chips.push(`<span class="chip" title="${escapeHtml(visibleGpuTitle)}">Visible NVIDIA GPUs: ${escapeHtml(visibleGpuLabel)}</span>`);
        meta.innerHTML = chips.join('');
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
    }

    function renderWatchers(watchers) {
        if (!watchers.length) {
            watchersContainer.innerHTML = '<div class="empty">No watchers configured.</div>';
            return;
        }

        watchersContainer.innerHTML = watchers.map(function (watcher) {
            return `
                <div class="list-item">
                    <div class="job-name" title="${escapeHtml(watcher.directory)}">${escapeHtml(watcher.directory)}</div>
                    <div class="small">recursive: ${escapeHtml(String(watcher.recursive))} | poll: ${escapeHtml(String(watcher.poll_interval))}s | settle: ${escapeHtml(String(watcher.settle_time))}s | delete source: ${escapeHtml(String(Boolean(watcher.delete_source)))}</div>
                    <div class="actions">
                        <button class="inline-button" type="button" data-remove-watcher="${watcher.id}" title="Stop monitoring this source directory.">Remove</button>
                    </div>
                </div>`;
        }).join('');

        Array.prototype.forEach.call(
            watchersContainer.querySelectorAll('[data-remove-watcher]'),
            function (button) {
                button.addEventListener('click', async function () {
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

            const leftTime = String(left.started_at || left.submitted_at || '');
            const rightTime = String(right.started_at || right.submitted_at || '');
            return rightTime.localeCompare(leftTime);
        });
    }

    function shouldShowJobOpen(job) {
        if (Object.prototype.hasOwnProperty.call(state.expandedJobs, job.id)) {
            return Boolean(state.expandedJobs[job.id]);
        }
        return job.status === 'running' || job.status === 'queued' || job.status === 'cancelling';
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
            jobsContainer.querySelectorAll('.job-card'),
            function (card) {
                const isActive = card.dataset.jobId === state.activeQueueJobId;
                card.classList.toggle('job-card-active', isActive);
                card.setAttribute('aria-selected', isActive ? 'true' : 'false');
            }
        );
    }

    function scrollActiveQueueJobIntoView() {
        const activeCard = jobsContainer.querySelector('.job-card-active');
        if (!activeCard) {
            return;
        }
        activeCard.scrollIntoView({ block: 'nearest' });
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

        let activeCard = null;
        Array.prototype.some.call(
            jobsContainer.querySelectorAll('.job-card'),
            function (card) {
                if (card.dataset.jobId !== state.activeQueueJobId) {
                    return false;
                }
                activeCard = card;
                return true;
            }
        );

        if (!activeCard) {
            return;
        }

        activeCard.open = !activeCard.open;
        state.expandedJobs[state.activeQueueJobId] = activeCard.open;
    }

    function renderJobs(jobs) {
        state.lastJobs = jobs.slice();
        if (!jobs.length) {
            state.expandedJobs = {};
            state.activeQueueJobId = '';
            state.queueJobIds = [];
            jobsContainer.innerHTML = '<div class="empty">No jobs yet.</div>';
            return;
        }

        pruneExpandedJobs(jobs);

        const sortedJobs = sortJobs(jobs);
        ensureActiveQueueJob(sortedJobs);

        const cards = sortedJobs.map(function (job) {
            const rawProgress = Number(job.progress_percent == null ? 0 : job.progress_percent);
            const progress = Number.isFinite(rawProgress)
                ? Math.max(0, Math.min(rawProgress, 100))
                : 0;
            const etaLabel = extractEtaLabel(job.message);
            let progressLabel = 'Done';

            if (job.status === 'queued') {
                progressLabel = 'Waiting';
            } else if (job.status === 'running') {
                progressLabel = etaLabel
                    ? `${progress.toFixed(1)}% - ETA ${etaLabel}`
                    : `${progress.toFixed(1)}%`;
            } else if (job.status === 'cancelling') {
                progressLabel = 'Cancelling...';
            } else if (job.status === 'failed') {
                progressLabel = 'Failed';
            } else if (job.status === 'cancelled') {
                progressLabel = 'Cancelled';
            } else if (job.status === 'skipped') {
                progressLabel = 'Skipped';
            } else if (progress > 0) {
                progressLabel = `${progress.toFixed(1)}%`;
            }

            const submitted = job.submitted_display || job.submitted_at || '';
            const detailsOpen = shouldShowJobOpen(job) ? ' open' : '';
            const preview = summarizeMessage(job);
            const cancelButton = (job.status === 'queued' || job.status === 'running')
                ? `<button class="inline-button" type="button" data-cancel-id="${job.id}" title="Request cancellation for this job.">Cancel job</button>`
                : '';
            const retryButton = (job.status === 'failed' || job.status === 'cancelled')
                ? `<button class="secondary" type="button" data-retry-id="${job.id}" title="Queue this job again with the same settings.">Retry job</button>`
                : '';
            const clearButton = (job.status !== 'running' && job.status !== 'cancelling')
                ? `<button class="ghost" type="button" data-clear-id="${job.id}" title="Remove this job from the queue list.">Clear</button>`
                : '';

            return `
                <details class="job-card" data-job-id="${job.id}"${detailsOpen}>
                    <summary class="job-summary" title="Open or collapse job details. Use Arrow Up and Arrow Down to move between jobs, and Enter to toggle the active job.">
                        <div class="job-summary-main">
                            <div class="job-summary-meta">
                                <span class="badge ${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
                                <span class="job-id">${escapeHtml(job.id.slice(0, 8))}</span>
                            </div>
                            <div class="job-title">${escapeHtml(basename(job.input_file))}</div>
                            <div class="job-preview">${escapeHtml(preview)}</div>
                        </div>
                        <div class="job-summary-side progress-cell">
                            <div class="job-summary-caption">Progress</div>
                            <div class="progress-track"><div class="progress-fill" style="width: ${progress.toFixed(1)}%"></div></div>
                            <div class="progress-text">${escapeHtml(progressLabel)}</div>
                        </div>
                        <div class="job-summary-expand"><span>Details</span><span class="job-chevron">▾</span></div>
                    </summary>
                    <div class="job-details">
                        <div class="job-detail-grid">
                            <div class="job-detail">
                                <div class="job-detail-label">Profile</div>
                                <div class="job-detail-value">${escapeHtml(job.codec)} / ${escapeHtml(job.encode_speed)}</div>
                            </div>
                            <div class="job-detail">
                                <div class="job-detail-label">Submitted</div>
                                <div class="job-detail-value">${escapeHtml(submitted)}</div>
                            </div>
                            <div class="job-detail job-detail-highlight">
                                <div class="job-detail-label">Original size</div>
                                <div class="job-detail-value">${escapeHtml(formatBytes(job.input_size_bytes))}</div>
                            </div>
                            <div class="job-detail job-detail-highlight">
                                <div class="job-detail-label">Converted size</div>
                                <div class="job-detail-value">${escapeHtml(formatBytes(job.output_size_bytes))}</div>
                            </div>
                            <div class="job-detail">
                                <div class="job-detail-label">Compression</div>
                                <div class="job-detail-value">${escapeHtml(formatCompression(job.compression_percent))}</div>
                            </div>
                            <div class="job-detail job-detail-wide">
                                <div class="job-detail-label">Source path</div>
                                <div class="job-detail-value job-detail-code">${escapeHtml(job.input_file)}</div>
                            </div>
                            ${job.output_file ? `
                            <div class="job-detail job-detail-wide">
                                <div class="job-detail-label">Destination path</div>
                                <div class="job-detail-value job-detail-code">${escapeHtml(job.output_file)}</div>
                            </div>` : ''}
                            <div class="job-detail job-detail-wide">
                                <div class="job-detail-label">Message</div>
                                <div class="job-detail-value job-detail-code">${escapeHtml(job.message || 'No extra message.')}</div>
                            </div>
                        </div>
                        ${(cancelButton || retryButton || clearButton) ? `<div class="actions">${cancelButton}${retryButton}${clearButton}</div>` : ''}
                    </div>
                </details>`;
        }).join('');

        jobsContainer.innerHTML = `
            <div class="jobs-wrap">
                <div class="job-list">${cards}</div>
            </div>`;

        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('.job-card'),
            function (details) {
                details.addEventListener('click', function () {
                    const jobId = details.dataset.jobId;
                    if (!jobId) {
                        return;
                    }
                    state.activeQueueJobId = jobId;
                    updateActiveQueueSelection();
                });
                details.addEventListener('toggle', function () {
                    const jobId = details.dataset.jobId;
                    if (!jobId) {
                        return;
                    }
                    state.expandedJobs[jobId] = details.open;
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
                        button.textContent = 'Cancel job';
                    }
                });
            }
        );

        Array.prototype.forEach.call(
            jobsContainer.querySelectorAll('[data-clear-id]'),
            function (button) {
                button.addEventListener('click', async function () {
                    if (!window.confirm('Remove this job from the queue list?')) {
                        return;
                    }
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
                        button.textContent = 'Retry job';
                    }
                });
            }
        );

        updateActiveQueueSelection();
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
        setStatus(watcherStatus, 'Adding watcher...');

        const formData = new FormData(watcherForm);
        const payload = {
            directory: formData.get('directory'),
            recursive: formData.get('recursive') === 'on',
            poll_interval: Number(formData.get('poll_interval') || 5),
            settle_time: Number(formData.get('settle_time') || 30),
            delete_source: formData.get('delete_source') === 'on',
        };

        try {
            await fetchJson('/watchers', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            watcherForm.reset();
            setWatcherDirectory('');
            watcherForm.elements.poll_interval.value = '5';
            watcherForm.elements.settle_time.value = '30';
            watcherForm.elements.delete_source.checked = settingsForm.elements.default_delete_source.checked;
            setStatus(watcherStatus, 'Watcher added.', 'ok');
            await refreshSummary();
        } catch (error) {
            setStatus(watcherStatus, error.message, 'error');
        } finally {
            watcherButton.disabled = false;
        }
    });

    refreshButton.addEventListener('click', function () {
        refreshAll();
    });

    browseInputFileButton.addEventListener('click', function () {
        openPathBrowser({
            target: 'input_file',
            selection: 'file',
            scope: 'allowed',
            path: inputFileField.value || '',
            eyebrow: 'Source file',
            title: 'Choose a file on the source',
        });
    });

    browseInputDirectoryButton.addEventListener('click', function () {
        openPathBrowser({
            target: 'input_directory',
            selection: 'directory',
            scope: 'allowed',
            path: inputKindField.value === 'directory' ? inputFileField.value || '' : '',
            eyebrow: 'Source folder',
            title: 'Choose a folder on the source',
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
            eyebrow: 'Allowed source root',
            title: 'Choose a directory on the source',
        });
    });

    browseWatcherDirectoryButton.addEventListener('click', function () {
        openPathBrowser({
            target: 'watcher_directory',
            selection: 'directory',
            scope: 'allowed',
            path: watcherDirectoryField.value || '',
            eyebrow: 'Source watch directory',
            title: 'Choose a watch directory on the source',
        });
    });

    clearWatcherDirectoryButton.addEventListener('click', function () {
        setWatcherDirectory('');
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

    clearJobsButton.addEventListener('click', async function () {
        if (!window.confirm('Remove all non-running jobs from the queue list?')) {
            return;
        }

        clearJobsButton.disabled = true;
        try {
            const result = await fetchJson('/jobs', { method: 'DELETE' });
            const deletedCount = Number(result.deleted || 0);
            const runningCount = Number(result.running || 0);
            let message = `Removed ${deletedCount} job${deletedCount === 1 ? '' : 's'} from the queue.`;
            if (runningCount > 0) {
                message += ` ${runningCount} running job${runningCount === 1 ? '' : 's'} kept.`;
            }
            setFormStatus(message, 'ok');
            await refreshJobs();
        } catch (error) {
            setFormStatus(error.message, 'error');
        } finally {
            clearJobsButton.disabled = false;
        }
    });

    toggleThemeButton.addEventListener('click', function () {
        const nextTheme = state.theme === 'dark' ? 'light' : 'dark';
        applyTheme(nextTheme);
        persistTheme(nextTheme);
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
    clearInputSelection();
    setWatcherDirectory('');
    updateAutoRefreshButton();

    if (startupParams.get('notice')) {
        setFormStatus(startupParams.get('notice'), 'ok');
        history.replaceState(null, '', window.location.pathname);
    } else if (startupParams.get('error')) {
        setFormStatus(startupParams.get('error'), 'error');
        history.replaceState(null, '', window.location.pathname);
    }

    refreshAll();
    scheduleRefresh();
}());
