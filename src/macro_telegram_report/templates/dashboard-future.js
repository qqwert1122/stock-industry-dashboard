    function futureData() {
      const future = DASHBOARD_DATA.future && typeof DASHBOARD_DATA.future === "object" ? DASHBOARD_DATA.future : {};
      return {
        categories: Array.isArray(future.categories) ? future.categories : defaultFutureCategories,
        glossary: future.glossary && typeof future.glossary === "object" ? future.glossary : {},
        common_readings: Array.isArray(future.common_readings) ? future.common_readings : [],
        track_record: future.track_record && typeof future.track_record === "object" ? future.track_record : { items: [], subjects: [], summary: {} },
        breakdown: future.breakdown && typeof future.breakdown === "object" ? future.breakdown : { ladders: [], summary: {} },
        company_arcs: Array.isArray(future.company_arcs) ? future.company_arcs : [],
        technologies: Array.isArray(future.technologies) ? future.technologies : [],
        summary: future.summary && typeof future.summary === "object" ? future.summary : {}
      };
    }

    function futureCategories() {
      const categories = futureData().categories.filter(Boolean);
      const unique = [...new Set([futureAllCategory, ...categories])];
      return unique.length ? unique : defaultFutureCategories;
    }

    function localizedFutureCategory(category) {
      if (category === futureAllCategory) return t("futureAll");
      if (state.language !== "en") return category || "";
      const tech = futureData().technologies.find((item) => item.category === category && item.category_en);
      const fallbacks = {
        "로봇·모빌리티": "Robotics/Mobility",
        "바이오": "Biotech",
        "에너지": "Energy",
        "우주": "Space"
      };
      return tech?.category_en || fallbacks[category] || category || "";
    }

    function localizedFutureField(item, field) {
      if (!item) return "";
      if (state.language === "en") {
        return item[`${field}_en`] || localizedText(item[field] || "");
      }
      return item[field] || "";
    }

    function futureStatusLabel(status) {
      if (status === "achieved") return t("futureStatusAchieved");
      if (status === "distant") return t("futureStatusDistant");
      if (status === "watch") return t("futureStatusWatch");
      return t("futureStatusUpcoming");
    }

    function futureNatureLabel(nature) {
      if (nature === "governance") return t("futureNatureGovernance");
      if (nature === "product") return t("futureNatureProduct");
      if (nature === "scenario") return t("futureNatureScenario");
      return t("futureNatureFrontier");
    }

    function futureInvestableLabel(investable) {
      if (investable === "false") return t("futureInvestableFalse");
      if (investable === "partial") return t("futureInvestablePartial");
      return t("futureInvestableTrue");
    }

    function futureCardId(techId) {
      return `future-card-${idSegment(techId)}`;
    }

    function futureBandId(band) {
      return `future-band-${idSegment(band)}`;
    }

    function setFutureCategory(category, options = {}) {
      state.navRoot = "future";
      state.futureView = "timeline";
      state.futureCategory = category || futureAllCategory;
      state.activeFutureId = "";
      state.trackRecordSubject = "";
      saveNavState();
      renderFilters();
      renderDailyUpdates();
      renderIndustries();
      if (options.updateHash !== false) writeDashboardHash("#future", "push");
      closeDrawerOnMobile();
    }

    function setFutureTrackRecordView(subject = "", options = {}) {
      state.navRoot = "future";
      state.futureView = "track-record";
      state.activeFutureId = "";
      state.trackRecordSubject = subject || "";
      saveNavState();
      renderFilters();
      renderDailyUpdates();
      renderIndustries();
      if (options.updateHash !== false) writeDashboardHash(currentNavHash(), options.hashMode || "push");
      closeDrawerOnMobile();
    }

    function setTrackRecordSubject(subject = "") {
      setFutureTrackRecordView(state.trackRecordSubject === subject ? "" : subject);
    }

    function setTrackRecordSort(sortKey) {
      state.trackRecordSort = sortKey || "predicted";
      renderIndustries();
      writeDashboardHash(currentNavHash(), "replace");
    }

    function filteredFutureTechnologies() {
      const category = state.futureCategory || futureAllCategory;
      return futureData().technologies.filter((item) => (
        category === futureAllCategory || item.category === category
      ));
    }

    function futureBandSortKey(band) {
      if (/^\d{4}$/.test(String(band))) return Number(band);
      if (band === "2030년대") return 2030;
      if (band === "2040년대") return 2040;
      if (band === "먼 미래") return 9990;
      if (band === "미정" || band === "연도 미정 트랙") return 9999;
      return 9000;
    }

    function localizedFutureBand(band) {
      if (state.language !== "en") return band;
      if (band === "2030년대") return "2030s";
      if (band === "2040년대") return "2040s";
      if (band === "먼 미래") return "Distant future";
      if (band === "연도 미정 트랙") return t("futureUnknownTrack");
      if (band === "미정") return "Unscheduled";
      return band;
    }

    function futureGlossaryMarkup(keys) {
      const glossary = futureData().glossary || {};
      return (keys || []).map((key) => {
        const item = glossary[key];
        if (!item) return "";
        const term = state.language === "en" ? (item.term_en || item.term) : item.term;
        const short = state.language === "en" ? (item.short_en || item.short) : item.short;
        const learnMore = item.learn_more || item.source || "";
        return `<span class="future-glossary-chip" tabindex="0">${escapeHtml(term)}
          <span class="future-tooltip">${escapeHtml(short)}${learnMore ? `<br><a href="${escapeHtml(learnMore)}" target="_blank" rel="noopener noreferrer">${escapeHtml(t("futureGlossaryLearnMore"))}</a>` : ""}</span>
        </span>`;
      }).join("");
    }

    function localizedReadingField(item, field) {
      if (!item) return "";
      if (state.language === "en") return item[`${field}_en`] || localizedText(item[field] || "");
      return item[field] || "";
    }

    function futureReadingLevelLabel(level) {
      if (state.language !== "en") return level || "";
      if (level === "입문") return t("futureReadingBeginner");
      if (level === "중급") return t("futureReadingIntermediate");
      if (level === "심화") return t("futureReadingAdvanced");
      return level || "";
    }

    function futureReadingIcon(reading) {
      const type = String(reading?.type || "").toLowerCase();
      if (type.includes("뉴스레터") || type.includes("newsletter")) return "fa-regular fa-envelope";
      if (type.includes("데이터") || type.includes("data")) return "fa-solid fa-database";
      if (type.includes("책") || type.includes("book")) return "fa-solid fa-book";
      if (type.includes("리포트") || type.includes("report")) return "fa-regular fa-file-lines";
      if (type.includes("공식") || type.includes("official")) return "fa-solid fa-building-columns";
      return "fa-regular fa-newspaper";
    }

    function futureReadingBadges(reading) {
      const badges = [];
      if (reading.trusted) badges.push(t("futureReadingTrusted"));
      if (reading.subscription) badges.push(t("futureReadingSubscription"));
      if (reading.auto_collected) badges.push(t("futureReadingAuto"));
      return badges.map((badge) => `<span class="future-reading-badge">${escapeHtml(badge)}</span>`).join("");
    }

    function futureReadingRow(reading) {
      const title = localizedReadingField(reading, "title");
      const why = localizedReadingField(reading, "why");
      const meta = [
        localizedReadingField(reading, "type"),
        reading.lang || "",
        localizedReadingField(reading, "effort"),
        localizedReadingField(reading, "cadence")
      ].filter(Boolean);
      const badges = futureReadingBadges(reading);
      return `<div class="future-reading-row">
        <span class="future-reading-icon"><i class="${escapeHtml(futureReadingIcon(reading))}" aria-hidden="true"></i></span>
        <span class="future-reading-main">
          <span class="future-reading-title-row">
            <a class="future-reading-title" href="${escapeHtml(reading.url || "#")}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)}</a>
            ${badges ? `<span class="future-reading-badges">${badges}</span>` : ""}
          </span>
          <span class="future-reading-meta">${meta.map((item) => `<span class="future-reading-chip">${escapeHtml(item)}</span>`).join("")}</span>
          ${why ? `<p class="future-reading-why">${escapeHtml(why)}</p>` : ""}
        </span>
        <a class="future-reading-link" href="${escapeHtml(reading.url || "#")}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHtml(t("futureReadingOpen"))}">
          <i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i>
        </a>
      </div>`;
    }

    function futureReadingsMarkup(readings, options = {}) {
      const items = Array.isArray(readings) ? readings.filter((item) => item && item.url) : [];
      if (!items.length) return "";
      const levels = ["입문", "중급", "심화"];
      const sections = levels.map((level) => {
        const levelItems = items.filter((item) => item.level === level);
        if (!levelItems.length) return "";
        return `<details class="future-reading-level" ${level === "입문" ? "open" : ""}>
          <summary>${escapeHtml(futureReadingLevelLabel(level))} <span>${levelItems.length}</span></summary>
          <div class="future-reading-list">${levelItems.map(futureReadingRow).join("")}</div>
        </details>`;
      }).join("");
      const title = options.common ? t("futureReadingsCommonTitle") : t("futureReadingsTitle");
      return `<section class="future-readings ${options.common ? "future-common-readings" : ""}">
        <h3 class="future-readings-title">${escapeHtml(title)}</h3>
        ${sections}
        <p class="future-readings-note">${escapeHtml(t("futureReadingNotice"))}</p>
      </section>`;
    }

    function futureMetricMarkup(metric) {
      if (!metric?.id) return "";
      const value = metric.display_value || "";
      const change = metric.change_pct_label || metric.change_abs_label || "";
      return `<button class="future-metric-chip" type="button" data-future-metric="${escapeHtml(metric.id)}">
        <span>
          <span class="future-metric-name">${escapeHtml(localizedField(metric, "name"))}</span>
          <span class="future-metric-value">${escapeHtml([value, change].filter(Boolean).join(" · "))}</span>
        </span>
        ${chart(metric.history || [], "chart-mini", metric)}
      </button>`;
    }

    function futureCompanyMarkup(company) {
      const metricId = company?.metric_id || "";
      const label = state.language === "en" ? (company?.label_en || company?.label || company?.symbol || "") : (company?.label || company?.symbol || "");
      const change = company?.change_pct_label || "";
      const disabled = metricId ? "" : " disabled";
      const dataAttr = metricId ? ` data-future-company="${escapeHtml(metricId)}"` : "";
      return `<button class="future-company-chip" type="button"${dataAttr}${disabled}>
        <span class="future-company-name">${escapeHtml(label)}</span>
        ${change ? `<span class="future-company-change ${directionClass(company.change_pct)}">${escapeHtml(change)}</span>` : ""}
      </button>`;
    }

    function localizedBreakdownField(item, field) {
      if (!item) return "";
      if (state.language === "en") return item[`${field}_en`] || localizedText(item[field] || "");
      return item[field] || "";
    }

    function futureBreakdownGapLabel(requirement) {
      if (requirement?.satisfied) return t("futureBreakdownGapMet");
      const gapSteps = Number(requirement?.gap_steps);
      if (Number.isFinite(gapSteps) && gapSteps > 0) {
        return state.language === "en"
          ? `${t("futureBreakdownGapSteps")} ${gapSteps} ${t("futureBreakdownStepSuffix")}`
          : `${t("futureBreakdownGapSteps")} ${gapSteps}${t("futureBreakdownStepSuffix")}`;
      }
      return "";
    }

    function futureBreakdownBadges(requirement) {
      const badges = [];
      if (requirement?.is_bottleneck) badges.push({ label: t("futureBreakdownBottleneck"), className: "is-bottleneck" });
      const gapLabel = futureBreakdownGapLabel(requirement);
      if (gapLabel) badges.push({ label: gapLabel, className: requirement?.satisfied ? "is-satisfied" : "" });
      if (requirement?.confidence === "low") badges.push({ label: t("futureBreakdownLowConfidence"), className: "is-low" });
      if (requirement?.stale) badges.push({ label: t("futureBreakdownStale"), className: "is-stale" });
      return badges.map((badge) => `<span class="future-breakdown-badge ${badge.className}">${escapeHtml(badge.label)}</span>`).join("");
    }

    function futureBreakdownStateMarkup(requirement) {
      const current = localizedBreakdownField(requirement, "current_label");
      const target = localizedBreakdownField(requirement, "target_label");
      if (!current && !target) return "";
      return `<div class="future-breakdown-state">
        ${current ? `<span><b>${escapeHtml(t("futureBreakdownCurrent"))}</b>${escapeHtml(current)}</span>` : ""}
        ${target ? `<span><b>${escapeHtml(t("futureBreakdownRequired"))}</b>${escapeHtml(target)}</span>` : ""}
      </div>`;
    }

    function futureBreakdownLadderMarkup(requirement) {
      const rungs = Array.isArray(requirement?.ladder?.rungs) ? requirement.ladder.rungs : [];
      if (!rungs.length) return "";
      const currentIndex = Number(requirement.current_index);
      const requiredIndex = Number(requirement.required_index);
      const items = rungs.map((rung) => {
        const index = Number(rung.index);
        const classes = [
          "future-ladder-rung",
          Number.isFinite(currentIndex) && index === currentIndex ? "is-current" : "",
          Number.isFinite(requiredIndex) && index === requiredIndex ? "is-required" : ""
        ].filter(Boolean).join(" ");
        const label = state.language === "en" ? (rung.label_en || rung.label || rung.level) : (rung.label || rung.level);
        const desc = state.language === "en" ? (rung.desc_en || rung.desc || "") : (rung.desc || "");
        const level = rung.level || "";
        return `<span class="${classes}" tabindex="0" aria-label="${escapeHtml([level, label, desc].filter(Boolean).join(": "))}">
          ${escapeHtml(label)}
          ${desc ? `<span class="future-tooltip">${escapeHtml(level ? `${level}: ${desc}` : desc)}</span>` : ""}
        </span>`;
      }).join("");
      return `<div class="future-ladder" aria-label="${escapeHtml(localizedBreakdownField(requirement.ladder, "name"))}">${items}</div>`;
    }

    function futureBreakdownPartyChip(party) {
      const label = state.language === "en" ? (party?.label_en || party?.label || party?.symbol || "") : (party?.label || party?.symbol || "");
      const change = party?.change_pct_label || "";
      if (!label) return "";
      if (party?.metric_id) {
        return `<button class="future-breakdown-chip" type="button" data-breakdown-company="${escapeHtml(party.metric_id)}">
          <span>${escapeHtml(label)}</span>${change ? `<span class="${directionClass(party.change_pct)}">${escapeHtml(change)}</span>` : ""}
        </button>`;
      }
      return `<span class="future-breakdown-chip">${escapeHtml(label)}</span>`;
    }

    function futureBreakdownPartyRow(label, parties) {
      const chips = (Array.isArray(parties) ? parties : []).map(futureBreakdownPartyChip).filter(Boolean).join("");
      if (!chips) return "";
      return `<div class="future-breakdown-party">
        <span class="future-breakdown-party-label">${escapeHtml(label)}</span>
        ${chips}
      </div>`;
    }

    function futureBreakdownMetricMarkup(requirement) {
      const metric = requirement?.metric || null;
      const fallback = localizedBreakdownField(requirement, "metric_label");
      if (metric?.id) {
        const value = [metric.display_value || "", metric.change_pct_label || metric.change_abs_label || ""].filter(Boolean).join(" · ");
        return `<button class="future-breakdown-chip" type="button" data-breakdown-metric="${escapeHtml(metric.id)}">
          <span>${escapeHtml(localizedField(metric, "name") || fallback || t("futureBreakdownMetric"))}</span>
          ${value ? `<span>${escapeHtml(value)}</span>` : ""}
        </button>`;
      }
      return fallback ? `<span class="future-breakdown-chip">${escapeHtml(fallback)}</span>` : "";
    }

    function futureBreakdownSourceMarkup(requirement) {
      const source = requirement?.source || "";
      if (!source) return "";
      const label = localizedBreakdownField(requirement, "source_label") || t("futureBreakdownSource");
      return `<a class="future-breakdown-chip" href="${escapeHtml(source)}" target="_blank" rel="noopener noreferrer">
        ${escapeHtml(label)}
      </a>`;
    }

    function futureBreakdownRequirementMarkup(requirement, tech) {
      const rowId = `future-breakdown-${idSegment(tech?.id || "tech")}-${idSegment(requirement?.id || "requirement")}`;
      const badges = futureBreakdownBadges(requirement);
      const ladder = futureBreakdownLadderMarkup(requirement);
      const stateMarkup = futureBreakdownStateMarkup(requirement);
      const metric = futureBreakdownMetricMarkup(requirement);
      const source = futureBreakdownSourceMarkup(requirement);
      const meta = [metric, source].filter(Boolean).join("");
      const classes = [
        "future-breakdown-row",
        requirement?.is_bottleneck ? "is-bottleneck" : "",
        requirement?.confidence === "low" ? "is-low-confidence" : "",
        requirement?.stale ? "is-stale" : ""
      ].filter(Boolean).join(" ");
      return `<section class="${classes}" id="${escapeHtml(rowId)}" data-breakdown-row="${escapeHtml(requirement?.flow_id || "")}">
        <div class="future-breakdown-head">
          <div class="future-breakdown-name">${escapeHtml(localizedBreakdownField(requirement, "name"))}</div>
          ${badges ? `<div class="future-breakdown-badges">${badges}</div>` : ""}
        </div>
        ${stateMarkup}
        ${ladder}
        <div class="future-breakdown-copy">
          <p class="future-breakdown-gap">${escapeHtml(localizedBreakdownField(requirement, "gap"))}</p>
          <p>${escapeHtml(localizedBreakdownField(requirement, "what"))}</p>
        </div>
        ${futureBreakdownPartyRow(t("futureBreakdownAchievedBy"), requirement?.achieved_by)}
        ${futureBreakdownPartyRow(t("futureBreakdownPursuing"), requirement?.pursuing)}
        ${meta ? `<div class="future-breakdown-meta">${meta}</div>` : ""}
      </section>`;
    }

    function futureBreakdownMarkup(tech) {
      const requirements = Array.isArray(tech?.breakdown?.requirements) ? tech.breakdown.requirements : [];
      if (!requirements.length) return "";
      return `<section class="future-breakdown">
        <h3 class="future-breakdown-title">${escapeHtml(t("futureBreakdownTitle"))}</h3>
        <div class="future-breakdown-list">
          ${requirements.map((requirement) => futureBreakdownRequirementMarkup(requirement, tech)).join("")}
        </div>
      </section>`;
    }

    function trackRecordData() {
      const track = futureData().track_record || {};
      return {
        items: Array.isArray(track.items) ? track.items : [],
        subjects: Array.isArray(track.subjects) ? track.subjects : [],
        summary: track.summary && typeof track.summary === "object" ? track.summary : {}
      };
    }

    function localizedTrackField(item, field) {
      if (!item) return "";
      if (state.language === "en") return item[`${field}_en`] || localizedText(item[field] || "");
      return item[field] || "";
    }

    function trackRecordStatusLabel(status) {
      if (status === "early") return t("futureTrackStatusEarly");
      if (status === "on_time") return t("futureTrackStatusOnTime");
      if (status === "late") return t("futureTrackStatusLate");
      if (status === "missed") return t("futureTrackStatusMissed");
      return t("futureTrackStatusPending");
    }

    function trackRecordErrorLabel(item) {
      const status = item?.status || "pending";
      const error = Number(item?.error_years);
      if (status === "pending") return t("futureTrackRecordStillOpen");
      if (status === "missed") {
        return Number.isFinite(error)
          ? `${Math.abs(error)}${t("futureTrackYearSuffix")}+`
          : t("futureTrackStatusMissed");
      }
      if (!Number.isFinite(error)) return "";
      if (error === 0) return t("futureTrackRecordExact");
      const abs = Math.abs(error);
      return error < 0
        ? `${abs}${t("futureTrackYearSuffix")} ${t("futureTrackRecordEarly")}`
        : `${abs}${t("futureTrackYearSuffix")} ${t("futureTrackRecordLate")}`;
    }

    function trackRecordSubjectName(subject) {
      if (state.language === "en") return subject?.name_en || subject?.name || "";
      return subject?.name || "";
    }

    function trackRecordSubjectSummary(subject) {
      if (state.language === "en") return subject?.summary_en || subject?.summary || "";
      return subject?.summary || "";
    }

    function trackRecordSubjectScore(subject) {
      if (state.language === "en") return subject?.score_label_en || subject?.score_label || "";
      return subject?.score_label || "";
    }

    function filteredTrackRecordItems() {
      const items = trackRecordData().items.slice();
      const filtered = state.trackRecordSubject
        ? items.filter((item) => item.by_id === state.trackRecordSubject)
        : items;
      return filtered.sort((a, b) => {
        if (state.trackRecordSort === "error") {
          return Number(b.absolute_error_years ?? -1) - Number(a.absolute_error_years ?? -1)
            || Number(a.predicted_for_year || 9999) - Number(b.predicted_for_year || 9999);
        }
        if (state.trackRecordSort === "subject") {
          return String(localizedTrackField(a, "predicted_by")).localeCompare(String(localizedTrackField(b, "predicted_by")), state.language === "en" ? "en" : "ko")
            || Number(a.predicted_for_year || 9999) - Number(b.predicted_for_year || 9999);
        }
        return Number(a.predicted_for_year || 9999) - Number(b.predicted_for_year || 9999)
          || String(localizedTrackField(a, "name")).localeCompare(String(localizedTrackField(b, "name")), state.language === "en" ? "en" : "ko");
      });
    }

    function trackRecordAxisRange(items) {
      const years = items.flatMap((item) => [
        Number(item.predicted_for_year),
        Number(item.display_actual_year || item.actual_year)
      ]).filter(Number.isFinite);
      const min = Math.min(...years, 1950);
      const max = Math.max(...years, new Date().getFullYear());
      return { min: min - 3, max: max + 3 };
    }

    function trackRecordX(year, range) {
      const value = Number(year);
      if (!Number.isFinite(value) || range.max <= range.min) return 0;
      return Math.max(0, Math.min(100, ((value - range.min) / (range.max - range.min)) * 100));
    }

    function trackRecordAxisTicks(range) {
      const span = Math.max(1, range.max - range.min);
      const step = span > 75 ? 20 : span > 36 ? 10 : 5;
      const start = Math.ceil(range.min / step) * step;
      const end = Math.floor(range.max / step) * step;
      const ticks = [];
      for (let year = start; year <= end; year += step) ticks.push(year);
      return ticks.length ? ticks : [Math.round(range.min), Math.round(range.max)];
    }

    function trackRecordTickMarkup(ticks, range, className = "track-record-grid-line") {
      return ticks.map((year) => {
        const x = trackRecordX(year, range).toFixed(3);
        const label = className === "track-record-axis-label" ? escapeHtml(String(year)) : "";
        return `<span class="${className}" style="--x:${x}%">${label}</span>`;
      }).join("");
    }

    function trackRecordAxisRow(range, ticks) {
      return `<div class="track-record-axis-row" aria-hidden="true">
        <div class="track-record-axis-space"></div>
        <div class="track-record-axis-canvas">
          ${trackRecordTickMarkup(ticks, range, "track-record-axis-label")}
        </div>
      </div>`;
    }

    function trackRecordTimeline(item, range, ticks) {
      const predictedYear = Number(item.predicted_for_year);
      const actualYear = Number(item.display_actual_year || item.actual_year);
      const predictedX = trackRecordX(predictedYear, range);
      const actualX = trackRecordX(actualYear, range);
      const hasPredicted = Number.isFinite(predictedYear);
      const hasActual = Number.isFinite(actualYear);
      const yearGap = hasPredicted && hasActual ? Math.abs(actualYear - predictedYear) : 0;
      const start = Math.min(predictedX, actualX);
      const width = Math.abs(actualX - predictedX);
      const hasSpan = hasPredicted && hasActual && yearGap >= 6 && width >= 7;
      const actualLabel = item.open_ended ? t("futureTrackRecordNow") : String(item.actual_year || item.display_actual_year || "");
      const errorLabel = trackRecordErrorLabel(item);
      return `<span class="track-record-timeline" aria-label="${escapeHtml(localizedTrackField(item, "name"))}">
        ${trackRecordTickMarkup(ticks, range)}
        ${hasSpan ? `<span class="track-record-predicted-year" style="--x:${predictedX.toFixed(3)}%">${escapeHtml(String(item.predicted_for_year || ""))}</span>` : ""}
        ${hasSpan ? `<span class="track-record-predicted-dot" style="--x:${predictedX.toFixed(3)}%"></span>` : ""}
        ${hasSpan ? `<span class="track-record-span" style="--start:${start.toFixed(3)}%;--width:${width.toFixed(3)}%">${escapeHtml(errorLabel)}</span>` : ""}
        ${hasActual ? `<span class="track-record-actual-year" style="--x:${actualX.toFixed(3)}%">${escapeHtml(actualLabel)}</span>` : ""}
        ${hasActual ? `<span class="track-record-actual-dot" style="--x:${actualX.toFixed(3)}%"></span>` : ""}
        ${!hasSpan && hasActual ? `<span class="track-record-pill" style="--x:${actualX.toFixed(3)}%">${escapeHtml(errorLabel || trackRecordStatusLabel(item.status))}</span>` : ""}
      </span>`;
    }

    function trackRecordSourceLinks(item) {
      const sourceLabel = localizedTrackField(item, "source_label") || t("futureTrackRecordSource");
      const actualLabel = localizedTrackField(item, "actual_source_label") || t("futureTrackRecordActualBasis");
      return `<div class="track-record-links">
        ${item.source ? `<a href="${escapeHtml(item.source)}" target="_blank" rel="noopener">${escapeHtml(sourceLabel)}</a>` : ""}
        ${item.actual_source ? `<a href="${escapeHtml(item.actual_source)}" target="_blank" rel="noopener">${escapeHtml(actualLabel)}</a>` : ""}
      </div>`;
    }

    function trackRecordRow(item, range, ticks) {
      const predictedText = `${localizedTrackField(item, "predicted_for") || item.predicted_for_year || ""}`;
      const actualText = item.actual_year ? `${item.actual_year}` : t("futureTrackRecordStillOpen");
      return `<details class="track-record-row status-${escapeHtml(item.status || "pending")}" data-track-status="${escapeHtml(item.status || "pending")}">
        <summary>
          <span class="track-record-row-main">
            <span class="track-record-title-row">
              <span class="track-record-name">${escapeHtml(localizedTrackField(item, "name"))}</span>
              <span class="track-record-by">${escapeHtml(localizedTrackField(item, "predicted_by"))}, ${escapeHtml(String(item.predicted_in || ""))}</span>
            </span>
            <span class="track-record-years">${escapeHtml(predictedText)} → ${escapeHtml(actualText)}</span>
          </span>
          <span class="track-record-chart">${trackRecordTimeline(item, range, ticks)}</span>
          <span class="track-record-status">
            <span class="track-record-pill">${escapeHtml(trackRecordStatusLabel(item.status))}</span>
            <span class="track-record-error">${escapeHtml(trackRecordErrorLabel(item))}</span>
          </span>
        </summary>
        <div class="track-record-detail">
          <p><span>${escapeHtml(t("futureTrackRecordWhat"))}</span>${escapeHtml(localizedTrackField(item, "what"))}</p>
          <p><span>${escapeHtml(t("futureTrackRecordOutcome"))}</span>${escapeHtml(localizedTrackField(item, "outcome"))}</p>
          <p><span>${escapeHtml(t("futureTrackRecordLesson"))}</span>${escapeHtml(localizedTrackField(item, "lesson"))}</p>
          <p><span>${escapeHtml(t("futureTrackRecordActualBasis"))}</span>${escapeHtml(localizedTrackField(item, "actual_label"))}</p>
          ${trackRecordSourceLinks(item)}
        </div>
      </details>`;
    }

    function renderTrackRecordScorecards(subjects) {
      const summary = trackRecordData().summary || {};
      const cards = [
        `<button class="track-score-card ${state.trackRecordSubject ? "" : "is-active"}" type="button" data-track-subject="" aria-label="${escapeHtml(`${t("futureTrackRecordAllSubjects")} · ${summary.judged_count || 0}${t("futureTrackRecordJudgedSuffix")}`)}">
          <span class="track-score-name">${escapeHtml(t("futureTrackRecordAllSubjects"))}</span>
          <span class="track-score-summary">${escapeHtml(`${summary.judged_count || 0}${t("futureTrackRecordJudgedSuffix")} · ${summary.on_time_count || 0}${t("futureTrackRecordHitSuffix")}`)}</span>
        </button>`,
        ...subjects.map((subject) => `<button class="track-score-card ${state.trackRecordSubject === subject.id ? "is-active" : ""}" type="button" data-track-subject="${escapeHtml(subject.id)}" aria-label="${escapeHtml(`${trackRecordSubjectName(subject)} · ${trackRecordSubjectSummary(subject)}`)}">
          <span class="track-score-name">${escapeHtml(trackRecordSubjectName(subject))}</span>
          <span class="track-score-summary">${escapeHtml(trackRecordSubjectSummary(subject))}</span>
        </button>`)
      ];
      return `<div class="track-score-grid">${cards.join("")}</div>`;
    }

    const companyArcColors = ["var(--chart-down)", "var(--chart-up)", "var(--blue)", "#10b981", "#a855f7", "#f59e0b"];

    function companyArcEndLabel(end) {
      if (end === "bankrupt") return t("futureCompanyArcBankrupt");
      if (end === "acquired") return t("futureCompanyArcAcquired");
      if (end === "delisted") return t("futureCompanyArcDelisted");
      return t("futureCompanyArcOngoing");
    }

    function companyArcEndMarker(end) {
      if (end === "bankrupt" || end === "delisted") return "×";
      if (end === "acquired") return "→";
      return "╌";
    }

    function companyArcSelection(arc) {
      const chapters = Array.isArray(arc.chapters) ? arc.chapters : [];
      const fallback = chapters.length;
      const stored = Number(state.companyArcChapters[arc.id]);
      const index = Number.isInteger(stored) ? Math.max(0, Math.min(stored, fallback)) : fallback;
      const chapter = index < chapters.length ? chapters[index] : null;
      return { index, chapter, start: chapter?.from ?? arc.range?.start ?? arc.as_of, end: chapter?.to ?? arc.range?.end ?? arc.as_of };
    }

    function companyArcMarketCapLabel(value) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric) || numeric <= 0) return "";
      if (numeric >= 1000) return `$${(numeric / 1000).toFixed(numeric >= 10000 ? 0 : 1)}T`;
      if (numeric < 1) return `$${Math.max(numeric * 1000, 1).toFixed(0)}M`;
      return `$${numeric.toFixed(numeric < 10 ? 1 : 0)}B`;
    }

    function companyArcLogScale(values, top, bottom) {
      const positive = (values || []).map(Number).filter((value) => Number.isFinite(value) && value > 0);
      if (!positive.length) return null;
      let minLog = Math.log10(Math.max(Math.min(...positive) * 0.75, 0.001));
      let maxLog = Math.log10(Math.max(Math.max(...positive) * 1.25, 0.01));
      const minimumSpan = 0.35;
      if (maxLog - minLog < minimumSpan) {
        const center = (minLog + maxLog) / 2;
        minLog = center - minimumSpan / 2;
        maxLog = center + minimumSpan / 2;
      }
      const logSpan = maxLog - minLog;
      return {
        minLog,
        maxLog,
        logSpan,
        yFor: (value) => top + (1 - ((Math.log10(Math.max(Number(value), 0.0001)) - minLog) / logSpan)) * (bottom - top)
      };
    }

    function companyArcSvg(arc) {
      const selection = companyArcSelection(arc);
      const isMobileChart = mobileDrawerQuery.matches;
      const span = Math.max(selection.end - selection.start, 1);
      const width = Math.min(2400, Math.max(
        isMobileChart ? 520 : 800,
        detailChartAvailableWidth(),
        Math.ceil(span * (isMobileChart ? 13 : 11))
      ));
      const height = isMobileChart ? 158 : 190;
      const axisWidth = isMobileChart ? 40 : 42;
      const axisGuideStart = axisWidth - 2;
      const plot = { left: 1, right: 1, top: isMobileChart ? 30 : 34, bottom: 44 };
      const axisY = height - 32;
      const plotBottom = axisY - 12;
      const innerWidth = width - plot.left - plot.right;
      const innerHeight = plotBottom - plot.top;
      const xFor = (year) => plot.left + ((Number(year) - selection.start) / span) * innerWidth;
      const visibleSeries = (arc.companies || []).flatMap((company) =>
        (company.series || []).filter((point) => point.y >= selection.start && point.y <= selection.end)
      );
      const marketCaps = visibleSeries.map((point) => Number(point.v)).filter((value) => value > 0);
      const scale = companyArcLogScale(marketCaps, plot.top, plotBottom);
      const minLog = scale?.minLog ?? -3;
      const maxLog = scale?.maxLog ?? 1;
      const logSpan = scale?.logSpan ?? 4;
      const yFor = scale?.yFor || (() => plotBottom);
      const clipId = `company-arc-clip-${idSegment(arc.id)}`;
      const tickCount = Math.max(4, Math.min(12, Math.round(width / 150) + 1));
      const yearTicks = [...new Set(Array.from({ length: tickCount }, (_, index) => Math.round(selection.start + (span * index) / (tickCount - 1))))];
      const horizontalTickValues = [0, .5, 1].map((ratio) => {
        const logValue = maxLog - logSpan * ratio;
        const value = Math.pow(10, logValue);
        const y = plot.top + innerHeight * ratio;
        const label = companyArcMarketCapLabel(value);
        return { label, y };
      });
      const yAxis = horizontalTickValues.map((tick, index) => `<text class="company-arc-axis-label" data-company-arc-axis-ratio="${index / 2}" x="${axisGuideStart}" y="${tick.y.toFixed(2)}" text-anchor="end" dominant-baseline="middle">${escapeHtml(tick.label)}</text>`).join("");
      const horizontalTicks = horizontalTickValues.map((tick) => `<line class="chart-background-line level-line" x1="${plot.left}" x2="${width - plot.right}" y1="${tick.y.toFixed(2)}" y2="${tick.y.toFixed(2)}"></line>`).join("");
      const verticalTicks = yearTicks.map((year) => {
        const x = xFor(year);
        const anchor = x <= plot.left + 2 ? "start" : x >= width - plot.right - 2 ? "end" : "middle";
        return `<line class="chart-background-line" x1="${x.toFixed(2)}" x2="${x.toFixed(2)}" y1="${plot.top}" y2="${axisY}"></line><text class="company-arc-axis-label" x="${x.toFixed(2)}" y="${height - 12}" text-anchor="${anchor}">${year}</text>`;
      }).join("");
      const events = (arc.events || []).filter((event) => event.year >= selection.start && event.year <= selection.end).map((event, index) => {
        const x = xFor(event.year);
        const y = 9 + (index % 2) * 10;
        const label = localizedFutureField(event, "label");
        const anchor = x <= 64 ? "start" : x >= width - 64 ? "end" : "middle";
        return `<path class="company-arc-event" d="M ${x.toFixed(2)} ${plot.top - 8} l 4 4 l -4 4 l -4 -4 z"></path><text class="company-arc-event-label" x="${x.toFixed(2)}" y="${y}" text-anchor="${anchor}">${escapeHtml(label)}</text>`;
      }).join("");
      const lines = (arc.companies || []).map((company, index) => {
        const points = (company.series || []).filter((point) => point.y >= selection.start && point.y <= selection.end);
        if (!points.length) return "";
        const color = companyArcColors[index % companyArcColors.length];
        const path = points.map((point, pointIndex) => `${pointIndex ? "L" : "M"} ${xFor(point.y).toFixed(2)} ${yFor(point.v).toFixed(2)}`).join(" ");
        const first = points[0];
        const last = points[points.length - 1];
        const startsHere = first.y === (company.series || [])[0]?.y;
        const endsHere = last.y === (company.series || []).at(-1)?.y;
        const label = localizedFutureField(company, "name");
        const labelOffset = -7 - (index % 3) * 12;
        const labelY = yFor(first.v) + labelOffset;
        const scalePoints = points.map((point) => `<circle class="company-arc-scale-point" data-arc-x="${xFor(point.y).toFixed(2)}" data-arc-value="${Number(point.v)}"></circle>`).join("");
        const turningPoints = points.filter((point) => point.kind && point.kind !== "year_end").map((point) => {
          const x = xFor(point.y);
          const y = yFor(point.v);
          const pointLabel = localizedFutureField(point, "label") || `${point.y} ${point.kind}`;
          return `<circle class="company-arc-turning" data-arc-value="${Number(point.v)}" cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="5"><title>${escapeHtml(pointLabel)}</title></circle>`;
        }).join("");
        return `<g class="company-arc-company" role="button" tabindex="0" data-company-arc-company="${escapeHtml(company.symbol)}" style="--arc-color:${color}">
          ${scalePoints}
          ${points.length > 1 ? `<path class="company-arc-line ${company.metric !== "market_cap" ? "is-alternate" : ""}" d="${path}"></path>` : ""}
          ${turningPoints}
          ${startsHere ? `<circle class="company-arc-start" data-arc-value="${Number(first.v)}" cx="${xFor(first.y).toFixed(2)}" cy="${yFor(first.v).toFixed(2)}" r="5"></circle><text class="company-arc-line-label" data-arc-value="${Number(first.v)}" data-arc-offset="${labelOffset}" x="${(xFor(first.y) + 7).toFixed(2)}" y="${labelY.toFixed(2)}">${escapeHtml(label)}</text>` : ""}
          ${endsHere ? `<text class="company-arc-end" data-arc-value="${Number(last.v)}" x="${xFor(last.y).toFixed(2)}" y="${(yFor(last.v) + 5).toFixed(2)}" text-anchor="middle">${escapeHtml(companyArcEndMarker(company.end))}</text>` : ""}
        </g>`;
      }).join("");
      return `<div class="detail-chart company-arc-detail-chart">
        <svg class="chart detail-chart-axis" viewBox="0 0 ${axisWidth} ${height}" width="${axisWidth}" height="${height}" aria-hidden="true">
          ${yAxis}
          <line x1="${axisGuideStart}" y1="${axisY}" x2="${axisWidth}" y2="${axisY}" class="axis-line"></line>
        </svg>
        <div class="detail-chart-scroll">
          <svg class="chart chart-detail company-arc-svg" style="--detail-chart-width:${width}px" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="${escapeHtml(localizedFutureField(arc, "name"))}" data-company-arc-plot data-chart-top="${plot.top}" data-chart-bottom="${plotBottom}">
            <defs><clipPath id="${clipId}"><rect x="${plot.left}" y="${plot.top - 10}" width="${innerWidth}" height="${innerHeight + 18}"></rect></clipPath></defs>
            ${selection.chapter ? `<rect class="company-arc-chapter-band" x="${plot.left}" y="${plot.top}" width="${innerWidth}" height="${innerHeight}"></rect>` : ""}
            ${horizontalTicks}${verticalTicks}
            <line x1="${plot.left}" y1="${axisY}" x2="${width - plot.right}" y2="${axisY}" class="axis-line"></line>
            ${events}<g clip-path="url(#${clipId})">${lines}</g>
          </svg>
        </div>
      </div><p class="company-arc-axis-caption">${escapeHtml(t("futureCompanyArcIndex"))}</p>`;
    }

    function companyArcDetailMarkup(arc) {
      const symbol = state.companyArcCompanies[arc.id] || "";
      const company = (arc.companies || []).find((item) => item.symbol === symbol);
      if (!company) return "";
      const confidence = company.confidence === "exact" ? t("futureCompanyArcExact") : t("futureCompanyArcApprox");
      const endNote = localizedFutureField(company, "end_note");
      const metric = company.metric === "market_cap" ? t("futureCompanyArcMarketCap") : localizedFutureField(company, "metric_label");
      const turningSummary = (company.series || []).filter((point) => point.kind && point.kind !== "year_end").map((point) => localizedFutureField(point, "label")).filter(Boolean).join(" · ");
      return `<aside class="company-arc-detail">
        <div class="company-arc-detail-copy">
          <strong>${escapeHtml(localizedFutureField(company, "name"))} · ${escapeHtml(companyArcEndLabel(company.end))}</strong>
          <p>${escapeHtml(localizedFutureField(company, "summary"))}</p>
          ${turningSummary ? `<p>${escapeHtml(turningSummary)}</p>` : ""}
          ${endNote ? `<p>${escapeHtml(endNote)}</p>` : ""}
          <div class="company-arc-detail-meta"><span>${escapeHtml(metric)}</span><span>·</span><span>${escapeHtml(t("futureCompanyArcConfidence"))}: ${escapeHtml(confidence)}</span><span>·</span><span>${escapeHtml(t("futureCompanyArcAsOf"))} ${escapeHtml(String(arc.as_of))}</span></div>
        </div>
        ${company.source_url ? `<a href="${escapeHtml(company.source_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(t("futureCompanyArcSource"))}</a>` : ""}
      </aside>`;
    }

    function companyArcLegendMarkup(arc) {
      return `<div class="company-arc-legend">${(arc.companies || []).map((company, index) => {
        const color = companyArcColors[index % companyArcColors.length];
        const alternate = company.metric !== "market_cap";
        return `<button class="${alternate ? "is-alternate" : ""}" type="button" data-company-arc-company="${escapeHtml(company.symbol)}" style="--arc-color:${color}"><i></i><span>${escapeHtml(localizedFutureField(company, "name"))}</span>${alternate ? `<span class="company-arc-metric-badge">${escapeHtml(localizedFutureField(company, "metric_label"))}</span>` : ""}</button>`;
      }).join("")}</div>`;
    }

    function companyArcTurningMarkup(arc) {
      const selection = companyArcSelection(arc);
      const items = (arc.companies || []).flatMap((company, companyIndex) =>
        (company.series || [])
          .filter((point) => point.kind && point.kind !== "year_end" && point.y >= selection.start && point.y <= selection.end)
          .map((point) => ({ company, companyIndex, point }))
      );
      if (!items.length) return "";
      return `<div class="company-arc-turning-list">${items.map(({ company, companyIndex, point }) => {
        const color = companyArcColors[companyIndex % companyArcColors.length];
        const label = localizedFutureField(point, "label") || `${point.y} ${point.kind}`;
        const observed = String(point.date || point.y).replaceAll("-", ".");
        return `<button type="button" data-company-arc-company="${escapeHtml(company.symbol)}" style="--arc-color:${color}"><i></i><strong>${escapeHtml(localizedFutureField(company, "name"))}</strong><span>${escapeHtml(label)}</span><time>${escapeHtml(observed)}</time></button>`;
      }).join("")}</div>`;
    }

    function companyArcVisualMarkup(arc) {
      const selection = companyArcSelection(arc);
      const chapters = arc.chapters || [];
      const title = selection.chapter ? `${selection.start}–${selection.end}` : t("futureCompanyArcAll");
      const note = selection.chapter ? localizedFutureField(selection.chapter, "note") : localizedFutureField(arc, "intro");
      return `<div class="company-arc-chart-shell">${companyArcSvg(arc)}</div>
        ${companyArcTurningMarkup(arc)}
        ${companyArcLegendMarkup(arc)}
        <div class="company-arc-stepper">
          <button type="button" data-company-arc-step="-1" aria-label="${escapeHtml(t("futureCompanyArcPrevious"))}" ${selection.index === 0 ? "disabled" : ""}><i class="fa-solid fa-chevron-left" aria-hidden="true"></i></button>
          <div class="company-arc-stepper-copy"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(note)}</span></div>
          <button type="button" data-company-arc-step="1" aria-label="${escapeHtml(t("futureCompanyArcNext"))}" ${selection.index === chapters.length ? "disabled" : ""}><i class="fa-solid fa-chevron-right" aria-hidden="true"></i></button>
        </div>
        ${companyArcDetailMarkup(arc)}`;
    }

    function companyArcCardMarkup(arc, index) {
      return `<details class="company-arc-card" data-company-arc="${escapeHtml(arc.id)}" ${index === 0 ? "open" : ""}>
        <summary><span class="company-arc-summary-copy"><strong>${escapeHtml(localizedFutureField(arc, "name"))}</strong><span>${escapeHtml(localizedFutureField(arc, "intro"))}</span></span><span class="company-arc-summary-meta">${escapeHtml(String((arc.companies || []).length))} ${escapeHtml(t("futureCompanyArcCompanies"))} · ${escapeHtml(t("futureCompanyArcAsOf"))} ${escapeHtml(String(arc.as_of))} <i class="fa-solid fa-chevron-down company-arc-summary-icon" aria-hidden="true"></i></span></summary>
        <div class="company-arc-body"><p class="company-arc-notice">${escapeHtml(t("futureCompanyArcNotice"))} · ${escapeHtml(t("futureCompanyArcAsOf"))} ${escapeHtml(String(arc.as_of))}</p><div data-company-arc-visual>${companyArcVisualMarkup(arc)}</div></div>
      </details>`;
    }

    function renderCompanyArcs() {
      const arcs = futureData().company_arcs || [];
      if (!arcs.length) return "";
      return `<section class="company-arcs-section"><div class="company-arcs-head"><h3>${escapeHtml(t("futureCompanyArcsTitle"))}</h3><p>${escapeHtml(t("futureCompanyArcsIntro"))}</p></div><div class="company-arcs-list">${arcs.map(companyArcCardMarkup).join("")}</div></section>`;
    }

    function renderFutureTrackRecord() {
      const data = trackRecordData();
      const subjects = data.subjects || [];
      const items = filteredTrackRecordItems();
      const range = trackRecordAxisRange(items);
      const ticks = trackRecordAxisTicks(range);
      return `<article class="future-page track-record-page" data-future-track-record>
        <div class="future-page-head">
          <h2>${escapeHtml(t("futureTrackRecordTitle"))}</h2>
          <p>${escapeHtml(t("futureTrackRecordIntro"))}</p>
        </div>
        ${renderTrackRecordScorecards(subjects)}
        <div class="track-record-toolbar">
          <div class="track-record-legend" aria-hidden="true">
            <span class="track-record-legend-item is-predicted"><i></i>${escapeHtml(t("futureTrackRecordPredictedPoint"))}</span>
            <span class="track-record-legend-item is-actual"><i></i>${escapeHtml(t("futureTrackRecordActualPoint"))}</span>
          </div>
        </div>
        <div class="track-record-list">
          ${items.length ? `${trackRecordAxisRow(range, ticks)}${items.map((item) => trackRecordRow(item, range, ticks)).join("")}` : `<div class="empty" style="display:block">${escapeHtml(t("futureTrackRecordEmpty"))}</div>`}
        </div>
        ${renderCompanyArcs()}
      </article>`;
    }

    function futureSourceMarkup(tech) {
      const predicted = tech.predicted || {};
      const source = predicted.source || "";
      const label = state.language === "en"
        ? (predicted.source_label_en || localizedText(predicted.source_label || ""))
        : (predicted.source_label || t("futureSource"));
      if (!source) return "";
      const subject = tech.track_record_subject || null;
      const scoreLabel = subject ? (state.language === "en" ? (subject.score_label_en || subject.score_label) : subject.score_label) : "";
      return `<div class="future-source-row">
        <a class="future-source-link" href="${escapeHtml(source)}" target="_blank" rel="noopener">${escapeHtml(t("futureSource"))}: ${escapeHtml(label)}</a>
        ${subject ? `<button class="future-source-score" type="button" data-track-record-subject="${escapeHtml(subject.id)}">${escapeHtml(scoreLabel)}</button>` : ""}
      </div>`;
    }

    function futureCompanySideMarkup(company, indirect = false) {
      const metricId = company?.metric_id || "";
      const label = state.language === "en" ? (company?.label_en || company?.label || company?.symbol || "") : (company?.label || company?.symbol || "");
      const change = company?.change_pct_label || "";
      const tag = metricId ? "button" : "span";
      const dataAttr = metricId ? ` type="button" data-future-company="${escapeHtml(metricId)}"` : "";
      return `<${tag} class="future-company-row"${dataAttr}>
        <span class="future-company-name">${escapeHtml(label)}${indirect ? ` · ${escapeHtml(t("futureInvestablePartial"))}` : ""}</span>
        ${change ? `<span class="future-company-change ${directionClass(company.change_pct)}">${escapeHtml(change)}</span>` : ""}
      </${tag}>`;
    }

    function futureTrackScoreMarkup(tech) {
      const subject = tech.track_record_subject || null;
      if (!subject) return "";
      const judged = Math.max(0, Number(subject.judged_count || 0));
      const hits = Math.max(0, Number(subject.on_time_count || 0));
      const scoreLabel = state.language === "en" ? (subject.score_label_en || subject.score_label || "") : (subject.score_label || "");
      const total = Math.max(judged, 1);
      const bars = Array.from({ length: Math.min(Math.max(total, 3), 6) }, (_item, index) => (
        `<span class="${index < hits ? "is-hit" : ""}"></span>`
      )).join("");
      return `<button class="future-track-scorebox" type="button" data-track-record-subject="${escapeHtml(subject.id)}">
        <span class="future-side-label">${escapeHtml(t("futureTrackRecordTitle"))}</span>
        <span class="future-track-score-main">${escapeHtml(`${hits} / ${judged || total}`)}</span>
        <span class="future-track-bars">${bars}</span>
        ${scoreLabel ? `<span class="future-track-score-source">${escapeHtml(scoreLabel)}</span>` : ""}
      </button>`;
    }

    function futureDecadeLabel(tech) {
      if (tech?.status === "watch" || tech?.predicted == null) return t("futureStatusWatch");
      const year = Number(tech?.predicted?.year);
      if (!Number.isFinite(year)) return localizedFutureBand(tech?.band || "");
      const decade = Math.floor(year / 10) * 10;
      return state.language === "en" ? `${decade}s` : `${decade}년대`;
    }

    function futureBottleneckMarkup(tech) {
      const text = localizedFutureField(tech, "bottleneck");
      if (!text) return "";
      const cleaned = text.replace(/^병목\s*[:：]\s*/i, "").replace(/^Bottleneck\s*[:：]\s*/i, "");
      return `<div class="future-bottleneck-card">
        <span>${escapeHtml(t("futureBreakdownBottleneck"))}</span>
        <strong>${escapeHtml(cleaned)}</strong>
        <p>${escapeHtml(localizedFutureField(tech, "now"))}</p>
      </div>`;
    }

    function localizedRoadmapField(item, field) {
      if (!item) return "";
      return state.language === "en" ? (item[`${field}_en`] || item[field] || "") : (item[field] || "");
    }

    function futureRoadmapYear(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return "";
      return Number.isInteger(number) ? String(number) : number.toFixed(1);
    }

    function futureRoadmapShiftLabel(ghost) {
      const years = Math.abs(Number(ghost?.shift_years || 0));
      if (!years) return "";
      const amount = Number.isInteger(years) ? years : years.toFixed(1);
      return ghost.direction === "advanced"
        ? `${amount}${t("futureRoadmapAdvanced")}`
        : `${amount}${t("futureRoadmapDelayed")}`;
    }

    function futureRoadmapDetailsMarkup(tech, phase) {
      const revisions = (phase.revisions || []).map((revision) => `<li>
        <strong>${escapeHtml(revision.date || t("futureRoadmapInitial"))}</strong>
        · ${escapeHtml(futureRoadmapYear(revision.start))}–${escapeHtml(futureRoadmapYear(revision.end))}
        ${localizedRoadmapField(revision, "note") ? `· ${escapeHtml(localizedRoadmapField(revision, "note"))}` : ""}
      </li>`).join("");
      const ladder = phase.ladder_link || null;
      const ladderButton = ladder?.flow_id
        ? `<button class="future-roadmap-link" type="button" data-roadmap-ladder="${escapeHtml(ladder.flow_id)}">${escapeHtml(t("futureRoadmapLadder"))} · ${escapeHtml(localizedRoadmapField(ladder, "label"))}</button>`
        : "";
      const metrics = (phase.metrics || []).map((metric) => `<button class="future-roadmap-link" type="button" data-roadmap-metric="${escapeHtml(metric.id || "")}">${escapeHtml(localizedFutureField(metric, "name"))}</button>`).join("");
      return `<section class="future-roadmap-details" id="roadmap-detail-${idSegment(tech.id)}-${idSegment(phase.id)}" data-roadmap-detail hidden>
        <h4>${escapeHtml(localizedRoadmapField(phase, "name"))} · ${escapeHtml(futureRoadmapYear(phase.start))}–${escapeHtml(futureRoadmapYear(phase.end))}</h4>
        <p>${escapeHtml(localizedRoadmapField(phase, "desc"))}</p>
        <p><strong>${escapeHtml(t("futureRoadmapBasis"))}</strong> · ${escapeHtml(localizedRoadmapField(phase, "basis"))}</p>
        ${revisions ? `<div><strong>${escapeHtml(t("futureRoadmapRevisions"))}</strong><ul class="future-roadmap-revisions">${revisions}</ul></div>` : ""}
        ${(ladderButton || metrics) ? `<div class="future-roadmap-links">${ladderButton}${metrics}</div>` : ""}
      </section>`;
    }

    function futureRoadmapMarkup(tech) {
      const roadmap = tech?.roadmap;
      if (!roadmap || tech?.nature === "governance" || !(roadmap.phases || []).length) return "";
      const mobile = window.matchMedia("(max-width: 720px)").matches;
      const fullStart = Math.floor(Number(roadmap.range?.start || new Date().getFullYear() - 8));
      const fullEnd = Math.ceil(Number(roadmap.range?.end || new Date().getFullYear() + 10));
      const currentYear = new Date().getFullYear() + (new Date().getMonth() / 12);
      const rangeState = futureRoadmapRanges[tech.id] || { past: 0, future: 0 };
      futureRoadmapRanges[tech.id] = rangeState;
      const start = mobile ? Math.max(fullStart, Math.floor(currentYear - 6 - rangeState.past)) : fullStart;
      const end = mobile ? Math.min(fullEnd, Math.ceil(currentYear + 6 + rangeState.future)) : fullEnd;
      const width = mobile ? 350 : 900;
      const labelWidth = mobile ? 8 : 174;
      const plotLeft = mobile ? 8 : 186;
      const plotRight = width - 12;
      const plotWidth = plotRight - plotLeft;
      const visiblePhases = (roadmap.phases || []).filter((phase) => Number(phase.end) >= start && Number(phase.start) <= end);
      const rowHeight = mobile ? 54 : 42;
      const axisY = 24;
      const phaseTop = 42;
      const markerTop = phaseTop + (visiblePhases.length * rowHeight) + 12;
      const height = markerTop + 48;
      const x = (year) => plotLeft + ((Number(year) - start) / Math.max(end - start, 1)) * plotWidth;
      const clampX = (year) => Math.max(plotLeft, Math.min(plotRight, x(year)));
      const span = Math.max(end - start, 1);
      const tickStep = Math.max(1, Math.ceil(span / 6));
      const tickCandidates = [];
      for (let year = Math.ceil(start / tickStep) * tickStep; year <= end; year += tickStep) tickCandidates.push(year);
      tickCandidates.push(start, end);
      const ticks = [...new Set(tickCandidates)].sort((a, b) => a - b).reduce((selected, year) => {
        const previous = selected[selected.length - 1];
        if (previous === undefined || (x(year) - x(previous)) >= (mobile ? 34 : 42)) selected.push(year);
        return selected;
      }, []);
      const techKey = idSegment(tech.id);
      const defs = visiblePhases.filter((phase) => phase.status === "projected").map((phase) => `<linearGradient id="roadmap-gradient-${techKey}-${idSegment(phase.id)}" x1="0" x2="1">
        <stop offset="0%" stop-color="var(--chart-up)" stop-opacity="0.04"></stop>
        <stop offset="18%" stop-color="var(--chart-up)" stop-opacity="0.24"></stop>
        <stop offset="82%" stop-color="var(--chart-up)" stop-opacity="0.24"></stop>
        <stop offset="100%" stop-color="var(--chart-up)" stop-opacity="0.04"></stop>
      </linearGradient>`).join("");
      const grid = ticks.map((year, index) => {
        const anchor = index === 0 ? "start" : index === ticks.length - 1 ? "end" : "middle";
        return `<line class="future-roadmap-grid" x1="${clampX(year)}" x2="${clampX(year)}" y1="${axisY}" y2="${markerTop + 26}"></line>
          <text class="future-roadmap-axis-label" x="${clampX(year)}" y="14" text-anchor="${anchor}">${escapeHtml(futureRoadmapYear(year))}</text>`;
      }).join("");
      const phases = visiblePhases.map((phase, index) => {
        const rowY = phaseTop + (index * rowHeight);
        const barY = rowY + (mobile ? 19 : 3);
        const startX = clampX(phase.start);
        const endX = clampX(phase.end);
        const barWidth = Math.max(4, endX - startX);
        const gradient = `roadmap-gradient-${techKey}-${idSegment(phase.id)}`;
        const ghost = phase.ghost;
        const ghostStart = ghost ? clampX(ghost.start) : 0;
        const ghostEnd = ghost ? clampX(ghost.end) : 0;
        const ghostMarkup = ghost ? `<rect class="future-roadmap-ghost" x="${ghostStart}" y="${barY - 4}" width="${Math.max(4, ghostEnd - ghostStart)}" height="22" rx="4"></rect>` : "";
        const shift = futureRoadmapShiftLabel(ghost);
        const statusLabel = phase.status === "projected" ? t("futureRoadmapProjected") : phase.status === "done" ? "✓" : "";
        return `<g class="future-roadmap-phase-hit" role="button" tabindex="0" aria-label="${escapeHtml(localizedRoadmapField(phase, "name"))}" data-roadmap-phase="roadmap-detail-${techKey}-${idSegment(phase.id)}">
          <text class="future-roadmap-phase-label" x="${mobile ? labelWidth : 4}" y="${rowY + 14}">${escapeHtml(localizedRoadmapField(phase, "name"))}</text>
          ${ghostMarkup}
          <rect class="future-roadmap-bar is-${escapeHtml(phase.status)}" x="${startX}" y="${barY}" width="${barWidth}" height="14" rx="4" ${phase.status === "projected" ? `fill="url(#${gradient})"` : ""}></rect>
          ${statusLabel ? `<text class="future-roadmap-bar-label" x="${Math.min(endX - 4, startX + barWidth / 2)}" y="${barY + 10}" text-anchor="middle">${escapeHtml(statusLabel)}</text>` : ""}
          ${shift ? `<text class="future-roadmap-shift-label" x="${Math.min(plotRight - 4, Math.max(startX, Math.min(endX, ghostEnd)))}" y="${barY + 27}" text-anchor="end">${escapeHtml(shift)}</text>` : ""}
          <rect class="future-roadmap-click-target" x="0" y="${rowY - 2}" width="${width}" height="${rowHeight}"></rect>
        </g>`;
      }).join("");
      const todayX = clampX(currentYear);
      const markers = (roadmap.markers || []).filter((marker) => Number(marker.year) >= start && Number(marker.year) <= end).map((marker, index) => {
        const markerX = clampX(marker.year);
        const markerY = markerTop + ((index % 2) * 15);
        const rawLabel = localizedRoadmapField(marker, "label");
        const markerLabel = mobile
          ? (marker.type === "prediction" ? t("futurePrediction") : rawLabel.slice(0, 14))
          : (rawLabel.length > 34 ? `${rawLabel.slice(0, 32)}…` : rawLabel);
        const alignRight = markerX > plotRight - (mobile ? 94 : 180);
        const labelX = markerX + (alignRight ? -9 : 9);
        return `<g class="future-roadmap-marker" aria-label="${escapeHtml(localizedRoadmapField(marker, "label"))}">
          <path class="future-roadmap-diamond is-${escapeHtml(marker.type || "milestone")}" d="M ${markerX} ${markerY - 6} L ${markerX + 6} ${markerY} L ${markerX} ${markerY + 6} L ${markerX - 6} ${markerY} Z"></path>
          <text class="future-roadmap-marker-label" x="${labelX}" y="${markerY + 3}" text-anchor="${alignRight ? "end" : "start"}">${escapeHtml(futureRoadmapYear(marker.year))} ${escapeHtml(markerLabel)}</text>
        </g>`;
      }).join("");
      const detailPanels = (roadmap.phases || []).map((phase) => futureRoadmapDetailsMarkup(tech, phase)).join("");
      return `<section class="future-roadmap" data-future-roadmap="${escapeHtml(tech.id)}">
        <div class="future-roadmap-head"><h3>${escapeHtml(t("futureRoadmapTitle"))}</h3></div>
        <p class="future-roadmap-notice">${escapeHtml(t("futureRoadmapNotice"))}</p>
        <div class="future-roadmap-controls">
          <button class="future-roadmap-expand" type="button" data-roadmap-expand="past" data-roadmap-tech="${escapeHtml(tech.id)}" ${start <= fullStart ? "disabled" : ""}>‹ ${escapeHtml(t("futureRoadmapEarlier"))}</button>
          <button class="future-roadmap-expand" type="button" data-roadmap-expand="future" data-roadmap-tech="${escapeHtml(tech.id)}" ${end >= fullEnd ? "disabled" : ""}>${escapeHtml(t("futureRoadmapLater"))} ›</button>
        </div>
        <div class="future-roadmap-chart">
          <svg class="future-roadmap-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(localizedFutureField(tech, "name"))} ${escapeHtml(t("futureRoadmapTitle"))}">
            <defs>${defs}</defs>
            ${grid}
            <line class="future-roadmap-axis" x1="${plotLeft}" x2="${plotRight}" y1="${axisY}" y2="${axisY}"></line>
            ${phases}
            <line class="future-roadmap-today" x1="${todayX}" x2="${todayX}" y1="${axisY}" y2="${markerTop + 28}"></line>
            <text class="future-roadmap-today-label" x="${todayX + 4}" y="${axisY + 10}">${escapeHtml(t("futureRoadmapToday"))}</text>
            ${markers}
          </svg>
        </div>
        <div class="future-roadmap-legend">
          <span><i></i>${escapeHtml(t("futureRoadmapDone"))}</span>
          <span><i class="is-active"></i>${escapeHtml(t("futureRoadmapActive"))}</span>
          <span><i class="is-projected"></i>${escapeHtml(t("futureRoadmapProjected"))}</span>
          <span><i class="is-ghost"></i>${escapeHtml(t("futureRoadmapGhost"))}</span>
        </div>
        ${detailPanels}
      </section>`;
    }

    function futureCardMarkup(tech) {
      const predicted = tech.predicted || {};
      const predictedLabel = state.language === "en"
        ? (predicted.label_en || predicted.label || predicted.year || "")
        : (predicted.label || predicted.year || "");
      const metrics = (tech.metrics || []).map(futureMetricMarkup).join("");
      const companies = (tech.companies || []).map((company) => futureCompanySideMarkup(company, tech.investable === "partial")).join("");
      const privatePlayers = (tech.private_players || []).join(" · ");
      const investable = tech.investable || "true";
      const nature = tech.nature || "frontier";
      const predictionValue = tech.status === "watch"
        ? t("futureStatusWatch")
        : String(predicted.year || predictedLabel || "");
      const companyContent = investable === "false"
        ? `<span class="future-company-notice">${escapeHtml(t("futureNoInvestableCompanies"))}</span>`
        : `${companies || `<span class="future-company-change">${escapeHtml(t("futureNoCompanies"))}</span>`}
           ${investable === "partial" ? `<span class="future-company-notice">${escapeHtml(t("futurePartialInvesting"))}</span>` : ""}`;
      const privatePlayersMarkup = privatePlayers
        ? `<p class="future-private-players"><strong>${escapeHtml(t("futurePrivatePlayers"))}</strong> · ${escapeHtml(privatePlayers)}</p>`
        : "";
      const governanceIssues = nature === "governance" && (tech.issues || []).length
        ? `<section><span class="future-side-label">${escapeHtml(t("futureGovernanceIssues"))}</span><ul class="future-governance-issues">${tech.issues.map((item) => `<li>${escapeHtml(localizedFutureField(item, "label"))}</li>`).join("")}</ul></section>`
        : "";
      const glossary = futureGlossaryMarkup(tech.glossary || []);
      const readings = futureReadingsMarkup(tech.readings || []);
      const breakdown = futureBreakdownMarkup(tech);
      const roadmap = futureRoadmapMarkup(tech);
      const active = state.activeFutureId === tech.id;
      const image = tech.image || "";
      return `<article class="future-card ${tech.status === "achieved" ? "is-achieved" : ""} ${active ? "is-active" : ""}" id="${futureCardId(tech.id)}" data-future-card="${escapeHtml(tech.id)}">
        <aside class="future-card-side">
          <span class="future-card-decade">${escapeHtml(futureDecadeLabel(tech))}</span>
          <button class="future-card-title" type="button" data-future-focus="${escapeHtml(tech.id)}">${escapeHtml(localizedFutureField(tech, "name"))}</button>
          <div class="future-side-pills">
            <span class="future-status-pill">${escapeHtml(futureStatusLabel(tech.status))}</span>
            <span class="future-nature-pill is-${escapeHtml(nature)}">${escapeHtml(futureNatureLabel(nature))}</span>
            <span class="future-investable-pill is-${escapeHtml(investable)}">${escapeHtml(futureInvestableLabel(investable))}</span>
            ${predicted.confidence === "low" ? `<span class="future-investable-pill is-partial">${escapeHtml(t("futureForecastLow"))}</span>` : ""}
            ${predicted.manufacturer_forecast ? `<span class="future-investable-pill">${escapeHtml(t("futureManufacturerForecast"))}</span>` : ""}
            ${tech.stale ? `<span class="future-investable-pill is-partial">${escapeHtml(t("futureStale"))}</span>` : ""}
            ${glossary}
          </div>
          <div class="future-year-block">
            <span class="future-side-label">${escapeHtml(t("futurePrediction"))}</span>
            <strong>${escapeHtml(predictionValue)}</strong>
            <small>${escapeHtml(dateText(tech.as_of || ""))}</small>
          </div>
          ${futureTrackScoreMarkup(tech)}
          <div class="future-company-panel">
            <span class="future-side-label">${escapeHtml(t("futureCompanies"))}</span>
            <div class="future-company-list" aria-label="${escapeHtml(t("futureCompanies"))}">
              ${companyContent}
            </div>
            ${privatePlayersMarkup}
          </div>
        </aside>
        <div class="future-card-main">
          ${image ? `<div class="future-card-image"><img src="${escapeHtml(image)}" alt="" loading="lazy"></div>` : ""}
          <div class="future-copy">
            <p><strong>${escapeHtml(localizedFutureField(tech, "why"))}</strong></p>
            <p class="future-why">${escapeHtml(localizedFutureField(tech, "what"))}</p>
          </div>
          ${futureBottleneckMarkup(tech)}
          ${governanceIssues}
          <div class="future-progress">
            <div class="future-metric-list" aria-label="${escapeHtml(t("futureProgress"))}">
              ${metrics || `<span class="future-metric-value">${escapeHtml(t("futureNoMetrics"))}</span>`}
            </div>
          </div>
          ${roadmap}
          ${breakdown}
          ${readings}
          ${futureSourceMarkup(tech)}
        </div>
      </article>`;
    }

    function renderFutureTimeline() {
      const technologies = filteredFutureTechnologies();
      if (!technologies.length) {
        return `<article class="future-page"><div class="empty" style="display:block">${escapeHtml(t("futureEmpty"))}</div></article>`;
      }
      const achieved = technologies.filter((item) => item.status === "achieved");
      const upcoming = technologies.filter((item) => item.status !== "achieved");
      const byBand = upcoming.reduce((map, tech) => {
        const band = tech.band || "미정";
        map.set(band, [...(map.get(band) || []), tech]);
        return map;
      }, new Map());
      const bands = [...byBand.entries()].sort(([a], [b]) => futureBandSortKey(a) - futureBandSortKey(b));
      const minimap = [
        `<button type="button" data-future-jump="future-today">${escapeHtml(t("futureToday"))}</button>`,
        ...bands.map(([band]) => `<button type="button" data-future-jump="${escapeHtml(futureBandId(band))}">${escapeHtml(localizedFutureBand(band))}</button>`)
      ].join("");
      return `<article class="future-page" data-future-page>
        <div class="future-page-head">
          <h2>${escapeHtml(t("futureTimelineTitle"))}</h2>
          <p>${escapeHtml(t("futureTimelineIntro"))}</p>
        </div>
        <div class="future-minimap" aria-label="${escapeHtml(t("futureTimelineTitle"))}">${minimap}</div>
        ${achieved.length ? `<details class="future-achieved">
          <summary>${escapeHtml(t("futureAchieved"))} ${achieved.length}</summary>
          <div class="future-timeline">${achieved.map(futureCardMarkup).join("")}</div>
        </details>` : ""}
        <div class="future-today-marker" id="future-today">${escapeHtml(t("futureToday"))}</div>
        ${bands.map(([band, items]) => `<section class="future-band" id="${futureBandId(band)}">
          <h3 class="future-band-title">${escapeHtml(localizedFutureBand(band))}</h3>
          <div class="future-timeline">${items.map(futureCardMarkup).join("")}</div>
        </section>`).join("")}
        ${futureReadingsMarkup(futureData().common_readings || [], { common: true })}
      </article>`;
    }

    function initFutureTimeline() {
      document.querySelector("[data-future-track-record-link]")?.addEventListener("click", () => setFutureTrackRecordView());
      document.querySelectorAll("[data-future-jump]").forEach((button) => {
        button.addEventListener("click", () => {
          const target = document.getElementById(button.dataset.futureJump || "");
          target?.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      });
      document.querySelectorAll("[data-future-metric]").forEach((button) => {
        button.addEventListener("click", () => openMetricDetail(button.dataset.futureMetric));
      });
      document.querySelectorAll("[data-future-company]").forEach((button) => {
        button.addEventListener("click", () => openMetricDetail(button.dataset.futureCompany));
      });
      document.querySelectorAll("[data-breakdown-metric]").forEach((button) => {
        button.addEventListener("click", () => openMetricDetail(button.dataset.breakdownMetric));
      });
      document.querySelectorAll("[data-breakdown-company]").forEach((button) => {
        button.addEventListener("click", () => openMetricDetail(button.dataset.breakdownCompany));
      });
      document.querySelectorAll("[data-roadmap-phase]").forEach((phase) => {
        const openDetails = () => {
          const roadmap = phase.closest("[data-future-roadmap]");
          const target = document.getElementById(phase.dataset.roadmapPhase || "");
          if (!roadmap || !target) return;
          const opening = target.hidden;
          roadmap.querySelectorAll("[data-roadmap-detail]").forEach((detail) => { detail.hidden = true; });
          roadmap.querySelectorAll("[data-roadmap-phase]").forEach((item) => item.setAttribute("aria-pressed", "false"));
          target.hidden = !opening;
          phase.setAttribute("aria-pressed", String(opening));
        };
        phase.addEventListener("click", openDetails);
        phase.addEventListener("keydown", (event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          openDetails();
        });
      });
      document.querySelectorAll("[data-roadmap-expand]").forEach((button) => {
        button.addEventListener("click", () => {
          const techId = button.dataset.roadmapTech || "";
          const direction = button.dataset.roadmapExpand || "";
          const range = futureRoadmapRanges[techId] || { past: 0, future: 0 };
          if (direction === "past") range.past += 6;
          if (direction === "future") range.future += 6;
          futureRoadmapRanges[techId] = range;
          renderIndustries();
          requestAnimationFrame(() => document.querySelector(`[data-future-roadmap="${techId}"]`)?.scrollIntoView({ block: "center" }));
        });
      });
      document.querySelectorAll("[data-roadmap-ladder]").forEach((button) => {
        button.addEventListener("click", () => {
          const flowId = button.dataset.roadmapLadder || "";
          const target = [...document.querySelectorAll("[data-breakdown-row]")]
            .find((row) => row.dataset.breakdownRow === flowId);
          target?.scrollIntoView({ behavior: "smooth", block: "center" });
        });
      });
      document.querySelectorAll("[data-roadmap-metric]").forEach((button) => {
        button.addEventListener("click", () => openMetricDetail(button.dataset.roadmapMetric));
      });
      document.querySelectorAll("[data-future-component]").forEach((button) => {
        button.addEventListener("click", () => {
          const componentId = button.dataset.futureComponent || "";
          const target = [...document.querySelectorAll("[data-breakdown-row]")]
            .find((row) => row.dataset.breakdownRow === componentId);
          target?.scrollIntoView({ behavior: "smooth", block: "center" });
        });
      });
      document.querySelectorAll("[data-breakdown-row]").forEach((row) => {
        row.addEventListener("click", (event) => {
          if (event.target.closest("button, a")) return;
          const componentId = row.dataset.breakdownRow || "";
          const target = [...document.querySelectorAll("[data-future-component]")]
            .find((node) => node.dataset.futureComponent === componentId && node !== row);
          target?.scrollIntoView({ behavior: "smooth", block: "center" });
        });
      });
      document.querySelectorAll("[data-future-focus]").forEach((button) => {
        button.addEventListener("click", () => {
          state.activeFutureId = button.dataset.futureFocus || "";
          saveNavState();
          writeDashboardHash(currentNavHash(), "push");
          document.querySelectorAll("[data-future-card]").forEach((card) => {
            card.classList.toggle("is-active", card.dataset.futureCard === state.activeFutureId);
          });
        });
      });
      document.querySelectorAll("[data-track-record-subject]").forEach((button) => {
        button.addEventListener("click", () => setFutureTrackRecordView(button.dataset.trackRecordSubject || ""));
      });
    }

    function initFutureTrackRecord() {
      document.querySelector("[data-future-back-timeline]")?.addEventListener("click", () => {
        state.futureView = "timeline";
        state.trackRecordSubject = "";
        saveNavState();
        renderFilters();
        renderIndustries();
        writeDashboardHash("#future", "push");
      });
      document.querySelectorAll("[data-track-subject]").forEach((button) => {
        button.addEventListener("click", () => setTrackRecordSubject(button.dataset.trackSubject || ""));
      });
      document.querySelectorAll("[data-track-sort]").forEach((button) => {
        button.addEventListener("click", () => setTrackRecordSort(button.dataset.trackSort || "predicted"));
      });
      initCompanyArcs();
    }

    function companyArcGroupPoints(group) {
      return [...group.querySelectorAll(".company-arc-scale-point")]
        .map((point) => ({ x: Number(point.dataset.arcX), value: Number(point.dataset.arcValue) }))
        .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.value) && point.value > 0)
        .sort((left, right) => left.x - right.x);
    }

    function visibleCompanyArcValues(chart) {
      const scroller = chart.querySelector(".detail-chart-scroll");
      const plot = chart.querySelector("[data-company-arc-plot]");
      if (!scroller || !plot || scroller.clientWidth <= 0) return [];
      const viewBoxWidth = plot.viewBox?.baseVal?.width || 1;
      const renderedWidth = plot.getBoundingClientRect().width || viewBoxWidth;
      const scaleX = renderedWidth / Math.max(viewBoxWidth, 1);
      const visibleLeft = scroller.scrollLeft / Math.max(scaleX, 0.001);
      const visibleRight = (scroller.scrollLeft + scroller.clientWidth) / Math.max(scaleX, 0.001);
      return [...plot.querySelectorAll(".company-arc-company")].flatMap((group) => {
        const points = companyArcGroupPoints(group);
        const inside = points.filter((point) => point.x >= visibleLeft - 1 && point.x <= visibleRight + 1);
        const before = [...points].reverse().find((point) => point.x < visibleLeft);
        const after = points.find((point) => point.x > visibleRight);
        return [before, ...inside, after].filter(Boolean).map((point) => point.value);
      });
    }

    function renderVisibleCompanyArcScale(chart) {
      const plot = chart.querySelector("[data-company-arc-plot]");
      const axis = chart.querySelector(".detail-chart-axis");
      if (!plot || !axis) return;
      const top = Number(plot.dataset.chartTop);
      const bottom = Number(plot.dataset.chartBottom);
      const scale = companyArcLogScale(visibleCompanyArcValues(chart), top, bottom);
      if (!scale) return;

      plot.querySelectorAll(".company-arc-company").forEach((group) => {
        const points = companyArcGroupPoints(group);
        const path = group.querySelector(".company-arc-line");
        if (path && points.length > 1) {
          path.setAttribute("d", points.map((point, index) => `${index ? "L" : "M"} ${point.x.toFixed(2)} ${scale.yFor(point.value).toFixed(2)}`).join(" "));
        }
        group.querySelectorAll(".company-arc-start, .company-arc-turning").forEach((marker) => {
          marker.setAttribute("cy", scale.yFor(Number(marker.dataset.arcValue)).toFixed(2));
        });
        group.querySelectorAll(".company-arc-line-label").forEach((label) => {
          const offset = Number(label.dataset.arcOffset) || 0;
          label.setAttribute("y", (scale.yFor(Number(label.dataset.arcValue)) + offset).toFixed(2));
        });
        group.querySelectorAll(".company-arc-end").forEach((marker) => {
          marker.setAttribute("y", (scale.yFor(Number(marker.dataset.arcValue)) + 5).toFixed(2));
        });
      });

      axis.querySelectorAll("[data-company-arc-axis-ratio]").forEach((label) => {
        const ratio = Number(label.dataset.companyArcAxisRatio);
        const value = Math.pow(10, scale.maxLog - scale.logSpan * ratio);
        label.textContent = companyArcMarketCapLabel(value);
      });
    }

    function scheduleCompanyArcScale(chart) {
      if (!chart || chart.dataset.arcScaleFrame === "true") return;
      chart.dataset.arcScaleFrame = "true";
      requestAnimationFrame(() => {
        chart.dataset.arcScaleFrame = "false";
        renderVisibleCompanyArcScale(chart);
      });
    }

    function bindCompanyArcScale(card) {
      const chart = card.querySelector(".company-arc-detail-chart");
      const scroller = chart?.querySelector(".detail-chart-scroll");
      if (chart && scroller && scroller.dataset.arcScaleBound !== "true") {
        scroller.dataset.arcScaleBound = "true";
        scroller.addEventListener("scroll", () => scheduleCompanyArcScale(chart), { passive: true });
      }
      if (card.dataset.arcToggleScaleBound !== "true") {
        card.dataset.arcToggleScaleBound = "true";
        card.addEventListener("toggle", () => {
          if (card.open) scheduleCompanyArcScale(card.querySelector(".company-arc-detail-chart"));
        });
      }
      scheduleCompanyArcScale(chart);
    }

    function updateCompanyArc(arcId, options = {}) {
      const arc = (futureData().company_arcs || []).find((item) => item.id === arcId);
      const card = document.querySelector(`[data-company-arc="${CSS.escape(arcId)}"]`);
      const visual = card?.querySelector("[data-company-arc-visual]");
      if (!arc || !visual) return;
      const previousScroller = visual.querySelector(".detail-chart-scroll");
      const previousMaxScroll = Math.max(0, (previousScroller?.scrollWidth || 0) - (previousScroller?.clientWidth || 0));
      const scrollRatio = previousMaxScroll > 0 ? previousScroller.scrollLeft / previousMaxScroll : 0;
      visual.innerHTML = companyArcVisualMarkup(arc);
      bindCompanyArcControls(card, arc);
      if (options.preserveScroll) {
        requestAnimationFrame(() => {
          const scroller = visual.querySelector(".detail-chart-scroll");
          if (!scroller) return;
          scroller.scrollLeft = scrollRatio * Math.max(0, scroller.scrollWidth - scroller.clientWidth);
          scheduleCompanyArcScale(scroller.closest(".company-arc-detail-chart"));
        });
      }
    }

    function bindCompanyArcControls(card, arc) {
      card.querySelectorAll("[data-company-arc-step]").forEach((button) => {
        button.addEventListener("click", () => {
          const current = companyArcSelection(arc).index;
          const max = (arc.chapters || []).length;
          state.companyArcChapters[arc.id] = Math.max(0, Math.min(max, current + Number(button.dataset.companyArcStep || 0)));
          updateCompanyArc(arc.id);
        });
      });
      card.querySelectorAll("[data-company-arc-company]").forEach((button) => {
        const activate = () => {
          state.companyArcCompanies[arc.id] = button.dataset.companyArcCompany || "";
          updateCompanyArc(arc.id, { preserveScroll: true });
        };
        button.addEventListener("click", activate);
        if (button.tagName.toLowerCase() === "g") {
          button.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              activate();
            }
          });
        }
      });
      bindCompanyArcScale(card);
    }

    function initCompanyArcs() {
      const arcs = futureData().company_arcs || [];
      document.querySelectorAll("[data-company-arc]").forEach((card) => {
        const arc = arcs.find((item) => item.id === card.dataset.companyArc);
        if (arc) bindCompanyArcControls(card, arc);
      });
    }
