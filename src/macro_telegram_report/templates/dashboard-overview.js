    function briefingStatusLabel(briefing) {
      if (briefing?.status === "ok") return t("aiBriefing");
      return t("fallbackBriefing");
    }

    function aiSparkleIconMarkup() {
      return `<svg class="ai-sparkle-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <defs>
          <linearGradient id="aiSparkleGradient" x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
            <stop offset="0" stop-color="#3b82f6"></stop>
            <stop offset="0.52" stop-color="#5c6cff"></stop>
            <stop offset="1" stop-color="#6366f1"></stop>
          </linearGradient>
        </defs>
        <path d="M11.017 2.814C11.213 1.777 12.787 1.777 12.983 2.814L14.034 8.372C14.189 9.189 14.811 9.811 15.628 9.966L21.186 11.017C22.223 11.213 22.223 12.787 21.186 12.983L15.628 14.034C14.811 14.189 14.189 14.811 14.034 15.628L12.983 21.186C12.787 22.223 11.213 22.223 11.017 21.186L9.966 15.628C9.811 14.811 9.189 14.189 8.372 14.034L2.814 12.983C1.777 12.787 1.777 11.213 2.814 11.017L8.372 9.966C9.189 9.811 9.811 9.189 9.966 8.372Z"></path>
      </svg>`;
    }

    function localizedBriefingMetricName(item) {
      if (!item) return "";
      return item.id ? localizedMetricName(item.id, item.name || "") : englishMetricName(item.name || "");
    }

    function briefingDriverSentence(item) {
      const name = localizedBriefingMetricName(item);
      const industry = localizedIndustry(item?.industry);
      const change = item?.change_pct_label || item?.yoy_pct_label || "";
      const value = localizedValueLabel(item?.value || "");
      const moveText = change ? ` moved ${change}` : value ? ` is at ${value}` : " stands out";
      return `${industry ? `${industry}: ` : ""}${name}${moveText}. Check whether this reflects real activity, demand, or investment momentum.`;
    }

    function localizedBriefingView(briefing) {
      if (state.language !== "en") return briefing;
      const existingBullets = Array.isArray(briefing?.bullets) ? briefing.bullets : [];
      if (briefing?.headline_en || briefing?.summary_en) {
        return {
          ...briefing,
          headline: briefing.headline_en || localizedText(briefing.headline || ""),
          summary: briefing.summary_en || localizedText(briefing.summary || ""),
          bullets: existingBullets.map((item) => ({
            ...item,
            title: item.title_en || localizedText(item.title || ""),
            body: item.body_en || localizedText(item.body || "")
          }))
        };
      }
      const movers = Array.isArray(briefing?.top_movers) ? briefing.top_movers : [];
      const improving = Array.isArray(briefing?.improving_industries) ? briefing.improving_industries : [];
      const slowing = Array.isArray(briefing?.slowing_industries) ? briefing.slowing_industries : [];
      const top = movers[0];
      if (!top && !improving.length && !slowing.length) {
        return {
          ...briefing,
          headline: localizedText(briefing?.headline || "Market briefing updated."),
          summary: localizedText(briefing?.summary || ""),
          bullets: existingBullets.map((item) => ({
            ...item,
            title: localizedText(item.title || ""),
            body: localizedText(item.body || "")
          }))
        };
      }
      const improvingLead = improving[0];
      const slowingLead = slowing[0];
      const headline = top
        ? `${localizedIndustry(top.industry)}: ${localizedBriefingMetricName(top)}${top.change_pct_label ? ` moved ${top.change_pct_label}` : " stands out"}.`
        : "Market indicators updated.";
      const summaryParts = [];
      if (top) summaryParts.push(briefingDriverSentence(top));
      if (improvingLead) {
        const driver = improvingLead.drivers?.[0];
        summaryParts.push(`${localizedIndustry(improvingLead.industry)} is showing improving momentum${driver ? `, led by ${localizedBriefingMetricName(driver)}` : ""}.`);
      }
      if (slowingLead) {
        const driver = slowingLead.drivers?.[0];
        summaryParts.push(`${localizedIndustry(slowingLead.industry)} needs a closer watch${driver ? `, with ${localizedBriefingMetricName(driver)} still mixed` : ""}.`);
      }
      const bullets = [];
      if (top) {
        bullets.push({
          title: "Top mover",
          body: briefingDriverSentence(top),
          metric_ids: movers.map((item) => item.id).filter(Boolean).slice(0, 3)
        });
      }
      if (improvingLead) {
        const driver = improvingLead.drivers?.[0];
        bullets.push({
          title: "Improving trend",
          body: `${localizedIndustry(improvingLead.industry)} has relatively better recent readings${driver ? `, led by ${localizedBriefingMetricName(driver)} (${driver.change_pct_label || driver.yoy_pct_label || "updated"})` : ""}.`,
          metric_ids: (improvingLead.drivers || []).map((item) => item.id).filter(Boolean)
        });
      }
      if (slowingLead) {
        const driver = slowingLead.drivers?.[0];
        bullets.push({
          title: "Watch list",
          body: `${localizedIndustry(slowingLead.industry)} has weaker or mixed readings, so confirm whether the recovery continues${driver ? ` through ${localizedBriefingMetricName(driver)}` : ""}.`,
          metric_ids: (slowingLead.drivers || []).map((item) => item.id).filter(Boolean)
        });
      }
      return {
        ...briefing,
        headline,
        summary: summaryParts.join(" "),
        bullets
      };
    }

    function briefingInlineLinkCandidates(metric) {
      if (!metric) return [];
      return [...new Set([
        localizedField(metric, "name"),
        localizedIndustry(metric.industry),
        localizedField(metric, "group")
      ].map((value) => String(value || "").trim()).filter((value) => value.length >= 2))]
        .sort((left, right) => right.length - left.length);
    }

    function briefingSummaryMarkup(summary, bullets) {
      const text = String(summary || "");
      if (!text) return "";
      const links = [];
      const occupied = [];
      const overlaps = (start, end) => occupied.some((range) => start < range.end && end > range.start);

      (Array.isArray(bullets) ? bullets : []).forEach((bullet) => {
        const metric = (bullet?.metric_ids || []).map(metricById).find(Boolean);
        if (!metric) return;
        const match = briefingInlineLinkCandidates(metric).map((candidate) => {
          const start = text.toLocaleLowerCase().indexOf(candidate.toLocaleLowerCase());
          return start >= 0 && !overlaps(start, start + candidate.length)
            ? { start, end: start + candidate.length, metric }
            : null;
        }).find(Boolean);
        if (!match) return;
        occupied.push(match);
        links.push(match);
      });

      if (!links.length) return escapeHtml(text);
      links.sort((left, right) => left.start - right.start);
      let cursor = 0;
      return links.map((link) => {
        const before = escapeHtml(text.slice(cursor, link.start));
        const label = escapeHtml(text.slice(link.start, link.end));
        const href = `#d/${hashSegment(metricHashKey(link.metric))}`;
        cursor = link.end;
        return `${before}<a class="briefing-inline-link" href="${escapeHtml(href)}" data-briefing-metric="${escapeHtml(link.metric.id)}">${label}</a>`;
      }).join("") + escapeHtml(text.slice(cursor));
    }

    function briefingSummaryListMarkup(summary, bullets) {
      const sentences = String(summary || "")
        .trim()
        .split(/(?<=[.!?])\s+(?=\S)/)
        .map((sentence) => sentence.trim())
        .filter(Boolean);
      const items = sentences.length ? sentences : [String(summary || "").trim()].filter(Boolean);
      return `<ul class="briefing-summary-list">${items.map((sentence) => (
        `<li>${briefingSummaryMarkup(sentence, bullets)}</li>`
      )).join("")}</ul>`;
    }

    function activeBriefing() {
      return state.selectedBriefingCard || DASHBOARD_DATA.morning_briefing || {};
    }

    function briefingCards() {
      const cards = state.briefingIndex?.cards;
      return Array.isArray(cards) ? cards : [];
    }

    function briefingCardTypeLabel(card) {
      const type = card?.card_type || card?.card_type_label || "";
      const raw = card?.card_type_label || card?.card_type || "";
      if (state.language !== "en") return raw;
      return {
        morning: "Morning",
        intraday: "Intraday",
        close: "Korea close",
        us_close: "US close"
      }[type] || localizedText(raw);
    }

    function briefingChipLabel(card) {
      const source = card.generated_at || card.generated_label || "";
      const time = timeOnlyText(source);
      if (["close", "us_close"].includes(card?.card_type || "")) {
        return `${briefingCardTypeLabel(card)}${time ? ` ${time}` : ""}`.trim();
      }
      return time;
    }

    function briefingDateLabel(briefing) {
      const value = briefing?.generated_at || briefing?.generated_label || briefing?.date || "";
      return value ? dateTimeText(value) : "";
    }

    function briefingRelativeDateLabel(briefing) {
      const value = briefing?.generated_at || briefing?.generated_label || briefing?.date || "";
      const normalizedSource = normalizedDateTimeSource(value);
      const date = new Date(normalizedSource);
      if (!normalizedSource || Number.isNaN(date.getTime()) || zonedDateKey(value) !== dashboardTodayKey()) {
        return briefingDateLabel(briefing);
      }
      const diffSeconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
      if (diffSeconds < 60) return state.language === "en" ? "Just now" : "방금 전";
      const unit = diffSeconds < 3600 ? "minute" : "hour";
      const valueNumber = unit === "minute" ? Math.floor(diffSeconds / 60) : Math.floor(diffSeconds / 3600);
      if (state.language === "en") return `${valueNumber} ${unit}${valueNumber === 1 ? "" : "s"} ago`;
      return `${valueNumber}${unit === "minute" ? "분" : "시간"} 전`;
    }

    function briefingDateInputValue(briefing) {
      const value = briefing?.date || briefing?.generated_at || briefing?.generated_label || "";
      const match = String(value || "").match(/^(\d{4})[.-](\d{1,2})[.-](\d{1,2})/);
      if (!match) return "";
      const year = match[1];
      const month = String(Number(match[2])).padStart(2, "0");
      const day = String(Number(match[3])).padStart(2, "0");
      return `${year}-${month}-${day}`;
    }

    function briefingDisplayDateLabel(briefing) {
      const source = briefing?.generated_at || briefing?.generated_label || briefing?.date || "";
      const key = zonedDateKey(source);
      return key ? plainDateText(key) : t("irregular");
    }

    function activeBriefingSummary(briefing, cards = briefingCards()) {
      const activeId = state.selectedBriefingId || briefing?.id || cards[0]?.id || "";
      return cards.find((card) => card.id === activeId) || briefing || cards[0] || {};
    }

    function briefingCardsForDate(cards, dateValue, activeCard = null) {
      const byId = new Map();
      [...(cards || []), activeCard]
        .filter((card) => card && briefingDateInputValue(card) === dateValue)
        .forEach((card) => byId.set(String(card.id || card.generated_at || ""), card));
      return [...byId.values()]
        .sort((left, right) => String(left?.generated_at || "").localeCompare(String(right?.generated_at || "")));
    }

    function briefingTimeOptionLabel(card) {
      return timeOnlyText(card?.generated_at || card?.generated_label || "") || t("irregular");
    }

    function renderBriefingTimeline(briefing) {
      const cards = briefingCards();
      if (!cards.length) return "";
      const activeCard = activeBriefingSummary(briefing, cards);
      const activeId = activeCard?.id || "";
      const activeIndex = Math.max(0, cards.findIndex((card) => card.id === activeId));
      const olderCard = cards[activeIndex + 1];
      const newerCard = cards[activeIndex - 1];
      const activeDate = briefingDateInputValue(activeCard);
      const activeDateLabel = briefingDisplayDateLabel(activeCard);
      const selectedTime = briefingChipLabel(activeCard) || t("irregular");
      const sameDayCards = briefingCardsForDate(cards, activeDate, activeCard);
      const timeMenuOpen = Boolean(state.briefingTimeMenuOpen);
      const timeMenu = `<div class="briefing-time-menu" id="briefingTimeMenu" role="menu"${timeMenuOpen ? "" : " hidden"}>
        ${sameDayCards.map((card) => `<button class="briefing-time-option" type="button" role="menuitem" data-briefing-time-card-id="${escapeHtml(card.id || "")}" aria-current="${String(card.id || "") === String(activeId)}">
          <span class="briefing-time-option-label">${escapeHtml(briefingTimeOptionLabel(card))}</span>
          <span class="briefing-time-option-type">${escapeHtml(briefingCardTypeLabel(card))}</span>
        </button>`).join("")}
      </div>`;
      return `<div class="briefing-timeline">
        <div class="briefing-date-row">
          <span class="briefing-date-control">
            <input class="briefing-date-picker" type="date" data-briefing-date-picker value="${escapeHtml(activeDate)}" aria-label="${escapeHtml(t("selectBriefingDate"))}">
            <button type="button" class="briefing-date-display" data-briefing-date-open aria-label="${escapeHtml(t("selectBriefingDate"))}">
              <i class="fa-regular fa-calendar" aria-hidden="true"></i>
              <span>${escapeHtml(activeDateLabel)}</span>
            </button>
          </span>
          <button type="button" class="briefing-nav-button" data-briefing-card-id="${escapeHtml(olderCard?.id || "")}" aria-label="${escapeHtml(t("previousBriefing"))}" ${olderCard ? "" : "disabled"}><i class="fa-solid fa-chevron-left" aria-hidden="true"></i></button>
          <span class="briefing-time-control" data-briefing-time-control>
            <button type="button" class="briefing-selected-time" data-briefing-time-toggle aria-label="${escapeHtml(state.language === "ko" ? "브리핑 시간 선택" : "Select briefing time")}" aria-expanded="${timeMenuOpen}" aria-controls="briefingTimeMenu">
              <span>${escapeHtml(selectedTime)}</span>
              <i class="fa-solid fa-chevron-down briefing-time-chevron" aria-hidden="true"></i>
            </button>
            ${timeMenu}
          </span>
          <button type="button" class="briefing-nav-button" data-briefing-card-id="${escapeHtml(newerCard?.id || "")}" aria-label="${escapeHtml(t("nextBriefing"))}" ${newerCard ? "" : "disabled"}><i class="fa-solid fa-chevron-right" aria-hidden="true"></i></button>
        </div>
      </div>`;
    }

    function initBriefingTimeline() {
      document.querySelectorAll("[data-briefing-card-id]").forEach((button) => {
        if (button.dataset.briefingNavBound === "true") return;
        button.dataset.briefingNavBound = "true";
        button.addEventListener("click", () => {
          state.briefingTimeMenuOpen = false;
          selectBriefingCard(button.dataset.briefingCardId);
        });
      });
      document.querySelector("[data-briefing-time-toggle]")?.addEventListener("click", () => {
        state.briefingTimeMenuOpen = !state.briefingTimeMenuOpen;
        renderDailyUpdates();
      });
      document.querySelectorAll("[data-briefing-time-card-id]").forEach((button) => {
        button.addEventListener("click", () => {
          state.briefingTimeMenuOpen = false;
          if (button.dataset.briefingTimeCardId === String(activeBriefing()?.id || "")) {
            renderDailyUpdates();
            return;
          }
          selectBriefingCard(button.dataset.briefingTimeCardId);
        });
      });
      const datePicker = document.querySelector("[data-briefing-date-picker]");
      document.querySelector("[data-briefing-date-open]")?.addEventListener("click", () => {
        if (!datePicker) return;
        if (typeof datePicker.showPicker === "function") {
          datePicker.showPicker();
          return;
        }
        datePicker.focus();
        datePicker.click();
      });
      datePicker?.addEventListener("click", () => {
        if (typeof datePicker.showPicker !== "function") return;
        try {
          datePicker.showPicker();
        } catch (error) {
          datePicker.focus();
        }
      });
      datePicker?.addEventListener("change", (event) => {
        const date = event.target.value;
        const cards = briefingCards().filter((card) => card.date === date);
        if (cards.length) {
          state.briefingTimeMenuOpen = false;
          selectBriefingCard(cards[0].id);
        }
      });
      if (document.documentElement.dataset.briefingTimeDismissBound !== "true") {
        document.documentElement.dataset.briefingTimeDismissBound = "true";
        document.addEventListener("click", (event) => {
          if (!state.briefingTimeMenuOpen || event.target.closest("[data-briefing-time-control]")) return;
          state.briefingTimeMenuOpen = false;
          renderDailyUpdates();
        });
      }
    }

    function loadBriefingIndex() {
      fetch("data/briefings/index.json")
        .then((response) => (response.ok ? response.json() : null))
        .then((data) => {
          if (!data || !Array.isArray(data.cards)) return;
          state.briefingIndex = data;
          renderDailyUpdates();
        })
        .catch(() => {});
    }

    function selectBriefingCard(cardId) {
      const summary = briefingCards().find((card) => card.id === cardId);
      if (!summary) return;
      fetch(`data/briefings/${summary.date}.json`)
        .then((response) => (response.ok ? response.json() : null))
        .then((data) => {
          const card = (data?.cards || []).find((item) => item.id === cardId);
          if (!card) return;
          state.selectedBriefingId = cardId;
          state.selectedBriefingCard = card;
          renderDailyUpdates();
        })
        .catch(() => {});
    }

    function percentileWindowStats(metric) {
      const stats = metric?.percentiles;
      if (!stats) return null;
      const windowStats = stats.y10 || stats.all;
      if (!windowStats || typeof windowStats.pct !== "number") return null;
      return windowStats;
    }

    function percentileDetailStats(metric) {
      const stats = metric?.percentiles;
      if (!stats) return "";
      const windowStats = stats.y10 || stats.all;
      const allStats = stats.all;
      let html = "";
      if (windowStats && typeof windowStats.pct === "number") {
        html += detailStat(t("percentile10y"), `${Math.round(windowStats.pct)}%`);
      }
      if (allStats && typeof allStats.min === "number" && typeof allStats.max === "number") {
        html += detailStat(t("fullRange"), `${formatAxisValue(allStats.min)} ~ ${formatAxisValue(allStats.max)}`);
      }
      if (allStats?.from) {
        html += detailStat(t("dataSince"), dateText(String(allStats.from).slice(0, 7)));
      }
      return html;
    }

    function detailBandStats(metric) {
      const stats = metric?.percentiles?.y10 || metric?.percentiles?.all;
      if (!stats) return null;
      const scale = state.currency === "krw" ? dollarUnitScale(metric || {}) : null;
      const factor = scale ? scale.scale : 1;
      const p20 = Number(stats.p20);
      const p80 = Number(stats.p80);
      const median = Number(stats.median);
      if (![p20, p80, median].every(Number.isFinite)) return null;
      return { p20: p20 * factor, p80: p80 * factor, median: median * factor };
    }

    function thermometerClass(score) {
      if (score >= 80) return "heat-hot";
      if (score >= 60) return "heat-warm";
      if (score >= 45) return "heat-neutral";
      if (score >= 25) return "heat-cool";
      return "heat-cold";
    }

    function gaugeTrendIconMarkup(value) {
      if (typeof value !== "number" || !Number.isFinite(value) || value === 0) {
        return `<svg class="gauge-trend-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
          <path d="M5 12h14" stroke-width="2" stroke-linecap="round"></path>
        </svg>`;
      }
      if (value > 0) {
        return `<svg class="gauge-trend-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
          <path d="m22 7-8.5 8.5-5-5L2 17" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
          <path d="M16 7h6v6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
        </svg>`;
      }
      return `<svg class="gauge-trend-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
        <path d="m22 17-8.5-8.5-5 5L2 7" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="M16 17h6v-6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
      </svg>`;
    }

    function gaugeMetricChangeMarkup(metricId) {
      if (!metricId) return "";
      const metric = metricById(metricId);
      if (!metric) return "";
      const value = metric?.change_pct;
      const label = metric?.change_pct_label || (typeof value === "number" && Number.isFinite(value) ? `${numberText(value, true)}%` : "n/a");
      const direction = directionClass(value);
      return `<span class="gauge-component-change ${direction}">
        ${gaugeTrendIconMarkup(value)}
        <span>${escapeHtml(label)}</span>
      </span>`;
    }

    function gaugeMetricCountryMarkup(metricId) {
      const metric = metricById(metricId);
      return metric ? countryBadgeMarkup(metricCountryCode(metric), "metric-country-badge is-compact") : "";
    }

    function localizedGaugeName(item) {
      if (!item) return "";
      if (state.language !== "en") return item.name || item.metric_name || "";
      if (item.metric_id) return localizedMetricName(item.metric_id, item.name || item.metric_name || "");
      return localizedText(item.name || item.metric_name || "");
    }

    function gaugeComponentMarkup(component) {
      const inner = `<span class="gauge-component-name">${escapeHtml(localizedGaugeName(component))}${gaugeMetricCountryMarkup(component.metric_id)}</span>
        <span class="gauge-component-value">${escapeHtml(localizedValueLabel(component.value_label || ""))}</span>
        ${gaugeMetricChangeMarkup(component.metric_id)}`;
      if (component.metric_id) {
        return `<li><button type="button" data-briefing-metric="${escapeHtml(component.metric_id)}">${inner}</button></li>`;
      }
      return `<li><span class="gauge-component-static">${inner}</span></li>`;
    }

    function signalChipMarkup(signal) {
      const cls = `signal-chip signal-${escapeHtml(signal.status || "ok")}`;
      const inner = `<span class="gauge-component-name">${escapeHtml(localizedGaugeName(signal))}${gaugeMetricCountryMarkup(signal.metric_id)}</span>
        <span class="gauge-component-value signal-value">${escapeHtml(localizedValueLabel(signal.value_label || ""))}</span>
        ${gaugeMetricChangeMarkup(signal.metric_id)}`;
      const title = escapeHtml(localizedText(signal.description || ""));
      if (signal.metric_id) {
        return `<li><button type="button" class="${cls}" title="${title}" data-briefing-metric="${escapeHtml(signal.metric_id)}">${inner}</button></li>`;
      }
      return `<li><span class="${cls} signal-chip-static" title="${title}">${inner}</span></li>`;
    }

    function clampGaugeScore(value) {
      const score = Number(value);
      if (!Number.isFinite(score)) return 0;
      return Math.max(0, Math.min(100, score));
    }

    function gaugeTrackMarkup(score) {
      const clamped = clampGaugeScore(score);
      return `<div class="thermometer-track" aria-hidden="true">
        <div class="thermometer-marker" style="left: ${clamped}%"></div>
      </div>`;
    }

    function gaugeStatusBadgeMarkup(label, score) {
      if (!label) return "";
      return `<span class="gauge-status-badge ${thermometerClass(score)}">${escapeHtml(label)}</span>`;
    }

    function gaugePrimaryScoreMarkup(score) {
      const clamped = clampGaugeScore(score);
      const label = clamped % 1 === 0 ? String(clamped) : clamped.toFixed(1);
      return `<div class="gauge-primary">
        <span class="gauge-primary-number">${escapeHtml(label)}</span>
        <span class="gauge-primary-unit">/100</span>
      </div>`;
    }

    function gaugePrimaryTextMarkup(label) {
      return `<div class="gauge-primary">
        <span class="gauge-primary-text">${escapeHtml(label || "")}</span>
      </div>`;
    }

    function recessionDiagnosisState(recession) {
      const alerts = Math.max(0, Number(recession?.alert_count || 0));
      const warnings = Math.max(0, Number(recession?.warn_count || 0));
      const score = clampGaugeScore(alerts * 46 + warnings * 14);
      if (alerts > 0) {
        return { score, status: t("recessionStatusDanger"), primary: t("recessionRiskHigh") };
      }
      if (warnings > 0) {
        return { score, status: t("recessionStatusWatch"), primary: t("recessionRiskModerate") };
      }
      return { score, status: t("recessionStatusStable"), primary: t("recessionRiskLow") };
    }

    function fearGreedDiagnosisState(fearGreed) {
      const first = (fearGreed?.items || []).find((item) => Number.isFinite(Number(item?.score)));
      const score = clampGaugeScore(first?.score);
      return {
        score,
        status: localizedText(first?.label || "")
      };
    }

    function fearGreedGaugeMarkup(item) {
      const score = clampGaugeScore(item.score);
      const scoreLabel = score.toFixed(score % 1 === 0 ? 0 : 1);
      const heatClass = thermometerClass(score);
      const inner = `<span class="fear-greed-row-head">
          <span class="fear-greed-name-line">
            <span class="fear-greed-name">${escapeHtml(localizedGaugeName(item))}${gaugeMetricCountryMarkup(item.metric_id)}</span>
            <span class="fear-greed-label ${heatClass}">${escapeHtml(localizedText(item.label || ""))}</span>
          </span>
          <span class="fear-greed-score-line">
            <span class="fear-greed-score">${escapeHtml(scoreLabel)}</span>
            ${gaugeMetricChangeMarkup(item.metric_id)}
          </span>
        </span>
        <span class="thermometer-track" aria-hidden="true">
          <span class="thermometer-marker" style="left: ${score}%"></span>
        </span>`;
      if (item.metric_id) {
        return `<li><button type="button" class="fear-greed-gauge-item" data-briefing-metric="${escapeHtml(item.metric_id)}">${inner}</button></li>`;
      }
      return `<li><span class="fear-greed-gauge-item fear-greed-gauge-static">${inner}</span></li>`;
    }

    function gaugeBasisMarkup(items, mapper, className = "") {
      if (!items || !items.length) return "";
      const listClass = className ? `gauge-component-list ${className}` : "gauge-component-list";
      return `<div class="gauge-basis">
        <span class="gauge-basis-title">${escapeHtml(t("thermometerBasis"))}</span>
        <ul class="${listClass}">${items.map(mapper).join("")}</ul>
      </div>`;
    }

    function gaugeHistoryToggleMarkup(key, label = t("gaugeHistory")) {
      const active = Boolean(state.gaugeHistoryOpen[key]);
      return `<button class="gauge-history-toggle${active ? " is-active" : ""}" type="button" data-gauge-history-toggle="${escapeHtml(key)}" aria-expanded="${active ? "true" : "false"}">
        ${escapeHtml(label)}
      </button>`;
    }

    function ensureGaugeHistory() {
      if (state.gaugeHistoryData) return Promise.resolve(state.gaugeHistoryData);
      if (!gaugeHistoryPromise) {
        gaugeHistoryPromise = fetch("data/market_gauges_history.json")
          .then((response) => (response.ok ? response.json() : { snapshots: [] }))
          .catch(() => ({ snapshots: [] }))
          .then((data) => {
            state.gaugeHistoryData = data && typeof data === "object" ? data : { snapshots: [] };
            return state.gaugeHistoryData;
          });
      }
      return gaugeHistoryPromise;
    }

    function gaugeHistorySnapshots() {
      return Array.isArray(state.gaugeHistoryData?.snapshots) ? state.gaugeHistoryData.snapshots : [];
    }

    function gaugeHistoryRange(key) {
      return state.gaugeHistoryRange[key] || "3m";
    }

    function gaugeHistoryPointForSnapshot(snapshot, key) {
      if (key === "thermometer") {
        const score = Number(snapshot?.thermometer?.score);
        if (!Number.isFinite(score)) return null;
        return { date: snapshot.date, value: score, label: localizedText(snapshot.thermometer?.label || "") };
      }
      if (key === "recession") {
        const value = Number(snapshot?.recession?.alert_count || 0);
        if (!Number.isFinite(value)) return null;
        return { date: snapshot.date, value, label: localizedText(snapshot.recession?.summary || "") };
      }
      if (key.startsWith("fear_greed::")) {
        const name = key.slice("fear_greed::".length);
        const item = (snapshot?.fear_greed?.items || []).find((entry) => entry?.name === name);
        const score = Number(item?.score);
        if (!Number.isFinite(score)) return null;
        return { date: snapshot.date, value: score, label: localizedText(item?.label || "") };
      }
      return null;
    }

    function gaugeHistorySeries(key) {
      const points = gaugeHistorySnapshots()
        .map((snapshot) => gaugeHistoryPointForSnapshot(snapshot, key))
        .filter((point) => point && point.date)
        .sort((a, b) => String(a.date).localeCompare(String(b.date)));
      const range = gaugeHistoryRange(key);
      if (range === "all" || points.length < 2) return points;
      const latest = chartTimeValue(points[points.length - 1]);
      const months = range === "1y" ? 12 : 3;
      const cutoff = latest - months * 31 * 24 * 60 * 60 * 1000;
      return points.filter((point) => chartTimeValue(point) >= cutoff);
    }

    function gaugeHistoryChart(points, scoreChart = true) {
      if (!points.length) {
        return `<div class="gauge-history-empty">${escapeHtml(t("gaugeHistoryEmpty"))}</div>`;
      }
      const width = 360;
      const height = 150;
      const left = 34;
      const right = 352;
      const top = 12;
      const bottom = 116;
      const labelBottom = 140;
      const times = points.map(chartTimeValue).filter(Number.isFinite);
      const minTime = Math.min(...times);
      const maxTime = Math.max(...times);
      const values = points.map((point) => point.value).filter(Number.isFinite);
      const min = scoreChart ? 0 : 0;
      const max = scoreChart ? 100 : Math.max(1, ...values);
      const span = max - min || 1;
      const xFor = (point, index) => {
        if (minTime === maxTime) return (left + right) / 2;
        const time = chartTimeValue(point);
        return left + ((time - minTime) / (maxTime - minTime)) * (right - left);
      };
      const yFor = (value) => bottom - ((value - min) / span) * (bottom - top);
      const linePoints = scoreChart
        ? points.map((point, index) => `${xFor(point, index).toFixed(1)},${yFor(point.value).toFixed(1)}`).join(" ")
        : points.map((point, index) => {
            const x = xFor(point, index).toFixed(1);
            const y = yFor(point.value).toFixed(1);
            if (index === 0) return `${x},${y}`;
            const prevX = xFor(points[index - 1], index - 1).toFixed(1);
            return `${prevX},${y} ${x},${y}`;
          }).join(" ");
      const bands = scoreChart ? [
        { y1: yFor(100), y2: yFor(75), cls: "band-high" },
        { y1: yFor(75), y2: yFor(55), cls: "band-mid" },
        { y1: yFor(55), y2: yFor(45), cls: "band-low" },
        { y1: yFor(45), y2: yFor(25), cls: "band-mid" },
        { y1: yFor(25), y2: yFor(0), cls: "band-low" }
      ].map((band) => `<rect class="gauge-history-band ${band.cls}" x="${left}" y="${band.y1.toFixed(1)}" width="${right - left}" height="${(band.y2 - band.y1).toFixed(1)}"></rect>`).join("") : "";
      const tickCandidates = points.length > 2 ? [points[0], points[Math.floor(points.length / 2)], points[points.length - 1]] : points;
      const xLabels = tickCandidates.map((point, index) => {
        const x = xFor(point, index);
        const anchor = x <= left + 4 ? "start" : x >= right - 4 ? "end" : "middle";
        return `<text class="gauge-history-label" x="${x.toFixed(1)}" y="${labelBottom}" text-anchor="${anchor}">${escapeHtml(dateText(point.date))}</text>`;
      }).join("");
      const yLabels = [min, max].map((value) => `
        <text class="gauge-history-label" x="${left - 8}" y="${yFor(value).toFixed(1)}" text-anchor="end" dominant-baseline="middle">${escapeHtml(formatAxisValue(value))}</text>
        <line class="gauge-history-grid" x1="${left}" y1="${yFor(value).toFixed(1)}" x2="${right}" y2="${yFor(value).toFixed(1)}"></line>
      `).join("");
      const dots = points.map((point, index) => {
        const valueLabel = scoreChart ? `${numberText(point.value)} · ${localizedText(point.label || "")}` : `${numberText(point.value)} ${state.language === "en" ? "signals" : "개"}`;
        return `<circle class="gauge-history-point" cx="${xFor(point, index).toFixed(1)}" cy="${yFor(point.value).toFixed(1)}" r="3.5">
          <title>${escapeHtml(`${dateText(point.date)} ${valueLabel}`)}</title>
        </circle>`;
      }).join("");
      return `<div class="gauge-history-chart">
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(t("gaugeHistory"))}">
          ${bands}
          ${yLabels}
          <line class="gauge-history-axis" x1="${left}" y1="${bottom}" x2="${right}" y2="${bottom}"></line>
          ${xLabels}
          <polyline class="gauge-history-line" points="${linePoints}"></polyline>
          ${dots}
        </svg>
      </div>`;
    }

    function gaugeHistoryPanelMarkup(key, title, scoreChart = true) {
      if (!state.gaugeHistoryOpen[key]) return "";
      const loaded = Boolean(state.gaugeHistoryData);
      const points = loaded ? gaugeHistorySeries(key) : [];
      const range = gaugeHistoryRange(key);
      return `<div class="gauge-history-panel">
        <div class="gauge-history-toolbar">
          <span class="gauge-history-title">${escapeHtml(title)}</span>
          <span class="gauge-history-ranges">
            ${["3m", "1y", "all"].map((item) => `<button class="gauge-history-range${range === item ? " is-active" : ""}" type="button" data-gauge-history-range="${escapeHtml(key)}" data-range="${item}">${escapeHtml(t(item === "3m" ? "gaugeHistory3m" : item === "1y" ? "gaugeHistory1y" : "gaugeHistoryAll"))}</button>`).join("")}
          </span>
        </div>
        ${loaded ? gaugeHistoryChart(points, scoreChart) : `<div class="gauge-history-empty">${escapeHtml(t("gaugeHistoryLoading"))}</div>`}
      </div>`;
    }

    function renderMarketGauges() {
      const gauges = DASHBOARD_DATA.market_gauges || {};
      const thermo = gauges.thermometer;
      const recession = gauges.recession;
      const fearGreed = gauges.fear_greed;
      if (!thermo && !recession && !fearGreed) return "";
      const thermoScore = clampGaugeScore(thermo?.score);
      const recessionState = recessionDiagnosisState(recession);
      const fearGreedState = fearGreedDiagnosisState(fearGreed);
      const thermoHtml = thermo ? `<div class="gauge-card thermometer-card">
        <div class="gauge-card-head">
          <h3>${escapeHtml(t("marketThermometer"))}</h3>
          <span class="gauge-card-actions">${gaugeStatusBadgeMarkup(localizedText(thermo.label), thermoScore)}</span>
        </div>
        <div class="gauge-main-area">
          ${gaugePrimaryScoreMarkup(thermoScore)}
          ${gaugeTrackMarkup(thermoScore)}
          <p class="gauge-comment">${escapeHtml(localizedText(thermo.comment || ""))}</p>
        </div>
        ${gaugeBasisMarkup(thermo.components || [], gaugeComponentMarkup)}
        ${gaugeHistoryPanelMarkup("thermometer", t("marketThermometer"), true)}
      </div>` : "";
      const recessionHtml = recession ? `<div class="gauge-card recession-card">
        <div class="gauge-card-head">
          <h3>${escapeHtml(t("recessionSignals"))}</h3>
          <span class="gauge-card-actions">${gaugeStatusBadgeMarkup(recessionState.status, recessionState.score)}</span>
        </div>
        <div class="gauge-main-area recession-main-area">
          ${gaugePrimaryTextMarkup(recessionState.primary)}
          ${gaugeTrackMarkup(recessionState.score)}
          <p class="gauge-comment">${escapeHtml(localizedText(recession.summary || ""))}</p>
        </div>
        ${gaugeBasisMarkup(recession.signals || [], signalChipMarkup, "recession-signal-list")}
        ${gaugeHistoryPanelMarkup("recession", t("recessionSignals"), false)}
      </div>` : "";
      const fearGreedPanels = (fearGreed?.items || [])
        .map((item) => gaugeHistoryPanelMarkup(`fear_greed::${item.name}`, localizedGaugeName(item) || t("fearGreedIndex"), true))
        .join("");
      const fearGreedHtml = fearGreed?.items?.length ? `<div class="gauge-card fear-greed-card">
        <div class="gauge-card-head">
          <h3>${escapeHtml(t("fearGreedIndex"))}</h3>
          <span class="gauge-card-actions">${gaugeStatusBadgeMarkup(fearGreedState.status, fearGreedState.score)}</span>
        </div>
        <div class="gauge-main-area fear-greed-main-area">
          <ul class="fear-greed-gauge-list">${fearGreed.items.map(fearGreedGaugeMarkup).join("")}</ul>
          <p class="gauge-comment">${escapeHtml(localizedText(fearGreed.comment || ""))}</p>
        </div>
        ${fearGreedPanels}
      </div>` : "";
      return `<section class="market-diagnosis">
        <div class="market-diagnosis-head">
          <h2>${escapeHtml(t("marketDiagnosis"))}</h2>
        </div>
        <div class="market-gauges">${thermoHtml}${recessionHtml}${fearGreedHtml}</div>
      </section>`;
    }

    let longHistoryPromise = null;
    function ensureLongHistory() {
      if (!longHistoryPromise) {
        longHistoryPromise = fetch("data/long_history.json")
          .then((response) => (response.ok ? response.json() : {}))
          .catch(() => ({}));
      }
      return longHistoryPromise;
    }

    function longHistoryPoints(entry) {
      return (entry?.points || []).map((point) => ({ date: point[0], value: point[1] }));
    }

    function initDetailRange(metricId, detail) {
      const toggle = detail.querySelector("[data-range-toggle]");
      if (!toggle || toggle.dataset.bound === "true") return;
      if (state.compareBaseMetricId === metricId && state.compareMetricIds.length) {
        toggle.hidden = true;
        return;
      }
      toggle.dataset.bound = "true";
      ensureLongHistory().then((data) => {
        if (state.compareBaseMetricId === metricId && state.compareMetricIds.length) {
          toggle.hidden = true;
          return;
        }
        const entry = data?.[metricId];
        if (!entry || !Array.isArray(entry.points) || entry.points.length < 2) return;
        toggle.hidden = false;
        toggle.querySelectorAll("button").forEach((button) => {
          button.addEventListener("click", (event) => {
            event.stopPropagation();
            const metric = metricById(metricId);
            const host = detail.querySelector("[data-chart-host]");
            if (!metric || !host) return;
            toggle.querySelectorAll("button").forEach((other) => other.classList.toggle("is-active", other === button));
            const useFull = button.dataset.range === "full";
            const points = useFull ? longHistoryPoints(entry) : metric.history;
            host.innerHTML = detailChart(points, metric);
            const periodMeta = detail.querySelector("[data-period-meta] .detail-meta-value");
            if (periodMeta) periodMeta.textContent = displayPointsPeriodLabel(points, metric);
            bindDetailTooltipsWithin(host);
          });
        });
      });
    }

    function compareMetricList(baseMetric) {
      return [baseMetric, ...state.compareMetricIds.map(metricById).filter(Boolean)]
        .filter((metric, index, list) => metric && list.findIndex((item) => item.id === metric.id) === index);
    }

    function compareSourcePoints(metric) {
      const entry = state.longHistoryData?.[metric.id] || state.longHistoryData?.[metric.history_key];
      const points = entry ? longHistoryPoints(entry) : (metric.history || []);
      if (metric.chart_style === "flow_bars") return rollingSumPoints(points, 20);
      return points || [];
    }

    function compareSeries(baseMetric) {
      return compareMetricList(baseMetric).map((metric, index) => ({
        metric,
        index,
        flowConverted: metric.chart_style === "flow_bars",
        unit: detailChartUnit(metric),
        points: compareSourcePoints(metric).filter((point) => typeof point.value === "number" && Number.isFinite(point.value))
      })).filter((series) => series.points.length >= 2);
    }

    function compareTimeWindow(seriesList) {
      const starts = seriesList.map((series) => chartTimeValue(series.points[0])).filter(Number.isFinite);
      const ends = seriesList.map((series) => chartTimeValue(series.points[series.points.length - 1])).filter(Number.isFinite);
      if (!starts.length || !ends.length) return null;
      let start = Math.max(...starts);
      const end = Math.min(...ends);
      if (end <= start) return null;
      const yearMs = 365.25 * 24 * 60 * 60 * 1000;
      const rangeYears = { "1y": 1, "3y": 3, "10y": 10 }[state.compareRange];
      if (rangeYears) start = Math.max(start, end - rangeYears * yearMs);
      return { start, end, days: Math.round((end - start) / (24 * 60 * 60 * 1000)) };
    }

    function filterCompareSeries(seriesList, windowRange) {
      if (!windowRange) return [];
      return seriesList.map((series) => ({
        ...series,
        visiblePoints: series.points.filter((point) => {
          const time = chartTimeValue(point);
          return Number.isFinite(time) && time >= windowRange.start && time <= windowRange.end;
        })
      })).filter((series) => series.visiblePoints.length >= 2);
    }

    function compareAllPositive(seriesList) {
      return seriesList.every((series) => series.visiblePoints.every((point) => point.value > 0));
    }

    function normalizedComparePoints(points) {
      const base = points.find((point) => point.value > 0)?.value;
      if (!base) return [];
      return points.map((point) => ({ ...point, value: (point.value / base) * 100 }));
    }

    function compareRecentItems(baseMetric) {
      try {
        const parsed = JSON.parse(localStorage.getItem(recentCompareStorageKey) || "[]");
        if (!Array.isArray(parsed)) return [];
        return parsed.filter((item) => item?.base === baseMetric.id && Array.isArray(item.ids)).slice(0, 3);
      } catch (_error) {
        return [];
      }
    }

    function rememberCompareSet(baseMetric) {
      if (!baseMetric || !state.compareMetricIds.length) return;
      const current = { base: baseMetric.id, ids: [...state.compareMetricIds], ts: Date.now() };
      let parsed = [];
      try {
        parsed = JSON.parse(localStorage.getItem(recentCompareStorageKey) || "[]");
        if (!Array.isArray(parsed)) parsed = [];
      } catch (_error) {
        parsed = [];
      }
      const key = `${current.base}|${current.ids.join(",")}`;
      const next = [current, ...parsed.filter((item) => `${item?.base}|${(item?.ids || []).join(",")}` !== key)].slice(0, 12);
      localStorage.setItem(recentCompareStorageKey, JSON.stringify(next));
    }

    function compareChart(baseMetric) {
      const rawSeries = compareSeries(baseMetric);
      if (rawSeries.length < 2) return detailChart(baseMetric.history, baseMetric);
      const windowRange = compareTimeWindow(rawSeries);
      const visible = filterCompareSeries(rawSeries, windowRange);
      if (visible.length < 2) return detailChart(baseMetric.history, baseMetric);
      const positive = compareAllPositive(visible);
      const indexed = state.compareMode === "indexed" || visible.length > 2;
      const mode = indexed && positive ? "indexed" : "raw";
      const plotSeries = mode === "indexed"
        ? visible.map((series) => ({ ...series, visiblePoints: normalizedComparePoints(series.visiblePoints), unit: "" }))
        : visible.slice(0, 2);
      const chartHeight = mobileDrawerQuery.matches ? 158 : 190;
      const axisWidth = mobileDrawerQuery.matches ? 40 : 42;
      const showRightAxis = mode === "raw" && !!plotSeries[1];
      const svgWidth = detailChartWidth(plotSeries.flatMap((series) => series.visiblePoints), showRightAxis ? axisWidth : 0);
      const chartStyle = ` style="--detail-chart-width: ${svgWidth}px"`;
      const left = 1;
      const right = svgWidth - 1;
      const top = mobileDrawerQuery.matches ? 12 : 18;
      const axisY = chartHeight - 32;
      const bottom = axisY - 12;
      const labelBottom = chartHeight - 12;
      const allTimes = plotSeries.flatMap((series) => series.visiblePoints.map(chartTimeValue)).filter(Number.isFinite);
      const minTime = Math.min(...allTimes);
      const maxTime = Math.max(...allTimes);
      const xFor = (point) => left + ((chartTimeValue(point) - minTime) / Math.max(1, maxTime - minTime)) * (right - left);
      const yScaleFor = (series) => {
        const values = series.visiblePoints.map((point) => point.value);
        const min = Math.min(...values);
        const max = Math.max(...values);
        const span = max - min || Math.max(1, Math.abs(max));
        return {
          min,
          max,
          yFor: (value) => bottom - ((value - min) / span) * (bottom - top)
        };
      };
      const sharedValues = mode === "indexed" ? plotSeries.flatMap((series) => series.visiblePoints.map((point) => point.value)) : [];
      const sharedMin = sharedValues.length ? Math.min(...sharedValues) : null;
      const sharedMax = sharedValues.length ? Math.max(...sharedValues) : null;
      const sharedSpan = sharedMax !== null ? (sharedMax - sharedMin || 1) : 1;
      const lines = plotSeries.map((series, index) => {
        const scale = mode === "indexed"
          ? { yFor: (value) => bottom - ((value - sharedMin) / sharedSpan) * (bottom - top) }
          : yScaleFor(series);
        const points = series.visiblePoints.map((point) => `${xFor(point).toFixed(1)},${scale.yFor(point.value).toFixed(1)}`).join(" ");
        const hits = series.visiblePoints.map((point) => {
          const x = xFor(point);
          const y = scale.yFor(point.value);
          const label = `${localizedField(series.metric, "name")} ${chartPointDateLabel(point.date, series.metric)} ${detailPointValueLabel(point.value, series.unit)}`;
          return `<circle class="compare-point-hit" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="8" fill="transparent" tabindex="0"><title>${escapeHtml(label)}</title></circle>`;
        }).join("");
        return `<polyline class="compare-line compare-line-${index}" points="${points}"></polyline>${hits}`;
      }).join("");
      const ticks = chartTicks(plotSeries[0].visiblePoints, left, right, true, (point) => xFor(point), plotSeries[0].metric);
      const xGuides = ticks.map((tick) => `<text x="${tick.x.toFixed(1)}" y="${labelBottom}" text-anchor="${tick.x <= left + 2 ? "start" : tick.x >= right - 2 ? "end" : "middle"}">${tick.label}</text>`).join("");
      const axisLabelsForScale = (scale, textX, anchor) => {
        if (!scale) return "";
        const topLabel = `<text x="${textX}" y="${scale.yFor(scale.max).toFixed(1)}" text-anchor="${anchor}" dominant-baseline="middle">${escapeHtml(formatAxisValue(scale.max))}</text>`;
        const bottomLabel = Math.abs(scale.max - scale.min) < Number.EPSILON ? "" : `<text x="${textX}" y="${scale.yFor(scale.min).toFixed(1)}" text-anchor="${anchor}" dominant-baseline="middle">${escapeHtml(formatAxisValue(scale.min))}</text>`;
        return `${topLabel}${bottomLabel}`;
      };
      const leftScale = mode === "indexed" ? null : yScaleFor(plotSeries[0]);
      const rightScale = showRightAxis ? yScaleFor(plotSeries[1]) : null;
      const leftAxisLabels = mode === "indexed"
        ? `<text x="${(axisWidth - 2).toFixed(1)}" y="${top}" text-anchor="end" dominant-baseline="middle">100</text>`
        : axisLabelsForScale(leftScale, (axisWidth - 2).toFixed(1), "end");
      const rightAxis = showRightAxis ? `<svg class="chart detail-chart-axis compare-axis-right" viewBox="0 0 ${axisWidth} ${chartHeight}" preserveAspectRatio="none" aria-hidden="true">
          ${axisLabelsForScale(rightScale, "2", "start")}
        </svg>` : "";
      const shortRangeUnit = windowRange?.days < 180 ? (state.language === "en" ? `${windowRange.days}d` : `${windowRange.days}일`) : "";
      const warning = shortRangeUnit ? `<div class="compare-warning">${escapeHtml(t("compareShortRange"))} (${escapeHtml(shortRangeUnit)})</div>` : "";
      return `<div class="detail-chart compare-chart${showRightAxis ? " has-right-axis" : ""}">
        <svg class="chart detail-chart-axis" viewBox="0 0 ${axisWidth} ${chartHeight}" preserveAspectRatio="none" aria-hidden="true">
          ${leftAxisLabels}
        </svg>
        <div class="detail-chart-scroll">
          <svg class="chart chart-detail"${chartStyle} viewBox="0 0 ${svgWidth} ${chartHeight}" preserveAspectRatio="none" role="img" aria-label="compare trend">
            <line x1="${left}" y1="${axisY}" x2="${right}" y2="${axisY}" class="axis-line"></line>
            ${xGuides}
            ${lines}
          </svg>
        </div>
        ${rightAxis}
        ${warning}
        <div class="detail-chart-tooltip" role="status" aria-live="polite"></div>
      </div>`;
    }

    function compareColor(index) {
      return index === 0 ? "var(--chart-down)" : ["#16a34a", "#8b5cf6", "#f59e0b"][index - 1] || "var(--chart-down)";
    }

    function compareChipListMarkup(baseMetric, className = "compare-legend") {
      const series = compareMetricList(baseMetric);
      if (series.length < 2) return "";
      return `<div class="${escapeHtml(className)}">
        ${series.map((metric, index) => `<span class="compare-chip" style="--compare-color: ${compareColor(index)}">
          <span class="compare-swatch" aria-hidden="true"></span>
          <span>${escapeHtml(localizedField(metric, "name"))}${metric.chart_style === "flow_bars" ? ` · ${escapeHtml(t("compareFlowBadge"))}` : ""}</span>
          ${index > 0 ? `<button class="compare-chip-remove" type="button" data-compare-remove="${escapeHtml(metric.id)}" aria-label="${escapeHtml(t("delete"))}"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button>` : ""}
        </span>`).join("")}
      </div>`;
    }

    function compareLegendMarkup(baseMetric) {
      return compareChipListMarkup(baseMetric, "compare-legend");
    }

    function compareSelectionMarkup(baseMetric) {
      return compareChipListMarkup(baseMetric, "compare-selected-list");
    }

    function compareRangeLabel(range) {
      return range === "all" ? t("compareAllRange") : range.toUpperCase();
    }

    function compareSearchResultsMarkup(metric, items = null) {
      const results = (items || state.compareResults || [])
        .filter((item) => item.id !== metric.id && !state.compareMetricIds.includes(item.id))
        .slice(0, 8);
      return results.map((item) => `<button type="button" class="compare-result-button" data-compare-add="${escapeHtml(item.id)}">${escapeHtml(localizedField(item, "name"))} · ${escapeHtml(localizedIndustry(item.industry))}</button>`).join("");
    }

    function comparePanelMarkup(metric) {
      const active = state.compareBaseMetricId === metric.id && (state.compareOpen || state.compareMetricIds.length);
      if (!active) return "";
      const series = compareSeries(metric);
      const windowRange = compareTimeWindow(series);
      const visible = filterCompareSeries(series, windowRange);
      const positive = visible.length ? compareAllPositive(visible) : true;
      const forceIndexed = visible.length > 2;
      const controlsMarkup = state.compareOpen ? `
        <div class="compare-settings">
          <div class="compare-setting-group">
            <span class="compare-setting-label">${escapeHtml(t("compareDisplayBasis"))}</span>
            <div class="compare-segmented">
              <button class="compare-mode-button${state.compareMode === "raw" && !forceIndexed ? " is-active" : ""}" type="button" data-compare-mode="raw" ${forceIndexed ? "disabled" : ""}>${escapeHtml(t("compareRaw"))}</button>
              <button class="compare-mode-button${state.compareMode === "indexed" || forceIndexed ? " is-active" : ""}" type="button" data-compare-mode="indexed" ${positive ? "" : "disabled"} title="${positive ? "" : escapeHtml(t("compareNeedsPositive"))}">${escapeHtml(t("compareIndexed"))}</button>
            </div>
          </div>
          <div class="compare-setting-group">
            <span class="compare-setting-label">${escapeHtml(t("comparePeriod"))}</span>
            <div class="compare-segmented">
              ${["1y", "3y", "10y", "all"].map((range) => `<button class="compare-range-button${state.compareRange === range ? " is-active" : ""}" type="button" data-compare-range="${range}">${escapeHtml(compareRangeLabel(range))}</button>`).join("")}
            </div>
          </div>
        </div>
        ${state.compareWarning ? `<div class="compare-warning">${escapeHtml(localizedText(state.compareWarning))}</div>` : ""}
        <div class="compare-search-box">
          <div class="compare-search-row">
            <i class="fa-solid fa-magnifying-glass compare-search-icon" aria-hidden="true"></i>
            <input class="compare-search-input" data-compare-search="${escapeHtml(metric.id)}" type="search" autocomplete="off" value="${escapeHtml(state.compareQuery)}" placeholder="${escapeHtml(t("compareSearchPlaceholder"))}">
            <button class="compare-add-button" type="button" data-compare-add-first="${escapeHtml(metric.id)}"><i class="fa-solid fa-plus" aria-hidden="true"></i><span>${escapeHtml(t("compareAddMetric"))}</span></button>
          </div>
          <div class="compare-results" data-compare-results="${escapeHtml(metric.id)}">${compareSearchResultsMarkup(metric)}</div>
        </div>` : "";
      return `<div class="compare-panel" data-compare-panel="${escapeHtml(metric.id)}">
        ${controlsMarkup}
        ${compareSelectionMarkup(metric)}
      </div>`;
    }

    function detailChartForMetric(metric) {
      if (state.compareBaseMetricId === metric.id && state.compareMetricIds.length) {
        return `<div class="compare-chart-stack">${compareChart(metric)}</div>`;
      }
      return detailChart(metric.history, metric);
    }

    function signalMarkersMarkup(metric, displayPoints, xFor, top, bottom) {
      const bounds = chartTimeBounds(displayPoints);
      if (!bounds) return "";
      return signalEvents()
        .filter((event) => event.direction === "triggered" && String(event.metric_id || "") === String(metric?.id || ""))
        .map((event) => {
          const time = chartTimeValue({ date: event.observed_at });
          if (!Number.isFinite(time) || time < bounds.min || time > bounds.max) return "";
          const x = xFor({ date: event.observed_at }, 0);
          const observed = event.ts ? dateTimeText(event.ts) : dateText(event.observed_at || "");
          const title = `${localizedSignalMetricName(event)} ${observed} ${event.threshold_label || ""}`;
          return `<g class="signal-marker">
            <line class="signal-marker-line" x1="${x.toFixed(1)}" y1="${top}" x2="${x.toFixed(1)}" y2="${bottom}"></line>
            <path class="signal-marker-triangle" d="M${(x - 4).toFixed(1)} ${top} L${(x + 4).toFixed(1)} ${top} L${x.toFixed(1)} ${(top + 7).toFixed(1)} Z"><title>${escapeHtml(title)}</title></path>
          </g>`;
        })
        .join("");
    }

    function renderMorningBriefing() {
      const rawBriefing = activeBriefing();
      const briefing = localizedBriefingView(rawBriefing);
      if (!briefing.headline && !briefing.summary) return "";
      const bullets = Array.isArray(briefing.bullets) ? briefing.bullets : [];
      const activeSummary = activeBriefingSummary(rawBriefing);
      const meta = briefingRelativeDateLabel(activeSummary);
      const metaExact = briefingDateLabel(activeSummary);
      return `<section class="morning-briefing-section">
        <div class="briefing-section-title">
          ${aiSparkleIconMarkup()}
          <span class="briefing-section-copy">
            <h2>${escapeHtml(t("morningBriefing"))}</h2>
          </span>
        </div>
        <div class="morning-briefing">
          <div class="briefing-intro">
            <p class="briefing-headline">${escapeHtml(briefing.headline || "")}</p>
            ${meta ? `<span class="briefing-meta"${metaExact ? ` title="${escapeHtml(metaExact)}"` : ""}>${escapeHtml(meta)}</span>` : ""}
          </div>
          ${briefing.summary ? briefingSummaryListMarkup(briefing.summary, bullets) : ""}
          ${renderBriefingTimeline(rawBriefing)}
          <p class="briefing-disclaimer">
            <span class="briefing-disclaimer-icon" aria-hidden="true"><i class="fa-solid fa-info"></i></span>
            <span>${escapeHtml(t("briefingDisclaimer"))}</span>
          </p>
        </div>
      </section>`;
    }

    function favoriteMetrics() {
      return countryFilteredMetrics().filter((metric) => state.favoriteMetricIds.has(metric.id));
    }

    function favoritePageSize() {
      return mobileDrawerQuery.matches ? 6 : 15;
    }

    function favoritePageCount(metrics = favoriteMetrics()) {
      return Math.max(1, Math.ceil(metrics.length / favoritePageSize()));
    }

    function clampFavoritePage(metrics = favoriteMetrics()) {
      const maxPage = favoritePageCount(metrics) - 1;
      state.favoritePage = Math.min(Math.max(0, Number(state.favoritePage) || 0), maxPage);
      return state.favoritePage;
    }

    function favoriteCardStarMarkup(metric) {
      const active = isFavoriteMetric(metric.id);
      const label = active ? t("removeFavorite") : t("addFavorite");
      return `<button class="favorite-card-star${active ? " is-active" : ""}" type="button" data-favorite-toggle="${escapeHtml(metric.id)}" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}" aria-pressed="${active ? "true" : "false"}">
          <i class="fa-${active ? "solid" : "regular"} fa-star" aria-hidden="true"></i>
        </button>`;
    }

    function favoriteMetricCard(metric) {
      const selected = state.searchSelectedIndex >= 0 && state.searchResults[state.searchSelectedIndex]?.id === metric.id;
      const meta = state.searchResultMeta.get(metric.id);
      const notePreview = metricNotePreview(metric);
      return `<div class="favorite-card${selected ? " is-search-selected" : ""}" role="button" tabindex="0" data-favorite-card="${escapeHtml(metric.id)}">
        ${favoriteCardStarMarkup(metric)}
        ${noteButtonMarkup(metric, "favorite-card-note")}
        <span class="favorite-card-top">
          <span class="favorite-card-meta">${countryBadgeMarkup(metricCountryCode(metric))}${escapeHtml(localizedIndustry(metric.industry))} · ${escapeHtml(localizedGroup(metric.group, [metric]))}</span>
          <span class="favorite-card-title">${highlightSearchText(localizedField(metric, "name"))}</span>
          <span class="favorite-card-value">${escapeHtml(displayMetricValue(metric))}</span>
          ${notePreview ? `<span class="favorite-card-note-preview">${escapeHtml(notePreview)}</span>` : ""}
          ${meta?.fuzzy ? `<span class="search-fuzzy-badge">${escapeHtml(t("similarResults"))}</span>` : ""}
        </span>
        <span class="favorite-card-chart">${chart(metric.history, "chart-mini", metric)}</span>
      </div>`;
    }

    function renderFavoriteMetrics(metrics = favoriteMetrics(), options = {}) {
      if (!metrics.length) return "";
      const page = clampFavoritePage(metrics);
      const pageCount = favoritePageCount(metrics);
      const pageSize = favoritePageSize();
      const pagedMetrics = metrics.slice(page * pageSize, (page + 1) * pageSize);
      const pager = pageCount > 1 ? `<div class="favorite-metrics-pager" aria-label="${escapeHtml(t("favoriteMetrics"))}">
          <button class="favorite-page-button" type="button" data-favorite-page="${page - 1}" aria-label="${escapeHtml(t("favoritePreviousPage"))}" ${page <= 0 ? "disabled" : ""}><i class="fa-solid fa-chevron-left" aria-hidden="true"></i></button>
          <span class="favorite-page-indicator">${page + 1} / ${pageCount}</span>
          <button class="favorite-page-button" type="button" data-favorite-page="${page + 1}" aria-label="${escapeHtml(t("favoriteNextPage"))}" ${page >= pageCount - 1 ? "disabled" : ""}><i class="fa-solid fa-chevron-right" aria-hidden="true"></i></button>
        </div>` : "";
      return `<section class="favorite-metrics is-paged${options.context ? " is-context" : ""}">
        <div class="favorite-metrics-head">
          <h2>${escapeHtml(t("favoriteMetrics"))}</h2>
          <span class="favorite-metrics-count">${metrics.length}${state.language === "ko" ? "" : " "}${escapeHtml(t("favoriteCount"))}</span>
          ${pager}
        </div>
        <div class="favorite-metrics-grid">${pagedMetrics.map(favoriteMetricCard).join("")}</div>
      </section>`;
    }

    function isMetricUpdateCalendarEvent(event) {
      const name = String(event?.name || "");
      const note = String(event?.note || "");
      return event?.category === "site_update" || name.endsWith("갱신 예정") || note === "대시보드 지표 발표 예정일";
    }

    function calendarEvents() {
      const events = Array.isArray(DASHBOARD_DATA.calendar?.events) ? DASHBOARD_DATA.calendar.events : [];
      return events
        .filter((event) => !isMetricUpdateCalendarEvent(event))
        .filter((event) => matchesCountryFilter(eventCountryCode(event)))
        .map((event) => ({ ...event, category: normalizedCalendarCategory(event.category) }));
    }

    const calendarCategoryColors = {
      policy: "#dc5b5b",
      macro: "#8b6ac9",
      market: "#d08a4e",
      holiday: "#8792a2",
      corporate: "#0f9f8f",
      industry: "#2f9f8f",
      event: "#8a8a8a"
    };

    const calendarCategoryAliases = {
      fed: "policy",
      bok: "policy",
      us_data: "macro",
      kr_data: "macro",
      expiry: "market",
      earnings: "corporate",
      future: "industry"
    };

    function normalizedCalendarCategory(category) {
      const value = String(category || "event");
      return calendarCategoryAliases[value] || value;
    }

    const calendarFilters = [
      { key: "all", label: "전체", categories: null },
      { key: "policy", label: "통화정책", categories: ["policy"] },
      { key: "macro", label: "거시경제", categories: ["macro"] },
      { key: "market", label: "시장일정", categories: ["market"] },
      { key: "corporate", label: "기업", categories: ["corporate"] },
      { key: "industry", label: "산업", categories: ["industry"] },
      { key: "holiday", label: "휴장", categories: ["holiday"] }
    ];

    function calendarFilterLabel(filter) {
      if (state.language !== "en") return filter.label;
      return {
        all: "All",
        policy: "Policy",
        macro: "Macro",
        market: "Market",
        corporate: "Corporate",
        industry: "Industry",
        holiday: "Holiday"
      }[filter.key] || filter.label;
    }

    function filteredCalendarEvents(events = calendarEvents()) {
      const filter = calendarFilters.find((item) => item.key === state.calendarCategoryFilter) || calendarFilters[0];
      if (!filter.categories) return events;
      return events.filter((event) => filter.categories.includes(String(event.category || "event")));
    }

    function calendarFilterMarkup() {
      return `<div class="calendar-filter-bar" aria-label="${escapeHtml(t("marketCalendar"))}">
        ${calendarFilters.map((filter) => `<button class="calendar-filter-button${state.calendarCategoryFilter === filter.key ? ` is-from-${state.calendarFilterDirection}` : ""}" type="button" data-calendar-filter="${filter.key}" aria-pressed="${state.calendarCategoryFilter === filter.key}">${escapeHtml(calendarFilterLabel(filter))}</button>`).join("")}
      </div>`;
    }

    function calendarCategoryLabel(category) {
      return {
        policy: t("calendarPolicy"),
        macro: t("calendarMacro"),
        market: t("calendarMarket"),
        holiday: t("calendarHoliday"),
        corporate: t("calendarCorporate"),
        industry: t("calendarIndustry")
      }[category] || t("calendarEvent");
    }

    function localizedCalendarEventName(event) {
      if (state.language !== "en") return event?.name || "";
      if (event?.name_en) return event.name_en;
      return localizedText(event?.name || "");
    }

    function localizedCalendarEventNote(event) {
      if (state.language !== "en") return event?.note || "";
      if (event?.note_en) return event.note_en;
      return localizedText(event?.note || "");
    }

    function calendarDateLabel(value) {
      const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (!match) return value || "";
      const [, year, month, day] = match;
      const weekday = new Intl.DateTimeFormat(state.language === "en" ? "en-US" : "ko-KR", {
        weekday: "short",
        timeZone: "UTC"
      }).format(new Date(Date.UTC(Number(year), Number(month) - 1, Number(day))));
      if (state.language === "en") return `${month}/${day} ${weekday}`;
      return `${Number(month)}월 ${Number(day)}일 ${weekday}`;
    }

    function calendarDayNumber(dateValue) {
      const match = String(dateValue || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (!match) return null;
      return Math.floor(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) / 86400000);
    }

    function calendarEventDday(event) {
      const eventDay = calendarDayNumber(event?.date);
      const todayDay = calendarDayNumber(dashboardTodayKey());
      if (!Number.isFinite(eventDay) || !Number.isFinite(todayDay)) {
        const fallback = Number(event?.d_day);
        return Number.isFinite(fallback) ? fallback : null;
      }
      return eventDay - todayDay;
    }

    function calendarDdayLabel(event) {
      const dDay = calendarEventDday(event);
      if (!Number.isFinite(dDay)) return event?.d_day_label || "";
      if (dDay === 0) return "D-day";
      return `D${dDay > 0 ? "+" : ""}${dDay}`;
    }

    function calendarSnapshotDateLabel(event) {
      const dDay = calendarEventDday(event);
      if (Number.isFinite(dDay)) {
        if (dDay === 0) return state.language === "en" ? "Today" : "오늘";
        if (dDay === 1) return state.language === "en" ? "Tomorrow" : "내일";
      }
      const match = String(event?.date || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (!match) return event?.date || "";
      return state.language === "en" ? `${match[2]}/${match[3]}` : `${Number(match[3])}일`;
    }

    function calendarMonthKey(dateValue) {
      const match = String(dateValue || "").match(/^(\d{4})-(\d{2})/);
      return match ? `${match[1]}-${match[2]}` : "";
    }

    function calendarDefaultDate() {
      const upcoming = calendarEvents().filter((event) => {
        const dDay = calendarEventDday(event);
        return Number.isFinite(dDay) && dDay >= 0;
      });
      return upcoming[0]?.date || calendarEvents()[0]?.date || String(DASHBOARD_DATA.generated_at || "").slice(0, 10);
    }

    function calendarViewMonthKey() {
      const fallback = calendarMonthKey(state.calendarSelectedDate) || calendarMonthKey(calendarDefaultDate());
      return state.calendarViewMonth || fallback;
    }

    function calendarMonthTitle(monthKey) {
      const [year, month] = String(monthKey || "").split("-").map(Number);
      if (!year || !month) return "";
      if (state.language === "en") {
        const monthName = new Intl.DateTimeFormat("en-US", { month: "long", timeZone: "UTC" }).format(new Date(Date.UTC(year, month - 1, 1)));
        return `${monthName} ${year}`;
      }
      return `${year}년 ${month}월`;
    }

    function addCalendarMonths(monthKey, offset) {
      const [year, month] = String(monthKey || "").split("-").map(Number);
      if (!year || !month) return monthKey;
      const date = new Date(Date.UTC(year, month - 1 + offset, 1));
      return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
    }

    function calendarDayGridDates(monthKey) {
      const [year, month] = String(monthKey || "").split("-").map(Number);
      if (!year || !month) return [];
      const first = new Date(Date.UTC(year, month - 1, 1));
      const start = new Date(first);
      start.setUTCDate(first.getUTCDate() - first.getUTCDay());
      return Array.from({ length: 42 }, (_, index) => {
        const date = new Date(start);
        date.setUTCDate(start.getUTCDate() + index);
        return {
          value: `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-${String(date.getUTCDate()).padStart(2, "0")}`,
          day: date.getUTCDate(),
          outside: date.getUTCMonth() !== month - 1
        };
      });
    }

    function calendarEventDots(events) {
      const categories = [...new Set((events || []).map((event) => String(event.category || "event")))].slice(0, 4);
      return `<span class="calendar-day-dots">${categories.map((category) => `<span class="calendar-dot" style="--calendar-dot-color: ${calendarCategoryColors[category] || calendarCategoryColors.event}"></span>`).join("")}</span>`;
    }

    function renderCalendarMonth(eventsByDate, events = calendarEvents()) {
      const monthKey = calendarViewMonthKey();
      const today = dashboardTodayKey();
      const weekdays = state.language === "en" ? ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] : ["일", "월", "화", "수", "목", "금", "토"];
      return `<section class="calendar-month-panel">
        <div class="calendar-month-head">
          <h3 class="calendar-month-title">${escapeHtml(calendarMonthTitle(monthKey))}</h3>
          <span class="calendar-month-actions">
            <button type="button" class="calendar-month-nav" data-calendar-month="${escapeHtml(addCalendarMonths(monthKey, -1))}" aria-label="${escapeHtml(t("previousMonth"))}"><i class="fa-solid fa-chevron-left" aria-hidden="true"></i></button>
            <button type="button" class="calendar-month-nav" data-calendar-month="${escapeHtml(addCalendarMonths(monthKey, 1))}" aria-label="${escapeHtml(t("nextMonth"))}"><i class="fa-solid fa-chevron-right" aria-hidden="true"></i></button>
          </span>
        </div>
        <div class="calendar-weekdays">${weekdays.map((day) => `<span class="calendar-weekday">${escapeHtml(day)}</span>`).join("")}</div>
        <div class="calendar-days">
          ${calendarDayGridDates(monthKey).map((day) => {
            const events = eventsByDate.get(day.value) || [];
            const selected = state.calendarSelectedDate === day.value;
            const classes = ["calendar-day", day.outside ? "is-outside" : "", day.value === today ? "is-today" : "", selected ? "is-selected" : ""].filter(Boolean).join(" ");
            return `<button type="button" class="${classes}" data-calendar-date="${escapeHtml(day.value)}" aria-pressed="${selected}">
              <span class="calendar-day-number">${day.day}</span>
              ${calendarEventDots(events)}
            </button>`;
          }).join("")}
        </div>
        ${renderCalendarLegend(events)}
      </section>`;
    }

    function renderCalendarLegend(events = calendarEvents()) {
      const categories = [...new Set(events.map((event) => String(event.category || "event")))];
      return `<div class="calendar-legend">
        ${categories.map((category) => `<span class="calendar-legend-item">
          <span class="calendar-dot" style="--calendar-dot-color: ${calendarCategoryColors[category] || calendarCategoryColors.event}"></span>
          <span>${escapeHtml(calendarCategoryLabel(category))}</span>
        </span>`).join("")}
      </div>`;
    }

    function calendarEventRow(event) {
      const category = String(event.category || "event");
      const todayClass = calendarEventDday(event) === 0 ? " is-today" : "";
      const note = localizedCalendarEventNote(event);
      const inner = `
        <span class="calendar-date">${escapeHtml(calendarDateLabel(event.date))}</span>
        <span class="calendar-chip calendar-${escapeHtml(category)}">${escapeHtml(calendarCategoryLabel(category))}</span>
        <span class="calendar-main">
          <span class="calendar-name-line"><span class="calendar-name">${escapeHtml(localizedCalendarEventName(event))}</span>${countryBadgeMarkup(eventCountryCode(event), "calendar-country-badge")}</span>
          ${note ? `<span class="calendar-note">${escapeHtml(note)}</span>` : ""}
        </span>
        <span class="calendar-dday">${escapeHtml(calendarDdayLabel(event))}</span>
      `;
      if (event.metric_id) {
        return `<button class="calendar-row${todayClass}" type="button" data-briefing-metric="${escapeHtml(event.metric_id)}">${inner}</button>`;
      }
      return `<div class="calendar-row${todayClass}">${inner}</div>`;
    }

    function calendarSection(titleKey, events, collapsible = false) {
      const rows = events.map(calendarEventRow).join("") || `<div class="calendar-row"><span class="calendar-main"><span class="calendar-empty-text">${escapeHtml(t("calendarNoEvents"))}</span></span></div>`;
      const head = `<div class="calendar-section-head">
        <h3>${escapeHtml(t(titleKey))}</h3>
        <span class="calendar-section-count">${events.length}</span>
      </div>`;
      if (collapsible) {
        return `<details class="calendar-section">
          <summary class="calendar-section-summary">${head}</summary>
          <div class="calendar-list">${rows}</div>
        </details>`;
      }
      return `<section class="calendar-section">
        ${head}
        <div class="calendar-list">${rows}</div>
      </section>`;
    }

    function calendarAgendaRow(event) {
      const category = String(event.category || "event");
      const todayClass = calendarEventDday(event) === 0 ? " is-today" : "";
      const clickable = Boolean(event.metric_id);
      const note = localizedCalendarEventNote(event);
      const rowAttrs = clickable
        ? ` data-briefing-metric="${escapeHtml(event.metric_id)}" role="button" tabindex="0"`
        : "";
      return `<tr class="calendar-agenda-row${todayClass}${clickable ? " is-clickable" : ""}"${rowAttrs}>
        <td class="calendar-date-cell"><span class="calendar-date">${escapeHtml(calendarDateLabel(event.date))}</span></td>
        <td class="calendar-type-cell"><span class="calendar-chip calendar-${escapeHtml(category)}">${escapeHtml(calendarCategoryLabel(category))}</span></td>
        <td class="calendar-country-cell">${countryBadgeMarkup(eventCountryCode(event), "calendar-country-badge")}</td>
        <td class="calendar-agenda-title-cell">
          <span class="calendar-agenda-event">
            <span class="calendar-name">${escapeHtml(localizedCalendarEventName(event))}</span>
            ${note ? `<span class="calendar-note">${escapeHtml(note)}</span>` : ""}
          </span>
        </td>
        <td class="calendar-dday-cell"><span class="calendar-dday">${escapeHtml(calendarDdayLabel(event))}</span></td>
      </tr>`;
    }

    function calendarAgendaTable(events) {
      const rows = events.length
        ? events.map(calendarAgendaRow).join("")
        : `<tr class="calendar-agenda-row"><td colspan="5"><span class="calendar-empty-text">${escapeHtml(t("calendarNoEvents"))}</span></td></tr>`;
      return `<div class="metric-table-wrap calendar-agenda-table-wrap">
        <table class="metric-table calendar-agenda-table">
          <colgroup>
            <col class="calendar-date-cell">
            <col class="calendar-type-cell">
            <col class="calendar-country-cell">
            <col>
            <col class="calendar-dday-cell">
          </colgroup>
          <thead>
            <tr>
              <th scope="col" class="calendar-date-cell">${escapeHtml(t("calendarDate"))}</th>
              <th scope="col" class="calendar-type-cell">${escapeHtml(t("calendarType"))}</th>
              <th scope="col" class="calendar-country-cell">${escapeHtml(t("calendarCountry"))}</th>
              <th scope="col">${escapeHtml(t("calendarSchedule"))}</th>
              <th scope="col" class="calendar-dday-cell">${escapeHtml(t("calendarDday"))}</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
    }

    function renderCalendarAgenda(events) {
      const selected = state.calendarSelectedDate;
      const title = selected ? calendarDateLabel(selected) : t("calendarNext30");
      return `<section class="calendar-agenda-panel">
        <div class="calendar-agenda-head">
          <h3 class="calendar-agenda-title">${escapeHtml(title)}</h3>
          <span class="calendar-section-count">${events.length}</span>
          ${selected ? `<button type="button" class="calendar-selection-clear" data-calendar-clear>${escapeHtml(t("calendarNext30"))}</button>` : ""}
        </div>
        ${calendarAgendaTable(events)}
      </section>`;
    }

    function renderEventCalendar() {
      const events = filteredCalendarEvents();
      const filteredEventsByDate = events.reduce((map, event) => {
        const date = String(event.date || "");
        if (!date) return map;
        map.set(date, [...(map.get(date) || []), event]);
        return map;
      }, new Map());
      const selectedEvents = state.calendarSelectedDate ? (filteredEventsByDate.get(state.calendarSelectedDate) || []) : null;
      const agendaEvents = selectedEvents || events.filter((event) => {
        const dDay = calendarEventDday(event);
        return Number.isFinite(dDay) && dDay >= 0 && dDay <= 30;
      }).sort((a, b) => String(a.date).localeCompare(String(b.date)));
      return `<article class="industry calendar-page" id="${marketSectionId("캘린더")}" data-market-section data-market-category="캘린더">
        <div class="industry-head">
          <div>
            <h2>${escapeHtml(t("marketCalendar"))}</h2>
            ${calendarFilterMarkup()}
          </div>
        </div>
        <div class="calendar-layout">
          ${renderCalendarMonth(filteredEventsByDate, events)}
          ${renderCalendarAgenda(agendaEvents)}
        </div>
      </article>`;
    }

    function renderCalendarBanner() {
      const upcoming = calendarEvents()
        .filter((event) => {
          const dDay = calendarEventDday(event);
          return Number.isFinite(dDay) && dDay >= 0;
        })
        .sort((a, b) => String(a.date || "").localeCompare(String(b.date || "")));
      if (!upcoming.length) return "";
      const items = upcoming.slice(0, mobileDrawerQuery.matches ? 3 : 16).map((event) => {
        const category = String(event.category || "event");
        const dotColor = calendarCategoryColors[category] || calendarCategoryColors.event;
        const inner = `<span class="event-snapshot-dot" style="--event-dot-color: ${escapeHtml(dotColor)}" aria-hidden="true"></span>
          <span class="event-snapshot-date">${escapeHtml(calendarSnapshotDateLabel(event))}</span>
          <span class="event-snapshot-name">${escapeHtml(localizedCalendarEventName(event))} ${countryBadgeMarkup(eventCountryCode(event), "calendar-country-badge")}</span>`;
        if (event.metric_id) {
          return `<button class="event-snapshot-row" type="button" data-briefing-metric="${escapeHtml(event.metric_id)}">${inner}</button>`;
        }
        return `<div class="event-snapshot-row">${inner}</div>`;
      }).join("");
      return `<section class="event-snapshot-card">
        <button class="event-snapshot-head" type="button" data-calendar-snapshot-open aria-label="${escapeHtml(t("marketCalendar"))}">
          <span class="event-snapshot-title">${escapeHtml(t("calendarSnapshotTitle"))}</span>
          <span class="event-snapshot-arrow" aria-hidden="true">
            <i class="fa-solid fa-chevron-right" aria-hidden="true"></i>
          </span>
        </button>
        <p class="event-snapshot-copy">${escapeHtml(t("calendarSnapshotCopy"))}</p>
        <div class="event-snapshot-list">${items}</div>
      </section>`;
    }

    function recentAlertTimeText(event) {
      const source = event.ts || event.observed_at || "";
      const time = timeOnlyText(source);
      const dateSource = source || event.observed_at || "";
      const dateKey = zonedDateKey(dateSource);
      const dateDay = calendarDayNumber(dateKey);
      const todayDay = calendarDayNumber(dashboardTodayKey());
      let dateLabel = "";
      if (Number.isFinite(dateDay) && Number.isFinite(todayDay)) {
        const diff = dateDay - todayDay;
        if (diff === 0) dateLabel = state.language === "en" ? "Today" : "오늘";
        else if (diff === -1) dateLabel = state.language === "en" ? "Yesterday" : "어제";
      }
      if (!dateLabel) {
        const parts = rawDateParts(dateKey);
        if (parts?.month && parts?.day) {
          dateLabel = state.language === "en"
            ? `${Number(parts.month)}/${Number(parts.day)}`
            : `${Number(parts.month)}/${Number(parts.day)}`;
        }
      }
      if (dateLabel && time) return `${dateLabel} ${time}`;
      if (dateLabel) return dateLabel;
      return dateText(dateSource);
    }

    function recentAlertTitle(event) {
      const metric = localizedSignalMetricName(event);
      const message = localizedSignalMessage(event) || signalEventValueText(event) || "";
      if (metric && message && !String(message).includes(metric)) {
        return `${metric} · ${message}`;
      }
      return message || metric || t("metric");
    }

    function recentAlertDotClass(event) {
      if (event.backfilled) return "is-muted";
      if (event.direction === "triggered") return "is-triggered";
      if (event.direction === "cleared") return "is-cleared";
      return "is-muted";
    }

    function renderRecentAlertsCard() {
      const events = signalEvents().slice(0, mobileDrawerQuery.matches ? 3 : 16);
      const rows = events.map((event) => {
        const inner = `<span class="recent-alert-dot ${recentAlertDotClass(event)}" aria-hidden="true"></span>
          <time class="recent-alert-time">${escapeHtml(recentAlertTimeText(event))}</time>
          <span class="recent-alert-title">${escapeHtml(recentAlertTitle(event))}</span>`;
        return `<button class="recent-alert-row" type="button" data-recent-alert-key="${escapeHtml(signalEventKey(event))}">${inner}</button>`;
      }).join("");
      return `<section class="event-snapshot-card recent-alert-card">
        <button class="event-snapshot-head" type="button" data-signal-history-open aria-label="${escapeHtml(t("signalHistoryTitle"))}">
          <span class="event-snapshot-title">${escapeHtml(t("recentAlerts"))}</span>
          <span class="event-snapshot-arrow" aria-hidden="true">
            <i class="fa-solid fa-chevron-right" aria-hidden="true"></i>
          </span>
        </button>
        <div class="recent-alert-list">
          ${rows || `<div class="recent-alert-empty">${escapeHtml(t("noRecentAlerts"))}</div>`}
        </div>
      </section>`;
    }

    function renderScheduleAlerts() {
      const calendarCard = renderCalendarBanner();
      const alertsCard = renderRecentAlertsCard();
      if (!calendarCard && !alertsCard) return "";
      return `<section class="schedule-alerts">
        <div class="schedule-alerts-head">
          <h2>${escapeHtml(t("scheduleAlerts"))}</h2>
        </div>
        <div class="schedule-alerts-grid">
          ${calendarCard}${alertsCard}
        </div>
      </section>`;
    }

    function isGrossFlowMetric(metric) {
      const key = String(metric?.history_key || metric?.id || "");
      if (/^krx-flow-/.test(key) && /-(buy|sell)$/.test(key)) return true;
      const name = String(metric?.name || "");
      return (name.includes(" 매수") || name.includes(" 매도")) && !name.includes("순매수");
    }

    function heatmapIntensity(value) {
      const abs = Math.abs(Number(value) || 0);
      if (abs >= 3) return "heat-3";
      if (abs >= 1.5) return "heat-2";
      if (abs >= 0.5) return "heat-1";
      return "heat-0";
    }

    function renderDailyHeatmap() {
      const metrics = changedMetrics()
        .filter((metric) => !isGrossFlowMetric(metric))
        .filter((metric) => typeof metric.change_pct === "number" && Number.isFinite(metric.change_pct))
        .sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct))
        .slice(0, 24);
      if (!metrics.length) return "";
      return `<section class="daily-heatmap">
        <div class="daily-heatmap-head">
          <h2>${escapeHtml(t("dailyHeatmap"))}</h2>
          <span class="favorite-metrics-count">${metrics.length}${state.language === "ko" ? "개" : ` ${escapeHtml(t("favoriteCount"))}`}</span>
        </div>
        <div class="daily-heatmap-grid">
          ${metrics.map((metric) => `<button class="daily-heatmap-tile ${heatmapIntensity(metric.change_pct)}" type="button" data-daily-update-metric="${escapeHtml(metric.id)}">
            <span class="daily-heatmap-title">${escapeHtml(localizedField(metric, "name"))}</span>
            <span class="daily-heatmap-change">${escapeHtml(metric.change_pct_label || numberText(metric.change_pct, true))}</span>
            <span class="daily-heatmap-caption">${escapeHtml(localizedIndustry(metric.industry))} · ${escapeHtml(localizedGroup(metric.group, [metric]))}</span>
          </button>`).join("")}
        </div>
      </section>`;
    }

    function moverTickerMetrics() {
      return changedMetrics()
        .filter((metric) => !isGrossFlowMetric(metric))
        .filter((metric) => (
          typeof metric.change_pct === "number" && Number.isFinite(metric.change_pct)
        ) || (
          typeof metric.change_abs === "number" && Number.isFinite(metric.change_abs)
        ) || metric.daily_status === "new")
        .sort((a, b) => {
          const aPct = typeof a.change_pct === "number" && Number.isFinite(a.change_pct) ? Math.abs(a.change_pct) : -1;
          const bPct = typeof b.change_pct === "number" && Number.isFinite(b.change_pct) ? Math.abs(b.change_pct) : -1;
          if (aPct !== bPct) return bPct - aPct;
          const aAbs = typeof a.change_abs === "number" && Number.isFinite(a.change_abs) ? Math.abs(a.change_abs) : 0;
          const bAbs = typeof b.change_abs === "number" && Number.isFinite(b.change_abs) ? Math.abs(b.change_abs) : 0;
          return bAbs - aAbs;
        })
        .slice(0, 24);
    }

    function moverTickerChangeText(metric) {
      const absolute = displayMetricChange(metric);
      const pct = metric.change_pct_label || (
        typeof metric.change_pct === "number" && Number.isFinite(metric.change_pct)
          ? `${numberText(metric.change_pct, true)}%`
          : ""
      );
      if (absolute && pct) return `${absolute} (${pct})`;
      if (absolute) return absolute;
      if (pct) return pct;
      return metric.daily_status === "new" ? t("newBadge") : "n/a";
    }

    function moverTickerItemMarkup(metric, duplicate = false) {
      const change = moverTickerChangeText(metric);
      const attrs = duplicate ? ` tabindex="-1" aria-hidden="true"` : "";
      const label = `${localizedField(metric, "name")} ${displayMetricValue(metric)} ${change}`;
      return `<button class="mover-ticker-item" type="button" data-daily-update-metric="${escapeHtml(metric.id)}"${attrs} aria-label="${escapeHtml(label)}">
        <span class="mover-ticker-name">${escapeHtml(localizedField(metric, "name"))}${countryBadgeMarkup(metricCountryCode(metric), "metric-country-badge is-compact")}</span>
        <span class="mover-ticker-value">${escapeHtml(displayMetricValue(metric))}</span>
        <span class="mover-ticker-change ${directionClass(metric.change_pct)}">${escapeHtml(change)}</span>
      </button>`;
    }

    function renderMoverTicker(enabled = true) {
      const section = document.getElementById("moverTicker");
      if (!section) return;
      const metrics = enabled && !isSearchFiltering() ? moverTickerMetrics() : [];
      document.body.classList.toggle("has-mover-ticker", Boolean(metrics.length));
      if (!metrics.length) {
        section.hidden = true;
        section.innerHTML = "";
        return;
      }
      const primaryItems = metrics.map((metric) => moverTickerItemMarkup(metric, false)).join("");
      const duplicateItems = metrics.map((metric) => moverTickerItemMarkup(metric, true)).join("");
      const duration = Math.max(120, Math.min(280, metrics.length * 10));
      section.hidden = false;
      section.style.setProperty("--mover-ticker-duration", `${duration}s`);
      section.innerHTML = `<div class="mover-ticker-viewport" aria-label="${escapeHtml(t("dailyHeatmap"))}">
        <div class="mover-ticker-track">
          <div class="mover-ticker-group">${primaryItems}</div>
          <div class="mover-ticker-group" aria-hidden="true">${duplicateItems}</div>
        </div>
      </div>`;
    }

    function renderSearchResultsCards() {
      if (!isSearchFiltering()) return "";
      const metrics = countryFilteredMetrics(state.searchResults || []);
      if (!metrics.length) return "";
      const top = metrics.slice(0, 12);
      const extra = Math.max(0, metrics.length - top.length);
      return `<section class="favorite-metrics search-results-cards">
        <div class="favorite-metrics-head">
          <h2>${escapeHtml(t("metricSearchCount"))}</h2>
          <span class="favorite-metrics-count">${metrics.length}${extra ? ` · ${extra}${state.language === "ko" ? "" : " "}${escapeHtml(t("metricSearchMore"))}` : ""}</span>
        </div>
        <div class="favorite-metrics-grid">${top.map(favoriteMetricCard).join("")}</div>
      </section>`;
    }

    function freshnessSummaryData() {
      const summary = DASHBOARD_DATA.freshness_summary;
      if (summary && Number(summary.total_count || 0) > 0) return summary;
      const metrics = (DASHBOARD_DATA.metrics || []).filter((metric) => metric && typeof metric === "object");
      const delayed = metrics.filter((metric) => metric.is_stale).length;
      const failed = metrics.filter((metric) => metric.fetch_status === "failed" || metric.status === "error").length;
      return {
        total_count: metrics.length,
        current_count: Math.max(0, metrics.length - delayed - failed),
        updated_count: metrics.filter((metric) => metric.fetch_status === "success").length,
        waiting_count: metrics.filter((metric) => metric.fetch_status === "no_new_data").length,
        delayed_count: delayed,
        failed_count: failed,
        last_checked_at: DASHBOARD_DATA.generated_at || "",
        latest_observed_at: metrics.reduce((latest, metric) => String(metric.observed_at || "") > latest ? String(metric.observed_at || "") : latest, ""),
        status: failed ? "failed" : delayed ? "delayed" : "current",
        sources: [],
      };
    }

    function freshnessSourceState(source) {
      if (Number(source.failed_count || 0) > 0) return "failed";
      if (Number(source.delayed_count || 0) > 0) return "delayed";
      return "current";
    }

    function freshnessStateText(stateName) {
      if (stateName === "failed") return t("dataFreshnessFailed");
      if (stateName === "delayed") return t("dataFreshnessDelayed");
      return t("dataFreshnessCurrent");
    }

    function renderDataFreshness() {
      const summary = freshnessSummaryData();
      const total = Number(summary.total_count || 0);
      if (!total) return "";
      const current = Number(summary.current_count || 0);
      const stateName = String(summary.status || "current");
      const checkedAt = String(summary.last_checked_at || summary.generated_at || DASHBOARD_DATA.generated_at || "");
      const checkedRelative = metricUpdatedAtText({ fetched_at: checkedAt });
      const checkedExact = fetchedAtText(checkedAt);
      const latestObserved = dateText(summary.latest_observed_at || "");
      const sources = Array.isArray(summary.sources) ? summary.sources : [];
      const sourceRows = sources.map((source) => {
        const sourceState = freshnessSourceState(source);
        const sourceChecked = String(source.last_checked_at || "");
        const sourceLatest = dateText(source.latest_observed_at || "");
        const sourceCount = Number(source.total_count || 0);
        return `<div class="data-freshness-source">
          <span class="data-freshness-source-name" title="${escapeHtml(source.name || "")}">${escapeHtml(source.name || "")}</span>
          <span title="${escapeHtml(fetchedAtText(sourceChecked))}">${escapeHtml(metricUpdatedAtText({ fetched_at: sourceChecked }))}</span>
          <span>${escapeHtml(sourceLatest || "-")}</span>
          <span class="data-freshness-source-state ${sourceState}">${escapeHtml(freshnessStateText(sourceState))} ${sourceCount}</span>
        </div>`;
      }).join("");
      const title = state.language === "ko"
        ? `${t("dataFreshness")} · ${total}개 중 ${current}개 ${t("dataFreshnessCurrent")}`
        : `${t("dataFreshness")} · ${current} of ${total} ${t("dataFreshnessCurrent").toLowerCase()}`;
      const metaParts = [
        `${t("dataFreshnessLastChecked")} ${checkedRelative || checkedExact || "-"}`,
        `${t("dataFreshnessLatestObservation")} ${latestObserved || "-"}`,
      ];
      return `<details class="data-freshness">
        <summary class="data-freshness-summary">
          <span class="data-freshness-dot ${escapeHtml(stateName)}" aria-hidden="true"></span>
          <span class="data-freshness-copy">
            <span class="data-freshness-title">${escapeHtml(title)}</span>
            <span class="data-freshness-meta" title="${escapeHtml(checkedExact)}">${escapeHtml(metaParts.join(" · "))}</span>
          </span>
          <i class="fa-solid fa-chevron-down data-freshness-chevron" aria-hidden="true"></i>
        </summary>
        <div class="data-freshness-panel">
          <div class="data-freshness-stats">
            <div class="data-freshness-stat"><strong>${current}</strong><span>${escapeHtml(t("dataFreshnessCurrent"))}</span></div>
            <div class="data-freshness-stat"><strong>${Number(summary.updated_count || 0)}</strong><span>${escapeHtml(t("dataFreshnessUpdated"))}</span></div>
            <div class="data-freshness-stat"><strong>${Number(summary.waiting_count || 0)}</strong><span>${escapeHtml(t("dataFreshnessWaiting"))}</span></div>
            <div class="data-freshness-stat"><strong>${Number(summary.delayed_count || 0)}</strong><span>${escapeHtml(t("dataFreshnessDelayed"))}</span></div>
            <div class="data-freshness-stat"><strong>${Number(summary.failed_count || 0)}</strong><span>${escapeHtml(t("dataFreshnessFailed"))}</span></div>
          </div>
          ${sourceRows ? `<div class="data-freshness-sources" aria-label="${escapeHtml(t("dataFreshnessSources"))}">${sourceRows}</div>` : ""}
        </div>
      </details>`;
    }

    function renderDailyUpdates() {
      const section = document.getElementById("dailyUpdates");
      if (!section) return;
      const overviewActive = state.navRoot === "overview";
      section.classList.toggle("is-overview-content", overviewActive && !isSearchFiltering());
      renderMoverTicker(overviewActive);
      if (state.navRoot === "future" && !isSearchFiltering()) {
        section.innerHTML = "";
        return;
      }
      if (isSearchFiltering()) {
        section.innerHTML = renderSearchResultsCards();
        initDailyUpdateLinks();
        return;
      }
      if (!overviewActive) {
        section.innerHTML = "";
        return;
      }
      const summary = DASHBOARD_DATA.daily_changes || {};
      const changes = changedMetrics();
      const updatedCount = state.countryFilter === "ALL"
        ? Number(summary.updated_count || changes.filter((metric) => metric.daily_status === "updated").length)
        : changes.filter((metric) => metric.daily_status === "updated").length;
      const newCount = state.countryFilter === "ALL"
        ? Number(summary.new_count || changes.filter((metric) => metric.daily_status === "new").length)
        : changes.filter((metric) => metric.daily_status === "new").length;
      const rows = changes.map((metric) => `
        <button class="daily-update-row" type="button" data-daily-update-metric="${escapeHtml(metric.id)}">
          <span class="daily-update-main">
            ${metricStatusMarkup(metric)}
            <span class="daily-update-title">${escapeHtml(localizedField(metric, "name"))}${countryBadgeMarkup(metricCountryCode(metric), "metric-country-badge is-compact")}</span>
          </span>
          <span class="daily-update-meta">${escapeHtml(localizedIndustry(metric.industry))} · ${escapeHtml(localizedGroup(metric.group, [metric]))} · ${escapeHtml(dateText(metric.observed_label, metric))}</span>
          <span class="daily-update-value">${escapeHtml(displayMetricValue(metric))}</span>
          <span class="daily-update-change ${directionClass(metric.change_pct)}">
            <i class="fa-solid ${trendIconClass(metric.change_pct)}" aria-hidden="true"></i>
            <span class="daily-update-change-abs">${escapeHtml(displayMetricChange(metric) || "n/a")}</span>
            <span class="daily-update-change-pct">${escapeHtml(metric.change_pct_label || "n/a")}</span>
          </span>
        </button>
      `).join("");
      const briefing = renderMorningBriefing();
      const favorites = renderFavoriteMetrics();
      const scheduleAlerts = renderScheduleAlerts();
      const topRow = briefing || scheduleAlerts ? `<div class="overview-hero">${briefing}${scheduleAlerts}</div>` : "";
      const gauges = renderMarketGauges();
      section.innerHTML = `${topRow}${gauges}${favorites}<details class="daily-update-details">
        <summary class="daily-update-summary">
          <span>${escapeHtml(t("showDailyChanges"))}</span>
          <span class="daily-update-summary-icon" aria-hidden="true">›</span>
        </summary>
        <div class="daily-update-panel">
          <div class="daily-update-list">
            ${rows || `<div class="daily-update-empty">${escapeHtml(t("noDailyChanges"))}</div>`}
          </div>
          <div class="daily-update-counts" aria-label="${escapeHtml(t("todayChanges"))}">
            <span class="daily-update-count">${escapeHtml(t("updatedCount"))} ${updatedCount}</span>
            <span class="daily-update-count">${escapeHtml(t("newCount"))} ${newCount}</span>
          </div>
        </div>
      </details>`;
      initDailyUpdateLinks();
      initFavoriteButtons(section);
      initFavoritePager(section);
      initBriefingTimeline();
      initGaugeCardScrollDrag(section);
      initGaugeHistoryControls(section);
    }

    function renderIndustry(industry, metrics) {
      const icon = DASHBOARD_DATA.industry_icons?.[industry] || "";
      const renderGroups = (items, hiddenGroup = "") => [...groupMetrics(items, (metric) => metric.group || "핵심 지표").entries()]
        .sort(([a], [b]) => groupRank(a) - groupRank(b) || String(a).localeCompare(String(b), "ko"))
        .map(([group, items]) => {
          const groupTitle = group === hiddenGroup ? "" : `<div class="group-title">${escapeHtml(localizedGroup(group, items))}</div>`;
          return `
            <section class="group">
            ${groupTitle}
            <div class="metric-table-wrap">
              <table class="metric-table">
                <colgroup>
                  <col class="metric-name-cell">
                  <col class="metric-description-cell">
                  <col class="metric-date-cell">
                  <col class="metric-value-cell">
                  <col class="metric-chart-cell">
                  <col class="metric-favorite-cell">
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col" data-mobile-label="${escapeHtml(t("metricSummary"))}">${escapeHtml(t("metric"))}</th>
                    <th scope="col">${escapeHtml(t("description"))}</th>
                    <th scope="col">${escapeHtml(t("lastUpdated"))}</th>
                    <th scope="col" data-mobile-label="${escapeHtml(t("metricValueShort"))}">${escapeHtml(t("currentValue"))}</th>
                    <th scope="col" data-mobile-label="${escapeHtml(t("chart"))}">${escapeHtml(t("chart"))}</th>
                    <th scope="col"><span class="sr-only">${escapeHtml(t("favoriteMetrics"))}</span></th>
                  </tr>
                </thead>
                <tbody>${items.map(metricRows).join("")}</tbody>
              </table>
            </div>
          </section>
        `;
        }).join("");
      const semiconductorGroups = industry === "반도체"
        ? [...groupMetrics(metrics, (metric) => metric.depth || "전체 업황").entries()]
            .sort(([a], [b]) => depthRank(a) - depthRank(b) || String(a).localeCompare(String(b), "ko"))
        : [];
      const renderDepthSection = ([depth, items]) => `
        <section class="depth-section" id="${depthId(industry, depth)}" data-depth-section data-depth-name="${escapeHtml(depth)}">
          <div class="depth-title">${escapeHtml(localizedDepth(depth, items))}</div>
          ${renderGroups(items, depth)}
        </section>
      `;
      const groupHtml = industry === "반도체"
        ? [
            ...semiconductorGroups
              .filter(([depth]) => depth === "전체 업황")
              .map(([, items]) => renderGroups(items)),
            (() => {
              const depthHtml = semiconductorGroups
                .filter(([depth]) => depth !== "전체 업황")
                .map(renderDepthSection)
                .join("");
              return depthHtml ? `<div class="depth-tree">${depthHtml}</div>` : "";
            })()
          ].join("")
        : renderGroups(metrics);

      return `<article class="industry" id="${industryId(industry)}" data-industry-section data-industry-name="${escapeHtml(industry)}">
        <div class="industry-head">
          <div class="industry-icon-wrap">${icon ? `<img class="industry-icon" src="${escapeHtml(icon)}" alt="">` : ""}</div>
          <div>
            <h2>${escapeHtml(localizedIndustry(industry))}</h2>
          </div>
        </div>
        <div class="group-stack">${groupHtml}</div>
      </article>`;
    }

    function marketSectionId(category) {
      return `market-${idSegment(category)}`;
    }

    function renderMarketCategory(category, metrics) {
      const byDepth = [...groupMetrics(metrics, (metric) => metric.depth || localizedMarketCategory(category)).entries()]
        .sort(([a], [b]) => String(a).localeCompare(String(b), "ko"));
      const renderGroups = (items) => [...groupMetrics(items, (metric) => metric.group || "핵심 지표").entries()]
        .sort(([a], [b]) => groupRank(a) - groupRank(b) || String(a).localeCompare(String(b), "ko"))
        .map(([group, items]) => `
          <section class="group">
            <div class="group-title">${escapeHtml(localizedGroup(group, items))}</div>
            <div class="metric-table-wrap">
              <table class="metric-table">
                <colgroup>
                  <col class="metric-name-cell">
                  <col class="metric-description-cell">
                  <col class="metric-date-cell">
                  <col class="metric-value-cell">
                  <col class="metric-chart-cell">
                  <col class="metric-favorite-cell">
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col" data-mobile-label="${escapeHtml(t("metricSummary"))}">${escapeHtml(t("metric"))}</th>
                    <th scope="col">${escapeHtml(t("description"))}</th>
                    <th scope="col">${escapeHtml(t("lastUpdated"))}</th>
                    <th scope="col" data-mobile-label="${escapeHtml(t("metricValueShort"))}">${escapeHtml(t("currentValue"))}</th>
                    <th scope="col" data-mobile-label="${escapeHtml(t("chart"))}">${escapeHtml(t("chart"))}</th>
                    <th scope="col"><span class="sr-only">${escapeHtml(t("favoriteMetrics"))}</span></th>
                  </tr>
                </thead>
                <tbody>${items.map(metricRows).join("")}</tbody>
              </table>
            </div>
          </section>
        `).join("");
      const content = byDepth.length > 1
        ? byDepth.map(([depth, items]) => `
          <section class="depth-section" data-depth-section data-depth-name="${escapeHtml(depth)}">
            <div class="depth-title">${escapeHtml(localizedDepth(depth, items))}</div>
            ${renderGroups(items)}
          </section>
        `).join("")
        : renderGroups(metrics);
      return `<article class="industry" id="${marketSectionId(category)}" data-market-section data-market-category="${escapeHtml(category)}">
        <div class="industry-head">
          <div>
            <h2>${escapeHtml(localizedMarketCategory(category))}</h2>
          </div>
        </div>
        <div class="group-stack">${content || `<div class="empty" style="display:block">${escapeHtml(t("empty"))}</div>`}</div>
      </article>`;
    }
