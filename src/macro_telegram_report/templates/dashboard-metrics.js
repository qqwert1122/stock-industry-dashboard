    function metricStatusMarkup(metric) {
      let markup = "";
      if (metric?.daily_status === "new") {
        markup += `<span class="metric-new-badge">${escapeHtml(t("newBadge"))}</span>`;
      } else if (metric?.daily_status === "updated") {
        markup += `<span class="metric-update-dot" aria-label="${escapeHtml(t("updatedBadge"))}" title="${escapeHtml(t("updatedBadge"))}"></span>`;
      }
      if (metric?.is_stale) {
        const staleTitle = `${t("staleBadge")}: ${dateText(metric.observed_label, metric)}`;
        markup += `<span class="metric-stale-badge" title="${escapeHtml(staleTitle)}">${escapeHtml(t("staleBadge"))}</span>`;
      }
      return markup;
    }

    function savedFavoriteMetricIds() {
      try {
        const parsed = JSON.parse(localStorage.getItem(favoriteMetricStorageKey) || "[]");
        if (!Array.isArray(parsed)) return [];
        const validIds = new Set((DASHBOARD_DATA.metrics || []).map((metric) => metric.id));
        return parsed.map(String).filter((id) => validIds.has(id));
      } catch (_error) {
        return [];
      }
    }

    function saveFavoriteMetricIds() {
      localStorage.setItem(favoriteMetricStorageKey, JSON.stringify([...state.favoriteMetricIds]));
    }

    function initFavoriteMetrics() {
      state.favoriteMetricIds = new Set(savedFavoriteMetricIds());
    }

    function isFavoriteMetric(metricId) {
      return state.favoriteMetricIds.has(metricId);
    }

    function favoriteButtonMarkup(metric) {
      const active = isFavoriteMetric(metric.id);
      const label = active ? t("removeFavorite") : t("addFavorite");
      return `<button class="metric-favorite-button${active ? " is-active" : ""}" type="button" data-favorite-toggle="${escapeHtml(metric.id)}" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}" aria-pressed="${active ? "true" : "false"}">
        <i class="fa-${active ? "solid" : "regular"} fa-star" aria-hidden="true"></i>
      </button>`;
    }

    function toggleFavoriteMetric(metricId) {
      if (!metricById(metricId)) return;
      if (state.favoriteMetricIds.has(metricId)) {
        state.favoriteMetricIds.delete(metricId);
      } else {
        state.favoriteMetricIds.add(metricId);
      }
      clampFavoritePage();
      saveFavoriteMetricIds();
      renderDailyUpdates();
      renderIndustries();
      if (state.activeMetricDetailId === metricId) renderMetricDetailDrawer(metricId);
    }

    function initFavoriteButtons(root = document) {
      root.querySelectorAll("[data-favorite-toggle]").forEach((button) => {
        if (button.dataset.favoriteBound === "true") return;
        button.dataset.favoriteBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          toggleFavoriteMetric(button.dataset.favoriteToggle);
        });
      });
    }

    function initFavoritePager(root = document) {
      root.querySelectorAll("[data-favorite-page]").forEach((button) => {
        if (button.dataset.favoritePageBound === "true") return;
        button.dataset.favoritePageBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          if (button.disabled) return;
          state.favoritePage = Number(button.dataset.favoritePage) || 0;
          renderDailyUpdates();
          renderIndustries();
        });
      });
    }

    function noteKeyForMetric(metric) {
      return String(metric?.history_key || metric?.id || metric?.name || "");
    }

    function makeNoteEntryId() {
      return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    }

    function normalizeNoteEntry(entry, index = 0, fallbackMetricName = "") {
      if (!entry || typeof entry !== "object") return null;
      const text = String(entry.text || "").trim();
      if (!text) return null;
      const now = new Date().toISOString();
      const updatedAt = String(entry.updated_at || entry.created_at || now);
      return {
        id: String(entry.id || `${updatedAt}-${index}`),
        text: text.slice(0, 2000),
        created_at: String(entry.created_at || updatedAt),
        updated_at: updatedAt,
        metric_name: String(entry.metric_name || fallbackMetricName || "")
      };
    }

    function sortNoteEntries(entries) {
      return [...entries].sort((a, b) => String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || "")));
    }

    function normalizeMetricNoteRecord(note, fallbackMetricName = "") {
      if (!note || typeof note !== "object") return { metric_name: fallbackMetricName, entries: [] };
      const sourceEntries = Array.isArray(note.entries) ? note.entries : [note];
      const entries = sourceEntries
        .map((entry, index) => normalizeNoteEntry(entry, index, note.metric_name || fallbackMetricName))
        .filter(Boolean);
      return {
        metric_name: String(note.metric_name || fallbackMetricName || entries[0]?.metric_name || ""),
        entries: sortNoteEntries(entries)
      };
    }

    function normalizeNotesDocument(source) {
      const rawNotes = source && typeof source === "object" && source.notes && typeof source.notes === "object"
        ? source.notes
        : {};
      const notes = {};
      Object.entries(rawNotes).forEach(([key, note]) => {
        const record = normalizeMetricNoteRecord(note);
        if (record.entries.length) notes[key] = record;
      });
      return { version: 2, notes };
    }

    function loadMetricNotes() {
      try {
        const parsed = JSON.parse(localStorage.getItem(metricNotesStorageKey) || "{}");
        state.metricNotes = normalizeNotesDocument(parsed);
      } catch (_error) {
        state.metricNotes = { version: 1, notes: {} };
      }
    }

    function saveMetricNotesDocument(document = state.metricNotes) {
      state.metricNotes = normalizeNotesDocument(document);
      localStorage.setItem(metricNotesStorageKey, JSON.stringify(state.metricNotes));
    }

    function metricNote(metric) {
      const key = noteKeyForMetric(metric);
      return key ? state.metricNotes.notes[key] || null : null;
    }

    function metricNoteEntries(metric) {
      return sortNoteEntries(normalizeMetricNoteRecord(metricNote(metric), metric?.name || "").entries);
    }

    function metricLatestNote(metric) {
      return metricNoteEntries(metric)[0] || null;
    }

    function metricNoteText(metric) {
      return String(metricLatestNote(metric)?.text || "");
    }

    function metricHasNote(metric) {
      return metricNoteEntries(metric).length > 0;
    }

    function metricNotePreview(metric) {
      const firstLine = metricNoteText(metric).split(/\r?\n/).map((line) => line.trim()).find(Boolean);
      return firstLine || "";
    }

    function noteButtonMarkup(metric, className = "metric-note-button") {
      const active = metricHasNote(metric);
      const label = active ? t("myNote") : t("editNote");
      return `<button class="${className}${active ? " is-active" : ""}" type="button" data-note-open="${escapeHtml(metric.id)}" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}">
        <i class="fa-${active ? "solid" : "regular"} fa-note-sticky" aria-hidden="true"></i>
      </button>`;
    }

    function noteBlockMarkup(metric) {
      const entries = metricNoteEntries(metric);
      const text = String(entries[0]?.text || "").trim();
      if (!text) return "";
      return `<button class="metric-note-block" type="button" data-note-open="${escapeHtml(metric.id)}">
        <span class="metric-note-label">${escapeHtml(t("noteTitle"))}</span>
        <span class="metric-note-count" aria-label="${escapeHtml(`${entries.length}`)}">${escapeHtml(entries.length)}</span>
        <span class="metric-note-divider" aria-hidden="true">|</span>
        <span class="metric-note-preview">${escapeHtml(text)}</span>
      </button>`;
    }

    function noteUpdatedLabel(note) {
      const updated = note?.updated_at;
      if (!updated) return t("noteNeverSaved");
      return `${t("noteUpdatedAt")}: ${fetchedAtText(updated) || updated}`;
    }

    function setNoteModalOpen(open) {
      const modal = document.getElementById("noteModal");
      const backdrop = document.getElementById("noteModalBackdrop");
      if (!modal || !backdrop) return;
      modal.hidden = !open;
      backdrop.hidden = !open;
      document.body.classList.toggle("note-modal-open", Boolean(open));
      if (open) {
        updateNoteViewportOffset();
        window.setTimeout(() => document.getElementById("noteModalText")?.focus({ preventScroll: true }), 30);
      }
    }

    function updateNoteViewportOffset() {
      if (!window.visualViewport) return;
      const offset = Math.max(0, window.innerHeight - window.visualViewport.height - window.visualViewport.offsetTop);
      document.documentElement.style.setProperty("--note-bottom-offset", `${Math.round(offset)}px`);
    }

    function updateNoteSaveButtonState() {
      const textarea = document.getElementById("noteModalText");
      const saveButton = document.getElementById("noteSaveButton");
      if (saveButton && textarea) saveButton.disabled = !String(textarea.value || "").trim();
      updateNoteCharCount();
    }

    function updateNoteCharCount() {
      const textarea = document.getElementById("noteModalText");
      const counter = document.getElementById("noteCharCount");
      if (!textarea || !counter) return;
      counter.textContent = `${String(textarea.value || "").length} / ${noteMaxLength}`;
    }

    function setNoteEditorValue(text = "", entryId = "") {
      const textarea = document.getElementById("noteModalText");
      state.activeNoteEntryId = entryId;
      state.noteInitialText = String(text || "").slice(0, noteMaxLength);
      if (textarea) {
        textarea.value = state.noteInitialText;
        textarea.placeholder = t("notePlaceholder");
        textarea.maxLength = noteMaxLength;
      }
      updateNoteSaveButtonState();
    }

    function noteHistoryItemMarkup(entry) {
      const timestamp = fetchedAtText(entry.updated_at || entry.created_at) || entry.updated_at || entry.created_at || "";
      return `<article class="note-history-item">
        <p class="note-history-text">${escapeHtml(entry.text)}</p>
        <div class="note-history-item-footer">
          <time class="note-history-time">${escapeHtml(timestamp)}</time>
          <span class="note-history-actions">
            <button class="note-history-action" type="button" data-note-edit="${escapeHtml(entry.id)}">${escapeHtml(t("edit"))}</button>
            <span aria-hidden="true">·</span>
            <button class="note-history-action" type="button" data-note-delete="${escapeHtml(entry.id)}">${escapeHtml(t("delete"))}</button>
          </span>
        </div>
      </article>`;
    }

    function renderNoteHistory(metric) {
      const list = document.getElementById("noteHistoryList");
      const count = document.getElementById("noteHistoryCount");
      const title = document.getElementById("noteHistoryTitle");
      if (!list) return;
      const entries = metricNoteEntries(metric);
      if (title) title.textContent = t("noteHistory");
      if (count) count.textContent = entries.length ? `${entries.length}${state.language === "ko" ? "개" : ` ${t("favoriteCount")}`}` : "";
      list.innerHTML = entries.length
        ? entries.map(noteHistoryItemMarkup).join("")
        : `<p class="note-history-empty">${escapeHtml(t("noteHistoryEmpty"))}</p>`;
      list.querySelectorAll("[data-note-edit]").forEach((button) => {
        button.addEventListener("click", () => editNoteEntry(button.dataset.noteEdit));
      });
      list.querySelectorAll("[data-note-delete]").forEach((button) => {
        button.addEventListener("click", () => deleteNoteEntry(button.dataset.noteDelete));
      });
    }

    function openNoteEditor(metricId) {
      const metric = metricById(metricId);
      if (!metric) return;
      if (!document.getElementById("noteModal")?.hidden && state.activeNoteMetricId !== metric.id && noteModalDirty()) {
        if (!window.confirm(t("noteDiscardConfirm"))) return;
      }
      state.activeNoteMetricId = metric.id;
      const title = document.getElementById("noteModalTitle");
      const meta = document.getElementById("noteModalMeta");
      if (title) title.textContent = t("noteTitle");
      if (meta) meta.textContent = `${localizedField(metric, "name")} · ${localizedIndustry(metric.industry)} · ${localizedGroup(metric.group, [metric])}`;
      setNoteEditorValue("", "");
      renderNoteHistory(metric);
      setNoteModalOpen(true);
    }

    function noteModalDirty() {
      const textarea = document.getElementById("noteModalText");
      return Boolean(textarea && textarea.value !== state.noteInitialText);
    }

    function closeNoteEditor(force = false) {
      if (!force && noteModalDirty() && !window.confirm(t("noteDiscardConfirm"))) return;
      setNoteModalOpen(false);
      state.activeNoteMetricId = "";
      state.activeNoteEntryId = "";
      state.noteInitialText = "";
    }

    function refreshNotesViews() {
      buildSearchIndex();
      renderDailyUpdates();
      renderIndustries();
      renderMetricSearchHost();
      if (state.activeMetricDetailId) renderMetricDetailDrawer(state.activeMetricDetailId);
    }

    function saveActiveNote() {
      const metric = metricById(state.activeNoteMetricId);
      const textarea = document.getElementById("noteModalText");
      if (!metric || !textarea) return;
      const key = noteKeyForMetric(metric);
      if (!key) return;
      const text = textarea.value.trim();
      const next = normalizeNotesDocument(state.metricNotes);
      if (text) {
        const now = new Date().toISOString();
        const record = normalizeMetricNoteRecord(next.notes[key], metric.name || "");
        const entries = [...record.entries];
        const index = state.activeNoteEntryId ? entries.findIndex((entry) => entry.id === state.activeNoteEntryId) : -1;
        if (index >= 0) {
          entries[index] = {
            ...entries[index],
            text: text.slice(0, noteMaxLength),
            updated_at: now,
            metric_name: metric.name || entries[index].metric_name || ""
          };
        } else {
          entries.unshift({
            id: makeNoteEntryId(),
            text: text.slice(0, noteMaxLength),
            created_at: now,
            updated_at: now,
            metric_name: metric.name || ""
          });
        }
        next.notes[key] = normalizeMetricNoteRecord({ metric_name: metric.name || "", entries }, metric.name || "");
      } else if (state.activeNoteEntryId) {
        deleteNoteEntry(state.activeNoteEntryId);
        return;
      } else {
        textarea.focus();
        return;
      }
      try {
        saveMetricNotesDocument(next);
      } catch (_error) {
        window.alert(t("noteSaveFailed"));
        return;
      }
      setNoteEditorValue("", "");
      renderNoteHistory(metric);
      refreshNotesViews();
    }

    function editNoteEntry(entryId) {
      const metric = metricById(state.activeNoteMetricId);
      if (!metric) return;
      const entry = metricNoteEntries(metric).find((item) => item.id === entryId);
      if (!entry) return;
      setNoteEditorValue(entry.text, entry.id);
      document.getElementById("noteModalText")?.focus({ preventScroll: true });
    }

    function deleteNoteEntry(entryId) {
      const metric = metricById(state.activeNoteMetricId);
      if (!metric || !entryId) return;
      const key = noteKeyForMetric(metric);
      const next = normalizeNotesDocument(state.metricNotes);
      const record = normalizeMetricNoteRecord(next.notes[key], metric.name || "");
      const entries = record.entries.filter((entry) => entry.id !== entryId);
      if (entries.length) {
        next.notes[key] = normalizeMetricNoteRecord({ metric_name: metric.name || "", entries }, metric.name || "");
      } else {
        delete next.notes[key];
      }
      try {
        saveMetricNotesDocument(next);
      } catch (_error) {
        window.alert(t("noteSaveFailed"));
        return;
      }
      if (state.activeNoteEntryId === entryId) setNoteEditorValue("", "");
      renderNoteHistory(metric);
      refreshNotesViews();
    }

    function initNoteButtons(root = document) {
      root.querySelectorAll("[data-note-open]").forEach((button) => {
        if (button.dataset.noteBound === "true") return;
        button.dataset.noteBound = "true";
        button.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          openNoteEditor(button.dataset.noteOpen);
        });
      });
    }

    function exportMetricNotes() {
      const blob = new Blob([JSON.stringify(state.metricNotes, null, 2)], { type: "application/json" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `dashboard-metric-notes-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(link.href);
    }

    function mergeMetricNotes(imported) {
      const current = normalizeNotesDocument(state.metricNotes);
      const incoming = normalizeNotesDocument(imported);
      Object.entries(incoming.notes).forEach(([key, note]) => {
        const existing = normalizeMetricNoteRecord(current.notes[key]);
        const merged = new Map(existing.entries.map((entry) => [entry.id, entry]));
        normalizeMetricNoteRecord(note).entries.forEach((entry) => {
          const previous = merged.get(entry.id);
          if (!previous || String(entry.updated_at || "") >= String(previous.updated_at || "")) {
            merged.set(entry.id, entry);
          }
        });
        const record = normalizeMetricNoteRecord({ entries: [...merged.values()] });
        if (record.entries.length) current.notes[key] = record;
      });
      saveMetricNotesDocument(current);
      refreshNotesViews();
    }

    function importMetricNotesFile(file) {
      if (!file) return;
      const reader = new FileReader();
      reader.addEventListener("load", () => {
        try {
          mergeMetricNotes(JSON.parse(String(reader.result || "{}")));
        } catch (_error) {
          window.alert(t("notesImportFailed"));
        }
      });
      reader.addEventListener("error", () => window.alert(t("notesImportFailed")));
      reader.readAsText(file);
    }

    function initMetricNotes() {
      loadMetricNotes();
      document.getElementById("noteSaveButton")?.addEventListener("click", saveActiveNote);
      document.getElementById("noteCancelButton")?.addEventListener("click", () => closeNoteEditor());
      document.getElementById("noteModalClose")?.addEventListener("click", () => closeNoteEditor());
      document.getElementById("noteModalBackdrop")?.addEventListener("click", () => closeNoteEditor());
      document.getElementById("noteModalText")?.addEventListener("input", (event) => {
        const value = event.target.value || "";
        if (value.length > noteMaxLength) event.target.value = value.slice(0, noteMaxLength);
        updateNoteSaveButtonState();
      });
      document.getElementById("notesImportInput")?.addEventListener("change", (event) => {
        importMetricNotesFile(event.target.files?.[0]);
        event.target.value = "";
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !document.getElementById("noteModal")?.hidden) {
          closeNoteEditor();
        }
      });
      if (window.visualViewport) {
        window.visualViewport.addEventListener("resize", updateNoteViewportOffset);
        window.visualViewport.addEventListener("scroll", updateNoteViewportOffset);
      }
    }

    function normalizedInterpretationText(value) {
      return String(value || "")
        .replace(/[\s,.;:·\-–—()\[\]{}]+/g, "")
        .trim();
    }

    function uniqueInterpretationParts(metric, rawParts) {
      const meaningNorm = normalizedInterpretationText(metricDescriptionText(metric));
      const parts = [];
      const seen = [];
      rawParts.forEach((raw) => {
        const text = localizedText(raw || "").trim();
        const norm = normalizedInterpretationText(text);
        if (!text || !norm) return;
        if (meaningNorm && (norm === meaningNorm || meaningNorm.includes(norm) || norm.includes(meaningNorm))) return;
        if (seen.some((existing) => norm === existing || norm.includes(existing) || existing.includes(norm))) return;
        parts.push(text);
        seen.push(norm);
      });
      return parts;
    }

    function interpretationDisplayText(metric) {
      const item = metric?.interpretation;
      const headline = item?.headline || item?.meaning_text || "";
      const detail = item?.detail_text || item?.trend_label || "";
      const context = metricInterpretationContext(metric);
      const parts = uniqueInterpretationParts(metric, [headline, detail, context]);
      if (!parts.length && item?.text) {
        return uniqueInterpretationParts(metric, [item.text]).join(" ");
      }
      return parts.join(" ");
    }

    function interpretationPreviewText(text, limit = 120) {
      if (text.length <= limit) return text;
      const slice = text.slice(0, limit);
      const sentenceEnd = Math.max(slice.lastIndexOf(". "), slice.lastIndexOf(".\""));
      const wordEnd = slice.lastIndexOf(" ");
      const end = sentenceEnd >= limit * 0.55 ? sentenceEnd + 1 : wordEnd >= limit * 0.55 ? wordEnd : limit;
      return slice.slice(0, end).trim();
    }

    function interpretationMarkup(metric) {
      const text = interpretationDisplayText(metric);
      if (!text) return "";
      const canExpand = text.length > 120;
      const expanded = Boolean(state.interpretationExpanded[metric.id]);
      const collapsed = canExpand && !expanded;
      const visibleText = collapsed ? interpretationPreviewText(text) : text;
      return `<div class="detail-interpretation-row">
        <span class="detail-interpretation-label">${escapeHtml(t("interpretationColumnSignal"))}</span>
        <div class="detail-interpretation-content">
          <span class="detail-interpretation-text">${escapeHtml(visibleText)}${collapsed ? "..." : ""}</span>
          ${canExpand ? `<button class="detail-interpretation-more" type="button" data-interpretation-toggle="${escapeHtml(metric.id)}" aria-expanded="${expanded}">${escapeHtml(t(expanded ? "interpretationLess" : "interpretationMore"))}</button>` : ""}
        </div>
      </div>`;
    }

    function detailMeasurementsMarkup(metric) {
      return `<div class="detail-measurements">
        <div class="detail-value-card">
          <span class="detail-field-label">${escapeHtml(t("currentValue"))}</span>
          <div class="detail-current-value">${detailCurrentValueMarkup(metric)}</div>
        </div>
        ${detailDelta(t("previousChange"), displayMetricChange(metric), metric.change_abs)}
        ${detailDelta(t("previousChangePct"), metric.change_pct_label, metric.change_pct)}
        ${detailDelta(t("yoy"), metric.yoy_pct_label, metric.yoy_pct)}
      </div>`;
    }

    function detailTitleColumnMarkup(metric, headingTag = "h3") {
      return `<div class="detail-title-column">
        <div class="detail-title-line"><${headingTag} class="detail-title">${escapeHtml(localizedField(metric, "name"))}</${headingTag}>${countryBadgeMarkup(metricCountryCode(metric))}</div>
        <span class="detail-updated-at ${metricUpdatedAtAgeClass(metric)}">${escapeHtml(metricUpdatedAtText(metric))}</span>
      </div>`;
    }

    function metricDetail(metric, options = {}) {
      const titleColumn = options.includeTitle === false ? "" : `${detailTitleColumnMarkup(metric)}
            <div class="detail-sizedbox" aria-hidden="true"></div>`;
      const titleBlock = `<div class="detail-title-block">
            ${titleColumn}
            <p class="detail-description">${escapeHtml(metricDescriptionText(metric))}</p>
            ${interpretationMarkup(metric)}
          </div>`;
      return `<div class="metric-detail-panel">
        <div class="metric-detail-inner">
          ${titleBlock}
          ${detailMeasurementsMarkup(metric)}
          ${detailMetaStrip(metric, { collapsible: Boolean(options.collapsibleMeta) })}
          <div class="detail-toolbar detail-actions-row">
            ${favoriteButtonMarkup(metric)}
            <button class="detail-icon-button${metricHasNote(metric) ? " note-active" : ""}" type="button" data-note-open="${escapeHtml(metric.id)}">
              <i class="fa-${metricHasNote(metric) ? "solid" : "regular"} fa-note-sticky" aria-hidden="true"></i>
              <span>${escapeHtml(t("myNote"))}</span>
            </button>
            <button class="detail-icon-button" type="button" data-csv-download="${escapeHtml(metric.id)}">
              <i class="fa-solid fa-download" aria-hidden="true"></i>
              <span>${escapeHtml(t("downloadCsv"))}</span>
            </button>
            <button class="detail-icon-button" type="button" data-compare-toggle="${escapeHtml(metric.id)}">
              <i class="fa-solid fa-plus" aria-hidden="true"></i>
              <span>${escapeHtml(t("compareAdd"))}</span>
            </button>
          </div>
          ${comparePanelMarkup(metric)}
          <div class="detail-chart-section">
            <div class="detail-chart-host" data-chart-host="${escapeHtml(metric.id)}">${detailChartForMetric(metric)}</div>
            <div class="detail-period-row">
              ${detailReferenceLegend(metric)}
              <div class="detail-range-toggle" data-range-toggle="${escapeHtml(metric.id)}" hidden>
                <button type="button" class="is-active" data-range="recent">${escapeHtml(t("rangeRecent"))}</button>
                <button type="button" data-range="full">${escapeHtml(t("rangeFull"))}</button>
              </div>
            </div>
          </div>
        </div>
      </div>`;
    }

    function metricRows(metric) {
      const detailId = `metric-detail-${metric.id}`;
      const selected = state.searchSelectedIndex >= 0 && state.searchResults[state.searchSelectedIndex]?.id === metric.id;
      return `<tr class="metric-row${selected ? " is-search-selected" : ""}" data-metric-row data-metric-id="${escapeHtml(metric.id)}" data-detail-id="${detailId}">
        <td class="metric-name-cell" data-label="${escapeHtml(t("metric"))}">
          <button class="metric-toggle" type="button" data-metric-toggle aria-expanded="false" aria-controls="${detailId}">
            <span class="metric-name-wrap">
              <span class="metric-name">${highlightSearchText(localizedField(metric, "name"))}</span>
              ${countryBadgeMarkup(metricCountryCode(metric))}
              ${metricStatusMarkup(metric)}
            </span>
          </button>
        </td>
        <td class="metric-description-cell" data-label="${escapeHtml(t("description"))}">
          <p class="metric-description">${highlightSearchText(metricDescriptionText(metric))}</p>
        </td>
        <td class="metric-date-cell" data-label="${escapeHtml(t("lastUpdated"))}">
          <span class="metric-date">${escapeHtml(dateText(metric.observed_label, metric))}</span>
        </td>
        <td class="metric-value-cell" data-label="${escapeHtml(t("currentValue"))}">
          <span class="metric-value-wrap">
            <span class="metric-current-value">${escapeHtml(displayMetricValue(metric))}</span>
            ${metricChangeBadge(metric)}
          </span>
        </td>
        <td class="metric-chart-cell" data-label="${escapeHtml(t("chart"))}">
          ${chart(metric.history, "chart-mini", metric)}
        </td>
        <td class="metric-favorite-cell" data-label="${escapeHtml(t("favoriteMetrics"))}">
          ${favoriteButtonMarkup(metric)}
          ${noteButtonMarkup(metric)}
        </td>
      </tr>
      <tr class="metric-detail-row" id="${detailId}" aria-hidden="true">
        <td colspan="6">${metricDetail(metric)}</td>
      </tr>`;
    }

    function changedMetrics() {
      return countryFilteredMetrics().filter((metric) =>
        metric.daily_status === "updated" || metric.daily_status === "new"
      );
    }

    function ensureMetricRow(metricId) {
      let row = document.querySelector(`[data-metric-id="${metricId}"]`);
      if (row) return row;
      const metric = metricById(metricId);
      if (!metric) return null;
      selectNavForMetric(metric);
      saveNavState();
      renderFilters();
      renderDailyUpdates();
      renderIndustries();
      return document.querySelector(`[data-metric-id="${metricId}"]`);
    }

    function jumpToMetric(metricId, options = {}) {
      const row = ensureMetricRow(metricId);
      if (!row) return;
      if (options.open !== false && !row.classList.contains("is-expanded")) {
        toggleMetricRow(row, { updateHash: false });
      }
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      row.classList.add("is-highlighted");
      window.setTimeout(() => row.classList.remove("is-highlighted"), 1400);
      const metric = metricById(metricId);
      if (metric && options.updateHash !== false) {
        writeDashboardHash(`#d/${hashSegment(metricHashKey(metric))}`, "replace");
      }
      rememberMetricVisit(metricId);
    }

    function initMetricDetailContent(root, metricId) {
      if (!root || !metricId) return;
      initDetailRange(metricId, root);
      initInterpretationToggles(root);
      initDetailMetaToggles(root);
      initFavoriteButtons(root);
      initCompareControls(root);
      initNoteButtons(root);
      initCsvButtons(root);
      initDetailChartTooltips(root);
      const scroller = root.querySelector(".detail-chart-scroll");
      if (scroller) {
        requestAnimationFrame(() => {
          scroller.scrollLeft = Math.max(0, scroller.scrollWidth - scroller.clientWidth);
          scheduleDynamicDetailAxis(scroller.closest(".detail-chart"));
          updateMetricDetailHeight(root.closest(".metric-detail-row"));
        });
      }
    }

    function initInterpretationToggles(root = document) {
      root.querySelectorAll("[data-interpretation-toggle]").forEach((button) => {
        if (button.dataset.interpretationBound === "true") return;
        button.dataset.interpretationBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          const metricId = button.dataset.interpretationToggle || "";
          if (!metricId) return;
          state.interpretationExpanded[metricId] = !state.interpretationExpanded[metricId];
          refreshMetricDetail(metricId);
        });
      });
    }

    function initDetailMetaToggles(root = document) {
      root.querySelectorAll("[data-detail-meta-toggle]").forEach((button) => {
        if (button.dataset.detailMetaBound === "true") return;
        button.dataset.detailMetaBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          const metricId = button.dataset.detailMetaToggle || "";
          if (!metricId) return;
          state.detailMetadataExpanded[metricId] = !state.detailMetadataExpanded[metricId];
          refreshMetricDetail(metricId);
        });
      });
    }

    function renderMetricDetailDrawer(metricId = state.activeMetricDetailId) {
      const metric = metricById(metricId);
      const body = document.getElementById("metricDetailDrawerBody");
      const title = document.getElementById("metricDetailDrawerTitle");
      if (!metric || !body || !title) return;
      title.innerHTML = detailTitleColumnMarkup(metric, "h2");
      body.innerHTML = metricDetail(metric, { includeTitle: false, collapsibleMeta: true });
      initMetricDetailContent(body, metric.id);
    }

    function setMetricDetailDrawerOpen(open, metricId = state.activeMetricDetailId, options = {}) {
      const drawer = document.getElementById("metricDetailDrawer");
      const backdrop = document.getElementById("metricDetailDrawerBackdrop");
      if (!drawer || !backdrop) return;
      if (open) {
        const metric = metricById(metricId);
        if (!metric) return;
        if (state.activeMetricDetailId !== metric.id) state.detailMetadataExpanded[metric.id] = false;
        if (state.compareBaseMetricId !== metric.id) resetCompareState(metric.id);
        state.activeMetricDetailId = metric.id;
        setDrawerOpen(false);
        if (!options.preserveSignal) setSignalDrawerOpen(false);
        renderMetricDetailDrawer(metric.id);
      } else {
        state.activeMetricDetailId = "";
        document.querySelectorAll(".detail-chart").forEach((chart) => hideDetailTooltip(chart, true));
      }
      document.body.classList.toggle("metric-detail-from-signal", Boolean(open && options.preserveSignal));
      document.body.classList.toggle("metric-detail-drawer-open", Boolean(open));
      drawer.setAttribute("aria-hidden", String(!open));
      backdrop.hidden = !open;
    }

    function openMetricDetail(metricId, options = {}) {
      const metric = metricById(metricId);
      if (!metric) return;
      setMetricDetailDrawerOpen(true, metric.id, options);
      rememberMetricVisit(metric.id);
      if (options.updateHash === true) {
        writeDashboardHash(`#d/${hashSegment(metricHashKey(metric))}`, "replace");
      }
    }

    function openSignalAlertSheet(event) {
      const drawer = document.getElementById("metricDetailDrawer");
      const backdrop = document.getElementById("metricDetailDrawerBackdrop");
      const title = document.getElementById("metricDetailDrawerTitle");
      const body = document.getElementById("metricDetailDrawerBody");
      if (!drawer || !backdrop || !title || !body || !event) return;
      state.activeMetricDetailId = "";
      setDrawerOpen(false);
      setSignalDrawerOpen(false);
      title.textContent = localizedSignalMetricName(event) || t("recentAlerts");
      body.innerHTML = `<section class="signal-detail-sheet">${signalCardMarkup(event)}</section>`;
      document.body.classList.add("metric-detail-drawer-open");
      drawer.setAttribute("aria-hidden", "false");
      backdrop.hidden = false;
    }

    function openRecentAlert(eventKey) {
      const event = signalEvents().find((item) => signalEventKey(item) === eventKey);
      if (!event) return;
      const eventMetricName = normalizeSearchText(event.metric_name || "");
      const metric = metricById(event.metric_id) || (DASHBOARD_DATA.metrics || []).find((item) =>
        eventMetricName && normalizeSearchText(item.name || "") === eventMetricName
      );
      if (metric) {
        openMetricDetail(metric.id);
        return;
      }
      openSignalAlertSheet(event);
    }

    function updateMetricDetailHeight(detail) {
      const panel = detail?.querySelector(".metric-detail-panel");
      if (!panel) return;
      if (!detail.classList.contains("is-open")) {
        panel.style.removeProperty("--metric-detail-max-height");
        return;
      }
      panel.style.setProperty("--metric-detail-max-height", `${panel.scrollHeight + 24}px`);
    }

    function updateOpenMetricDetailHeights() {
      document.querySelectorAll(".metric-detail-row.is-open").forEach(updateMetricDetailHeight);
    }

    function refreshMetricDetail(metricId) {
      const metric = metricById(metricId);
      const detail = document.getElementById(`metric-detail-${metricId}`);
      if (!metric) return;
      if (detail) {
        const cell = detail.querySelector("td");
        if (cell) {
          cell.innerHTML = metricDetail(metric);
          initMetricDetailContent(detail, metricId);
          updateMetricDetailHeight(detail);
        }
      }
      if (state.activeMetricDetailId === metric.id) {
        renderMetricDetailDrawer(metric.id);
      }
    }

    function resetCompareState(metricId) {
      state.compareBaseMetricId = metricId || "";
      state.compareMetricIds = [];
      state.compareOpen = false;
      state.compareQuery = "";
      state.compareResults = [];
      state.compareMode = "raw";
      state.compareRange = "all";
      state.compareWarning = "";
    }

    function ensureCompareHistory(metricId) {
      return ensureLongHistory().then((data) => {
        state.longHistoryData = data;
        refreshMetricDetail(metricId);
      });
    }

    function toggleComparePanel(metricId) {
      if (state.compareBaseMetricId !== metricId) resetCompareState(metricId);
      state.compareOpen = !state.compareOpen;
      state.compareWarning = "";
      refreshMetricDetail(metricId);
      ensureCompareHistory(metricId);
    }

    function compareVisibleForProposed(baseMetric, ids) {
      const previous = state.compareMetricIds;
      state.compareMetricIds = ids;
      const series = compareSeries(baseMetric);
      const visible = filterCompareSeries(series, compareTimeWindow(series));
      state.compareMetricIds = previous;
      return visible;
    }

    function addCompareMetric(metricId) {
      const baseMetric = metricById(state.compareBaseMetricId);
      if (!baseMetric || metricId === baseMetric.id || state.compareMetricIds.includes(metricId)) return;
      const proposed = [...state.compareMetricIds, metricId].slice(0, 3);
      if (proposed.length !== state.compareMetricIds.length + 1) {
        state.compareWarning = t("compareLimitCount");
        refreshMetricDetail(baseMetric.id);
        return;
      }
      const visible = compareVisibleForProposed(baseMetric, proposed);
      const positive = visible.length ? compareAllPositive(visible) : true;
      if (!positive && proposed.length > 1) {
        state.compareWarning = t("compareLimitRaw");
        refreshMetricDetail(baseMetric.id);
        return;
      }
      state.compareMetricIds = proposed;
      state.compareMode = proposed.length > 1 ? "indexed" : state.compareMode;
      state.compareQuery = "";
      state.compareResults = [];
      state.compareWarning = "";
      rememberCompareSet(baseMetric);
      refreshMetricDetail(baseMetric.id);
      ensureCompareHistory(baseMetric.id);
    }

    function addFirstCompareResult(metricId) {
      const baseMetric = metricById(metricId || state.compareBaseMetricId);
      if (!baseMetric) return;
      const candidates = (state.compareResults || [])
        .filter((item) => item.id !== baseMetric.id && !state.compareMetricIds.includes(item.id));
      if (candidates[0]) {
        addCompareMetric(candidates[0].id);
        return;
      }
      document.querySelector(`[data-compare-search="${CSS.escape(baseMetric.id)}"]`)?.focus();
    }

    function removeCompareMetric(metricId) {
      const baseMetric = metricById(state.compareBaseMetricId);
      state.compareMetricIds = state.compareMetricIds.filter((id) => id !== metricId);
      if (state.compareMetricIds.length <= 1 && state.compareMode === "indexed") state.compareMode = "raw";
      state.compareWarning = "";
      if (baseMetric) refreshMetricDetail(baseMetric.id);
    }

    function applyCompareSearch(query) {
      state.compareQuery = query;
      state.compareResults = normalizeSearchText(query) ? runMetricSearch(query) : [];
      renderCompareSearchResults(state.compareBaseMetricId);
    }

    function renderCompareSearchResults(metricId) {
      const metric = metricById(metricId);
      const hosts = [...document.querySelectorAll("[data-compare-results]")]
        .filter((element) => element.dataset.compareResults === metricId);
      if (!metric || !hosts.length) return;
      hosts.forEach((host) => {
        host.innerHTML = compareSearchResultsMarkup(metric);
        initCompareControls(host);
        updateMetricDetailHeight(host.closest(".metric-detail-row"));
      });
      requestAnimationFrame(updateOpenMetricDetailHeights);
    }

    function scheduleCompareSearch(query) {
      window.clearTimeout(compareDebounceTimer);
      applyCompareSearch(query);
    }

    function setCompareMode(mode) {
      const baseMetric = metricById(state.compareBaseMetricId);
      if (!baseMetric) return;
      const series = compareSeries(baseMetric);
      const visible = filterCompareSeries(series, compareTimeWindow(series));
      if (mode === "raw" && visible.length > 2) {
        state.compareWarning = t("compareUnitLimit");
      } else if (mode === "indexed" && !compareAllPositive(visible)) {
        state.compareWarning = t("compareNeedsPositive");
      } else {
        state.compareMode = mode;
        state.compareWarning = "";
      }
      refreshMetricDetail(baseMetric.id);
    }

    function setCompareRange(range) {
      const baseMetric = metricById(state.compareBaseMetricId);
      state.compareRange = range || "all";
      state.compareWarning = "";
      if (baseMetric) refreshMetricDetail(baseMetric.id);
    }

    function restoreRecentCompare(idsText) {
      const baseMetric = metricById(state.compareBaseMetricId);
      if (!baseMetric) return;
      state.compareMetricIds = String(idsText || "").split(",").filter((id) => metricById(id) && id !== baseMetric.id).slice(0, 3);
      state.compareMode = state.compareMetricIds.length > 1 ? "indexed" : "raw";
      state.compareWarning = "";
      refreshMetricDetail(baseMetric.id);
      ensureCompareHistory(baseMetric.id);
    }

    function csvEscape(value) {
      const text = String(value ?? "");
      return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    }

    function csvText(rows) {
      return `\ufeff${rows.map((row) => row.map(csvEscape).join(",")).join("\n")}\n`;
    }

    function safeFileName(value) {
      return String(value || "metric")
        .replace(/[\\/:*?"<>|]/g, "_")
        .replace(/\s+/g, "_")
        .slice(0, 80);
    }

    function downloadBlobText(filename, text) {
      const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = filename;
      link.click();
      URL.revokeObjectURL(link.href);
    }

    function csvDateSuffix() {
      return dashboardTodayKey() || new Date().toISOString().slice(0, 10);
    }

    function metricExportPoints(metric) {
      const entry = state.longHistoryData?.[metric.id] || state.longHistoryData?.[metric.history_key];
      return entry ? longHistoryPoints(entry) : (metric.history || []);
    }

    function exportSingleMetricCsv(metric) {
      const rows = [["date", "value"], ...metricExportPoints(metric).map((point) => [point.date, point.value])];
      downloadBlobText(`${safeFileName(localizedField(metric, "name"))}_${csvDateSuffix()}.csv`, csvText(rows));
    }

    function exportCompareCsv(metric) {
      const series = compareSeries(metric);
      if (series.length < 2) {
        exportSingleMetricCsv(metric);
        return;
      }
      const headers = ["date", ...series.map((item) => localizedField(item.metric, "name"))];
      const dates = [...new Set(series.flatMap((item) => item.points.map((point) => point.date)))].sort();
      const valueMaps = series.map((item) => new Map(item.points.map((point) => [point.date, point.value])));
      const rows = [headers, ...dates.map((date) => [date, ...valueMaps.map((map) => map.has(date) ? map.get(date) : "")])];
      downloadBlobText(`${safeFileName(localizedField(metric, "name"))}_compare_${csvDateSuffix()}.csv`, csvText(rows));
    }

    function exportMetricCsv(metricId) {
      const metric = metricById(metricId);
      if (!metric) return;
      ensureLongHistory().then((data) => {
        state.longHistoryData = data;
        if (state.compareBaseMetricId === metric.id && state.compareMetricIds.length) {
          exportCompareCsv(metric);
        } else {
          exportSingleMetricCsv(metric);
        }
      });
    }

    function initCsvButtons(root = document) {
      root.querySelectorAll("[data-csv-download]").forEach((button) => {
        if (button.dataset.csvBound === "true") return;
        button.dataset.csvBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          exportMetricCsv(button.dataset.csvDownload);
        });
      });
    }

    function initDailyUpdateLinks() {
      document.querySelectorAll("[data-daily-update-metric]").forEach((button) => {
        if (button.dataset.dailyUpdateBound === "true") return;
        button.dataset.dailyUpdateBound = "true";
        button.addEventListener("click", () => openMetricDetail(button.dataset.dailyUpdateMetric));
      });
      document.querySelectorAll("[data-briefing-metric]").forEach((button) => {
        if (button.dataset.briefingMetricBound === "true") return;
        button.dataset.briefingMetricBound = "true";
        button.addEventListener("click", (event) => {
          if (button.tagName === "A") event.preventDefault();
          openMetricDetail(button.dataset.briefingMetric, { updateHash: button.tagName === "A" });
        });
        if (button.tagName !== "BUTTON" && button.tagName !== "A") {
          button.addEventListener("keydown", (event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            openMetricDetail(button.dataset.briefingMetric);
          });
        }
      });
      document.querySelectorAll("[data-calendar-snapshot-open]").forEach((button) => {
        if (button.dataset.calendarSnapshotBound === "true") return;
        button.dataset.calendarSnapshotBound = "true";
        button.addEventListener("click", () => setMarketCategory("캘린더"));
      });
      document.querySelectorAll("[data-signal-history-open]").forEach((button) => {
        if (button.dataset.signalHistoryOpenBound === "true") return;
        button.dataset.signalHistoryOpenBound = "true";
        button.addEventListener("click", () => setSignalDrawerOpen(true));
      });
      document.querySelectorAll("[data-signal-metric]").forEach((button) => {
        if (button.dataset.signalMetricBound === "true") return;
        button.dataset.signalMetricBound = "true";
        button.addEventListener("click", () => openMetricDetail(button.dataset.signalMetric));
      });
      document.querySelectorAll("[data-recent-alert-key]").forEach((button) => {
        if (button.dataset.recentAlertBound === "true") return;
        button.dataset.recentAlertBound = "true";
        button.addEventListener("click", () => openRecentAlert(button.dataset.recentAlertKey));
      });
      document.querySelectorAll("[data-favorite-card]").forEach((button) => {
        if (button.dataset.favoriteCardBound === "true") return;
        button.dataset.favoriteCardBound = "true";
        button.addEventListener("click", () => openMetricDetail(button.dataset.favoriteCard));
        button.addEventListener("keydown", (event) => {
          if (event.target.closest("[data-favorite-toggle]") || event.target.closest("[data-note-open]")) return;
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          openMetricDetail(button.dataset.favoriteCard);
        });
      });
      initNoteButtons();
      initCalendarControls();
    }

    function rerenderCalendarSection() {
      const section = document.querySelector('[data-market-section][data-market-category="캘린더"]');
      if (!section) return;
      section.outerHTML = renderEventCalendar();
      initCalendarControls();
      initDailyUpdateLinks();
      updateActiveFromScroll();
    }

    function initCalendarControls(root = document) {
      root.querySelectorAll("[data-calendar-filter]").forEach((button) => {
        if (button.dataset.calendarBound === "true") return;
        button.dataset.calendarBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          const nextFilter = button.dataset.calendarFilter || "all";
          const currentIndex = calendarFilters.findIndex((filter) => filter.key === state.calendarCategoryFilter);
          const nextIndex = calendarFilters.findIndex((filter) => filter.key === nextFilter);
          state.calendarFilterDirection = nextIndex >= currentIndex ? "left" : "right";
          state.calendarCategoryFilter = nextFilter;
          state.calendarSelectedDate = "";
          rerenderCalendarSection();
        });
      });
      root.querySelectorAll("[data-calendar-date]").forEach((button) => {
        if (button.dataset.calendarBound === "true") return;
        button.dataset.calendarBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          const date = button.dataset.calendarDate || "";
          state.calendarSelectedDate = state.calendarSelectedDate === date ? "" : date;
          state.calendarViewMonth = calendarMonthKey(date) || state.calendarViewMonth;
          rerenderCalendarSection();
        });
      });
      root.querySelectorAll("[data-calendar-month]").forEach((button) => {
        if (button.dataset.calendarBound === "true") return;
        button.dataset.calendarBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          state.calendarViewMonth = button.dataset.calendarMonth || state.calendarViewMonth;
          rerenderCalendarSection();
        });
      });
      root.querySelectorAll("[data-calendar-clear]").forEach((button) => {
        if (button.dataset.calendarBound === "true") return;
        button.dataset.calendarBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          state.calendarSelectedDate = "";
          rerenderCalendarSection();
        });
      });
    }

    function initGaugeCardScrollDrag(root = document) {
      root.querySelectorAll(".gauge-component-list").forEach((scroller) => {
        if (scroller.closest(".market-diagnosis")) return;
        if (scroller.dataset.dragScrollBound === "true") return;
        scroller.dataset.dragScrollBound = "true";
        let activePointerId = null;
        let didDrag = false;
        let hasPointerCapture = false;
        let suppressClick = false;
        let startX = 0;
        let startScrollLeft = 0;
        const threshold = 6;

        const endDrag = () => {
          if (activePointerId === null) return;
          if (hasPointerCapture) {
            scroller.releasePointerCapture?.(activePointerId);
          }
          activePointerId = null;
          hasPointerCapture = false;
          scroller.classList.remove("is-dragging");
          if (didDrag) {
            suppressClick = true;
            window.setTimeout(() => {
              suppressClick = false;
            }, 120);
          }
        };

        scroller.addEventListener("pointerdown", (event) => {
          if (event.pointerType !== "mouse" || event.button !== 0) return;
          activePointerId = event.pointerId;
          didDrag = false;
          startX = event.clientX;
          startScrollLeft = scroller.scrollLeft;
        });

        scroller.addEventListener("pointermove", (event) => {
          if (event.pointerId !== activePointerId) return;
          const deltaX = event.clientX - startX;
          if (Math.abs(deltaX) > threshold) {
            didDrag = true;
            scroller.classList.add("is-dragging");
            if (!hasPointerCapture) {
              scroller.setPointerCapture?.(event.pointerId);
              hasPointerCapture = true;
            }
            event.preventDefault();
          }
          if (didDrag) {
            scroller.scrollLeft = startScrollLeft - deltaX;
          }
        });

        scroller.addEventListener("pointerup", endDrag);
        scroller.addEventListener("pointercancel", endDrag);
        scroller.addEventListener("lostpointercapture", endDrag);

        scroller.addEventListener("click", (event) => {
          if (!suppressClick) return;
          event.preventDefault();
          event.stopPropagation();
        }, true);
      });
    }

    function initGaugeHistoryControls(root = document) {
      root.querySelectorAll("[data-gauge-history-toggle]").forEach((button) => {
        if (button.dataset.gaugeHistoryBound === "true") return;
        button.dataset.gaugeHistoryBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          const key = button.dataset.gaugeHistoryToggle;
          if (!key) return;
          state.gaugeHistoryOpen[key] = !state.gaugeHistoryOpen[key];
          renderDailyUpdates();
          if (state.gaugeHistoryOpen[key]) {
            ensureGaugeHistory().then(() => renderDailyUpdates());
          }
        });
      });
      root.querySelectorAll("[data-gauge-history-range]").forEach((button) => {
        if (button.dataset.gaugeHistoryBound === "true") return;
        button.dataset.gaugeHistoryBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          const key = button.dataset.gaugeHistoryRange;
          if (!key) return;
          state.gaugeHistoryRange[key] = button.dataset.range || "3m";
          renderDailyUpdates();
        });
      });
    }
