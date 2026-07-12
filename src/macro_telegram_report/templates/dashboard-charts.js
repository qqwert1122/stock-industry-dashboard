    function formatAxisValue(value) {
      const abs = Math.abs(value);
      if (abs >= 1000) return `${(value / 1000).toFixed(1)}k`;
      if (abs >= 100) return value.toFixed(0);
      if (abs >= 10) return value.toFixed(1);
      return value.toFixed(2);
    }

    function selectedTimeZoneKey() {
      return state.timeZone === timeZoneOptions.us ? "us" : "korea";
    }

    function selectedTimeZoneLabel() {
      return selectedTimeZoneKey() === "us" ? t("timeZoneUs") : t("timeZoneKorea");
    }

    function selectedTimeZoneShortLabel() {
      return selectedTimeZoneKey() === "us" ? "ET" : "KST";
    }

    function metricFrequencyText(metric) {
      return String(metric?.frequency || metric?.frequency_en || "");
    }

    function isPeriodMetric(metric) {
      const frequency = metricFrequencyText(metric);
      return /월간|분기|연간|monthly|quarter|annual|year/i.test(frequency);
    }

    function shouldConvertDateForMetric(metric, value) {
      const text = String(value || "");
      const hasDay = /^(\d{4})[.-](\d{1,2})[.-](\d{1,2})/.test(text);
      if (!hasDay) return false;
      return !isPeriodMetric(metric);
    }

    function rawDateParts(value) {
      const match = String(value || "").match(/^(\d{4})[.-](\d{1,2})(?:[.-](\d{1,2}))?/);
      if (!match) return null;
      const year = Number(match[1]);
      const month = Number(match[2]);
      const day = match[3] ? Number(match[3]) : null;
      if (!Number.isFinite(year) || !Number.isFinite(month)) return null;
      if (day !== null && !Number.isFinite(day)) return null;
      return { year, month, day };
    }

    function zonedDateParts(value, metric = null) {
      const raw = rawDateParts(value);
      if (!raw) return null;
      if (!raw.day || !shouldConvertDateForMetric(metric, value)) return raw;
      const instant = new Date(Date.UTC(raw.year, raw.month - 1, raw.day));
      const formatter = new Intl.DateTimeFormat("en-CA", {
        timeZone: state.timeZone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit"
      });
      const parts = {};
      formatter.formatToParts(instant).forEach((part) => {
        if (part.type !== "literal") parts[part.type] = part.value;
      });
      return {
        year: Number(parts.year),
        month: Number(parts.month),
        day: Number(parts.day)
      };
    }

    function yearLabel(dateText, metric = null) {
      const parts = zonedDateParts(dateText, metric);
      if (!parts) return "";
      const year = Number(parts.year);
      if (!Number.isFinite(year)) return "";
      return state.language === "en" ? String(year) : `${year}년`;
    }

    function monthLabel(month) {
      const monthNumber = Number(month);
      if (!Number.isFinite(monthNumber)) return "";
      if (state.language === "en") {
        const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        return monthNames[Math.max(0, Math.min(11, monthNumber - 1))] || String(monthNumber);
      }
      return `${monthNumber}월`;
    }

    function chartDateParts(dateText, metric = null) {
      const parts = zonedDateParts(dateText, metric);
      if (!parts) return null;
      return { year: parts.year, month: parts.month, day: parts.day || null };
    }

    function chartPointDateLabel(dateText, metric = null) {
      const date = chartDateParts(dateText, metric);
      if (!date) return dateText || "";
      const day = date.day ? Number(date.day) : null;
      if (state.language === "en") {
        return day ? `${monthLabel(date.month)} ${day}, ${date.year}` : `${monthLabel(date.month)} ${date.year}`;
      }
      return day ? `${date.year}년 ${date.month}월 ${day}일` : `${date.year}년 ${date.month}월`;
    }

    function detailTickLabel(point, seenYears, metric = null) {
      const date = chartDateParts(point.date, metric);
      if (!date) return "";
      if (!seenYears.has(date.year)) {
        seenYears.add(date.year);
        return yearLabel(point.date, metric);
      }
      if ([3, 6, 9].includes(date.month)) {
        return monthLabel(date.month);
      }
      return "";
    }

    function chartTicks(history, left, right, includeQuarterMonths = false, xForPoint = null, metric = null) {
      const seen = new Set();
      const seenYears = new Set();
      const ticks = [];
      history.forEach((point, index) => {
        const yearText = yearLabel(point.date, metric);
        const label = includeQuarterMonths
          ? detailTickLabel(point, seenYears, metric)
          : yearText;
        if (!label) return;
        const key = includeQuarterMonths ? `${point.date}-${label}` : String(point.date).slice(0, 4);
        if (seen.has(key)) return;
        seen.add(key);
        const x = xForPoint
          ? xForPoint(point, index)
          : left + (index / Math.max(history.length - 1, 1)) * (right - left);
        ticks.push({ label, x, priority: label === yearText ? 2 : 1 });
      });
      if (ticks.length === 1 && history.length > 1) {
        ticks.push({ label: yearLabel(history[history.length - 1].date, metric), x: right, priority: 2 });
      }
      return compactChartTicks(
        ticks.filter((tick, index) => index === 0 || tick.label !== ticks[index - 1].label),
        includeQuarterMonths ? 46 : 54
      );
    }

    function compactChartTicks(ticks, minGap) {
      const kept = [];
      ticks.forEach((tick) => {
        const previous = kept[kept.length - 1];
        if (!previous || tick.x - previous.x >= minGap) {
          kept.push(tick);
          return;
        }
        if ((tick.priority || 0) > (previous.priority || 0)) {
          kept[kept.length - 1] = tick;
        }
      });
      return kept;
    }

    function separatedLabelPositions(levels, minY, maxY, minGap = 11) {
      const sorted = [...levels]
        .sort((a, b) => a.y - b.y)
        .map((level) => ({ ...level, preferredY: Math.min(maxY, Math.max(minY, level.y)) }));
      if (sorted.length <= 1) {
        return sorted.map((level) => ({ ...level, labelY: level.preferredY }));
      }

      const availableGap = (maxY - minY) / Math.max(sorted.length - 1, 1);
      const gap = Math.min(minGap, availableGap);
      const groups = sorted.map((_, index) => ({ start: index, end: index }));
      const positions = new Array(sorted.length);

      const layoutGroups = () => {
        groups.forEach((group) => {
          const count = group.end - group.start + 1;
          let startSum = 0;
          for (let index = group.start; index <= group.end; index += 1) {
            startSum += sorted[index].preferredY - (index - group.start) * gap;
          }
          const rawStart = startSum / count;
          const minStart = minY;
          const maxStart = maxY - (count - 1) * gap;
          const start = Math.min(maxStart, Math.max(minStart, rawStart));
          for (let index = group.start; index <= group.end; index += 1) {
            positions[index] = start + (index - group.start) * gap;
          }
        });
      };

      for (let pass = 0; pass < sorted.length; pass += 1) {
        layoutGroups();
        const mergeIndex = groups.findIndex((group, index) => {
          const next = groups[index + 1];
          return next && positions[next.start] - positions[group.end] < gap - 0.01;
        });
        if (mergeIndex === -1) break;
        const current = groups[mergeIndex];
        const next = groups[mergeIndex + 1];
        groups.splice(mergeIndex, 2, { start: current.start, end: next.end });
      }
      layoutGroups();

      return sorted.map((level, index) => ({
        ...level,
        labelY: Math.min(maxY, Math.max(minY, positions[index]))
      }));
    }

    function chartTimeValue(point) {
      const match = String(point?.date || "").match(/^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?/);
      if (!match) return null;
      const year = Number(match[1]);
      const month = Number(match[2]);
      const day = match[3] ? Number(match[3]) : 1;
      if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null;
      return Date.UTC(year, month - 1, day);
    }

    function chartMonthSpan(points) {
      if (!Array.isArray(points) || points.length < 2) return 0;
      const first = rawDateParts(points[0].date);
      const last = rawDateParts(points[points.length - 1].date);
      if (!first || !last) return 0;
      return Math.max(0, (last.year - first.year) * 12 + (last.month - first.month));
    }

    function chartTimeBounds(points) {
      const times = (points || [])
        .map(chartTimeValue)
        .filter((value) => typeof value === "number" && Number.isFinite(value));
      if (times.length < 2) return null;
      const min = Math.min(...times);
      const max = Math.max(...times);
      return max > min ? { min, max } : null;
    }

    function chartXScale(points, left, right) {
      const bounds = chartTimeBounds(points);
      if (!bounds) {
        return (point, index) => left + (index / Math.max(points.length - 1, 1)) * (right - left);
      }
      return (point, index) => {
        const time = chartTimeValue(point);
        if (typeof time !== "number" || !Number.isFinite(time)) {
          return left + (index / Math.max(points.length - 1, 1)) * (right - left);
        }
        const ratio = Math.min(1, Math.max(0, (time - bounds.min) / (bounds.max - bounds.min)));
        return left + ratio * (right - left);
      };
    }

    function detailChartAvailableWidth() {
      const containerWidth = document.getElementById("industryStack")?.clientWidth
        || document.querySelector(".content")?.clientWidth
        || window.innerWidth
        || 520;
      const axisWidth = mobileDrawerQuery.matches ? 40 : 42;
      const minimum = mobileDrawerQuery.matches ? 360 : 520;
      return Math.max(minimum, Math.floor(containerWidth - axisWidth));
    }

    function detailChartWidth(points, extraAxisWidth = 0) {
      const count = Array.isArray(points) ? points.length : 0;
      const perPointWidth = mobileDrawerQuery.matches ? 18 : 22;
      const perMonthWidth = mobileDrawerQuery.matches ? 11 : 14;
      const monthSpan = chartMonthSpan(points);
      const availableWidth = Math.max(
        mobileDrawerQuery.matches ? 360 : 520,
        detailChartAvailableWidth() - Math.max(0, extraAxisWidth)
      );
      const width = Math.max(
        availableWidth,
        count * perPointWidth,
        monthSpan > 0 ? (monthSpan + 1) * perMonthWidth : 0
      );
      return Math.min(4200, width);
    }

    function detailChartUnit(metric) {
      const scale = state.currency === "krw" ? dollarUnitScale(metric || {}) : null;
      return scale ? scale.unit : localizedUnit(metric || {});
    }

    function detailPointValueLabel(value, unit) {
      return formatMetricNumberWithUnit(value, unit);
    }

    function detailPointChangeLabel(point, previous, unit) {
      if (!previous || typeof point.value !== "number" || typeof previous.value !== "number") return "n/a";
      if (!Number.isFinite(point.value) || !Number.isFinite(previous.value)) return "n/a";
      const absolute = point.value - previous.value;
      const pct = previous.value === 0 ? null : (absolute / Math.abs(previous.value)) * 100;
      const absoluteLabel = formatMetricNumberWithUnit(absolute, unit, true, true);
      const pctLabel = typeof pct === "number" && Number.isFinite(pct) ? `${numberText(pct, true)}%` : "n/a";
      return `${absoluteLabel} / ${pctLabel}`;
    }

    function rollingSumPoints(points, window = 20) {
      const values = [];
      return (points || []).map((point) => {
        values.push(Number(point.value) || 0);
        return { date: point.date, value: values.slice(-window).reduce((sum, value) => sum + value, 0) };
      });
    }

    function flowBarDetailChart(history, metric = null) {
      const displayPoints = displayHistory(history, metric);
      if (!displayPoints || displayPoints.length < 2) {
        return detailChart(history, { ...metric, chart_style: "" });
      }
      const svgWidth = detailChartWidth(displayPoints);
      const chartStyle = ` style="--detail-chart-width: ${svgWidth}px"`;
      const isMobileChart = mobileDrawerQuery.matches;
      const chartHeight = isMobileChart ? 158 : 190;
      const axisWidth = isMobileChart ? 40 : 42;
      const left = 1;
      const right = svgWidth - 1;
      const top = isMobileChart ? 12 : 18;
      const axisY = chartHeight - 32;
      const bottom = axisY - 12;
      const labelBottom = chartHeight - 12;
      const values = displayPoints.map((point) => point.value).filter((value) => Number.isFinite(value));
      const cumulative = rollingSumPoints(displayPoints, 20);
      const cumulativeValues = cumulative.map((point) => point.value).filter((value) => Number.isFinite(value));
      const bound = Math.max(1, ...values.map(Math.abs), ...cumulativeValues.map(Math.abs));
      const yFor = (value) => bottom - ((value + bound) / (bound * 2)) * (bottom - top);
      const xFor = chartXScale(displayPoints, left, right);
      const zeroY = yFor(0);
      const step = Math.max(4, (right - left) / Math.max(displayPoints.length, 1));
      const barWidth = Math.max(2, Math.min(12, step * 0.62));
      const bars = displayPoints.map((point, index) => {
        const x = xFor(point, index) - barWidth / 2;
        const y = yFor(Math.max(point.value, 0));
        const height = Math.max(1, Math.abs(yFor(point.value) - zeroY));
        const cls = point.value >= 0 ? "positive" : "negative";
        return `<rect class="flow-bar ${cls}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${height.toFixed(1)}"></rect>`;
      }).join("");
      const cumulativeLine = cumulative.map((point, index) => `${xFor(point, index).toFixed(1)},${yFor(point.value).toFixed(1)}`).join(" ");
      const ticks = chartTicks(displayPoints, left, right, true, xFor, metric);
      const xGuides = ticks.map((tick) => `<text x="${tick.x.toFixed(1)}" y="${labelBottom}" text-anchor="${tick.x <= left + 2 ? "start" : tick.x >= right - 2 ? "end" : "middle"}">${tick.label}</text>`).join("");
      const axisClass = "chart detail-chart-axis";
      const plotClass = "chart chart-detail";
      return `<div class="detail-chart">
        <svg class="${axisClass}" viewBox="0 0 ${axisWidth} ${chartHeight}" preserveAspectRatio="none" aria-hidden="true">
          <text x="${(axisWidth - 2).toFixed(1)}" y="${top}" text-anchor="end" dominant-baseline="middle">${escapeHtml(formatAxisValue(bound))}</text>
          <text x="${(axisWidth - 2).toFixed(1)}" y="${zeroY.toFixed(1)}" text-anchor="end" dominant-baseline="middle">0</text>
          <text x="${(axisWidth - 2).toFixed(1)}" y="${bottom}" text-anchor="end" dominant-baseline="middle">${escapeHtml(formatAxisValue(-bound))}</text>
        </svg>
        <div class="detail-chart-scroll">
          <svg class="${plotClass}"${chartStyle} viewBox="0 0 ${svgWidth} ${chartHeight}" preserveAspectRatio="none" role="img" aria-label="flow trend">
            <line x1="${left}" y1="${zeroY.toFixed(1)}" x2="${right}" y2="${zeroY.toFixed(1)}" class="axis-line"></line>
            ${xGuides}
            ${bars}
            <polyline points="${cumulativeLine}" class="flow-cumulative-line"></polyline>
          </svg>
        </div>
      </div>`;
    }

    function detailChart(history, metric = null) {
      if (metric?.chart_style === "flow_bars") {
        return flowBarDetailChart(history, metric);
      }
      const displayPoints = displayHistory(history, metric);
      const svgWidth = detailChartWidth(displayPoints);
      const chartStyle = ` style="--detail-chart-width: ${svgWidth}px"`;
      const axisClass = "chart detail-chart-axis";
      const plotClass = "chart chart-detail";
      const isMobileChart = mobileDrawerQuery.matches;
      const chartHeight = isMobileChart ? 158 : 190;
      const axisWidth = isMobileChart ? 40 : 42;
      const axisGuideStart = axisWidth - 2;
      const left = 1;
      const right = svgWidth - 1;
      const top = isMobileChart ? 12 : 18;
      const axisY = chartHeight - 32;
      const bottom = axisY - 12;
      const labelBottom = chartHeight - 12;
      const levelMinY = top - 2;
      const levelMaxY = bottom + 2;
      const emptyPlot = `<svg class="${plotClass}"${chartStyle} viewBox="0 0 ${svgWidth} ${chartHeight}" preserveAspectRatio="none" role="img" aria-label="trend unavailable">
        <line x1="${left}" y1="${(top + bottom) / 2}" x2="${right}" y2="${(top + bottom) / 2}" class="guide"></line>
      </svg>`;
      if (!displayPoints || displayPoints.length < 2) {
        return `<div class="detail-chart">
          <svg class="${axisClass}" viewBox="0 0 ${axisWidth} ${chartHeight}" preserveAspectRatio="none" aria-hidden="true"></svg>
          <div class="detail-chart-scroll">${emptyPlot}</div>
        </div>`;
      }
      const values = displayPoints.map((point) => point.value).filter((value) => typeof value === "number" && Number.isFinite(value));
      if (values.length < 2) {
        return `<div class="detail-chart">
          <svg class="${axisClass}" viewBox="0 0 ${axisWidth} ${chartHeight}" preserveAspectRatio="none" aria-hidden="true"></svg>
          <div class="detail-chart-scroll">${emptyPlot}</div>
        </div>`;
      }
      const band = detailBandStats(metric);
      const min = Math.min(...values, ...(band ? [band.p20, band.median] : []));
      const max = Math.max(...values, ...(band ? [band.p80, band.median] : []));
      const latest = displayPoints[displayPoints.length - 1].value;
      const first = displayPoints[0].value;
      const span = max - min || 1;
      const yFor = (value) => bottom - ((value - min) / span) * (bottom - top);
      const xFor = chartXScale(displayPoints, left, right);
      const bandMarkup = band ? `<rect x="${left}" y="${yFor(band.p80).toFixed(1)}" width="${(right - left).toFixed(1)}" height="${Math.max(1, yFor(band.p20) - yFor(band.p80)).toFixed(1)}" class="pct-band"
          data-band-p20="${band.p20}" data-band-p80="${band.p80}"></rect>
        <line x1="${left}" y1="${yFor(band.median).toFixed(1)}" x2="${right}" y2="${yFor(band.median).toFixed(1)}" class="pct-band-median"
          data-band-median="${band.median}"></line>` : "";
      const points = displayPoints.map((point, index) => {
        const x = xFor(point, index);
        const y = yFor(point.value);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
      const trend = latest >= first ? "up" : "down";
      const levelEntries = [];
      [
        { value: max, type: "max" },
        { value: latest, type: "current" },
        { value: min, type: "min" }
      ].forEach((candidate) => {
        const existing = levelEntries.find((entry) => Math.abs(entry.value - candidate.value) < 1e-9);
        if (existing) {
          existing.types.push(candidate.type);
        } else {
          levelEntries.push({ value: candidate.value, types: [candidate.type] });
        }
      });
      const levels = separatedLabelPositions(
        levelEntries.map((entry) => ({
          value: entry.value,
          label: formatAxisValue(entry.value),
          y: yFor(entry.value),
          className: entry.types.map((type) => `level-${type}`).join(" ")
        })),
        levelMinY,
        levelMaxY
      );
      const yAxis = levels.map((level) => {
        const labelY = level.labelY;
        return `<g>
          <text class="${level.className}" x="${axisGuideStart.toFixed(1)}" y="${labelY.toFixed(1)}" text-anchor="end" dominant-baseline="middle">${level.label}</text>
        </g>`;
      }).join("");
      const ticks = chartTicks(displayPoints, left, right, true, xFor, metric);
      const yBackgroundLines = levels.map((level) => `
        <line x1="${left}" y1="${level.y.toFixed(1)}" x2="${right}" y2="${level.y.toFixed(1)}" class="chart-background-line level-line ${level.className}"></line>
      `).join("");
      const xBackgroundLines = ticks.map((tick) => `
        <line x1="${tick.x.toFixed(1)}" y1="${top}" x2="${tick.x.toFixed(1)}" y2="${axisY}" class="chart-background-line"></line>
      `).join("");
      const xGuides = ticks.map((tick) => {
        const anchor = tick.x <= left + 2 ? "start" : tick.x >= right - 2 ? "end" : "middle";
        return `<text x="${tick.x.toFixed(1)}" y="${labelBottom}" text-anchor="${anchor}">${tick.label}</text>`;
      }).join("");
      const signalMarkers = signalMarkersMarkup(metric || {}, displayPoints, xFor, top, bottom);
      const tooltipUnit = detailChartUnit(metric || {});
      const pointHits = displayPoints.map((point, index) => {
        const x = xFor(point, index);
        const y = yFor(point.value);
        const previous = index > 0 ? displayPoints[index - 1] : null;
        return `<circle class="detail-point-hit" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="10" fill="transparent" stroke="transparent" tabindex="0"
          data-point-index="${index}"
          data-point-x="${x.toFixed(1)}"
          data-point-y="${y.toFixed(1)}"
          data-point-value="${point.value}"
          data-tooltip-title="${escapeHtml(localizedField(metric, "name"))}"
          data-tooltip-date="${escapeHtml(chartPointDateLabel(point.date, metric))}"
          data-tooltip-value="${escapeHtml(detailPointValueLabel(point.value, tooltipUnit))}"
          data-tooltip-change="${escapeHtml(detailPointChangeLabel(point, previous, tooltipUnit))}"></circle>`;
      }).join("");
      const latestX = xFor(displayPoints[displayPoints.length - 1], displayPoints.length - 1);
      const latestY = yFor(latest);
      return `<div class="detail-chart">
        <svg class="${axisClass}" viewBox="0 0 ${axisWidth} ${chartHeight}" preserveAspectRatio="none" aria-hidden="true"
          data-axis-guide-start="${axisGuideStart}"
          data-axis-y="${axisY}"
          data-level-min-y="${levelMinY}"
          data-level-max-y="${levelMaxY}"
          data-current-value="${latest}"
          data-current-y="${latestY.toFixed(1)}"
          data-current-label="${escapeHtml(formatAxisValue(latest))}">
          ${yAxis}
          <line x1="${axisGuideStart}" y1="${axisY}" x2="${axisWidth}" y2="${axisY}" class="axis-line"></line>
        </svg>
        <div class="detail-chart-scroll">
          <svg class="${plotClass}"${chartStyle} viewBox="0 0 ${svgWidth} ${chartHeight}" preserveAspectRatio="none" role="img" aria-label="trend"
            data-chart-left="${left}"
            data-chart-right="${right}"
            data-chart-top="${top}"
            data-chart-bottom="${bottom}"
            data-chart-axis-y="${axisY}">
            ${yBackgroundLines}
            ${xBackgroundLines}
            <line x1="${left}" y1="${axisY}" x2="${right}" y2="${axisY}" class="axis-line"></line>
            ${xGuides}
            ${bandMarkup}
            ${signalMarkers}
            <polyline points="${points}" class="trend-line ${trend}"></polyline>
            <circle cx="${latestX}" cy="${latestY.toFixed(1)}" r="4" class="current-dot ${trend}"></circle>
            ${pointHits}
          </svg>
        </div>
        <div class="detail-chart-tooltip" role="status" aria-live="polite"></div>
      </div>`;
    }

    function miniChart(history, metric = null) {
      const displayPoints = displayHistory(history, metric);
      const chartClass = "chart chart-mini";
      if (!displayPoints || displayPoints.length < 2) {
        return `<svg class="${chartClass}" viewBox="0 0 160 36" role="img" aria-label="trend unavailable"></svg>`;
      }
      const values = displayPoints.map((point) => point.value).filter((value) => typeof value === "number" && Number.isFinite(value));
      const min = Math.min(...values);
      const max = Math.max(...values);
      const latest = displayPoints[displayPoints.length - 1].value;
      const first = displayPoints[0].value;
      const span = max - min || 1;
      const left = 4;
      const right = 156;
      const top = 5;
      const bottom = 31;
      const yFor = (value) => bottom - ((value - min) / span) * (bottom - top);
      const points = displayPoints.map((point, index) => {
        const x = left + (index / Math.max(displayPoints.length - 1, 1)) * (right - left);
        const y = yFor(point.value);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
      const trend = latest >= first ? "up" : "down";
      return `<svg class="${chartClass}" viewBox="0 0 160 36" role="img" aria-label="trend">
        <polyline points="${points}" class="trend-line ${trend}"></polyline>
      </svg>`;
    }

    function chart(history, extraClass = "", metric = null) {
      if (extraClass.split(" ").includes("chart-mini")) {
        return miniChart(history, metric);
      }
      const displayPoints = displayHistory(history, metric);
      const chartClass = `chart${extraClass ? ` ${extraClass}` : ""}`;
      const isDetailChart = extraClass.split(" ").includes("chart-detail");
      const svgWidth = isDetailChart ? detailChartWidth(displayPoints) : 360;
      const chartStyle = isDetailChart ? ` style="--detail-chart-width: ${svgWidth}px"` : "";
      const left = 62;
      const right = svgWidth - 16;
      if (!displayPoints || displayPoints.length < 2) {
        return `<svg class="${chartClass}"${chartStyle} viewBox="0 0 ${svgWidth} 158" role="img" aria-label="trend unavailable">
          <line x1="${left}" y1="72" x2="${right}" y2="72" class="guide"></line>
        </svg>`;
      }
      const values = displayPoints.map((point) => point.value).filter((value) => typeof value === "number" && Number.isFinite(value));
      const min = Math.min(...values);
      const max = Math.max(...values);
      const latest = displayPoints[displayPoints.length - 1].value;
      const first = displayPoints[0].value;
      const span = max - min || 1;
      const top = 16;
      const bottom = 116;
      const yFor = (value) => bottom - ((value - min) / span) * (bottom - top);
      const xFor = isDetailChart ? chartXScale(displayPoints, left, right) : null;
      const points = displayPoints.map((point, index) => {
        const x = xFor
          ? xFor(point, index)
          : left + (index / Math.max(displayPoints.length - 1, 1)) * (right - left);
        const y = yFor(point.value);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
      const trend = latest >= first ? "up" : "down";
      const levelValues = [];
      [max, latest, min].forEach((value) => {
        if (!levelValues.some((existing) => Math.abs(existing - value) < 1e-9)) {
          levelValues.push(value);
        }
      });
      const levels = separatedLabelPositions(
        levelValues.map((value) => ({
          value,
          label: formatAxisValue(value),
          y: yFor(value)
        })),
        14,
        118
      );
      const yGuides = levels.map((level) => {
        const y = level.y;
        const labelY = level.labelY;
        const connector = Math.abs(labelY - y) > 7
          ? `<line x1="50" y1="${labelY.toFixed(1)}" x2="${left}" y2="${y.toFixed(1)}" class="guide"></line>`
          : "";
        return `<g>
          <text x="8" y="${labelY.toFixed(1)}" dominant-baseline="middle">${level.label}</text>
          ${connector}
          <line x1="${left}" y1="${y.toFixed(1)}" x2="${right}" y2="${y.toFixed(1)}" class="guide"></line>
        </g>`;
      }).join("");
      const xGuides = chartTicks(displayPoints, left, right, isDetailChart, xFor, metric).map((tick) => `
        <text x="${tick.x.toFixed(1)}" y="146" text-anchor="middle">${tick.label}</text>
      `).join("");
      const latestX = xFor
        ? xFor(displayPoints[displayPoints.length - 1], displayPoints.length - 1)
        : right;
      const latestY = yFor(latest);
      return `<svg class="${chartClass}"${chartStyle} viewBox="0 0 ${svgWidth} 158" role="img" aria-label="trend">
        ${yGuides}
        <line x1="${left}" y1="126" x2="${right}" y2="126" class="axis-line"></line>
        ${xGuides}
        <polyline points="${points}" class="trend-line ${trend}"></polyline>
        <circle cx="${latestX}" cy="${latestY.toFixed(1)}" r="4" class="current-dot ${trend}"></circle>
      </svg>`;
    }

    function dateText(value, metric = null) {
      if (!value) return t("irregular");
      if (String(value).includes("비정기")) return t("irregular");
      const parts = zonedDateParts(value, metric);
      if (!parts) return value;
      if (state.language === "en") {
        const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        const month = monthNames[Math.max(0, Math.min(11, Number(parts.month) - 1))];
        return parts.day ? `${month} ${Number(parts.day)}, ${parts.year}` : `${month} ${parts.year}`;
      }
      const month = String(Number(parts.month));
      const day = parts.day ? ` ${Number(parts.day)}일` : "";
      return `${parts.year}년 ${month}월${day}`;
    }

    function plainDateText(value) {
      if (!value) return t("irregular");
      const parts = rawDateParts(value);
      if (!parts) return value;
      if (state.language === "en") {
        const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        const month = monthNames[Math.max(0, Math.min(11, Number(parts.month) - 1))];
        return parts.day ? `${month} ${Number(parts.day)}, ${parts.year}` : `${month} ${parts.year}`;
      }
      const month = String(Number(parts.month));
      const day = parts.day ? ` ${Number(parts.day)}일` : "";
      return `${parts.year}년 ${month}월${day}`;
    }

    function fullDateText(value, metric = null) {
      if (!value) return t("irregular");
      if (String(value).includes("비정기")) return t("irregular");
      const parts = zonedDateParts(value, metric);
      if (!parts) return value;
      if (state.language === "en") {
        const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        const month = monthNames[Math.max(0, Math.min(11, Number(parts.month) - 1))];
        return parts.day ? `${month} ${Number(parts.day)}, ${parts.year}` : `${month} ${parts.year}`;
      }
      const month = String(Number(parts.month));
      const day = parts.day ? ` ${Number(parts.day)}일` : "";
      return `${parts.year}년 ${month}월${day}`;
    }

    function normalizedDateTimeSource(value) {
      let normalizedSource = String(value || "");
      const kstMatch = normalizedSource.match(/^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})(?::(\d{2}))? KST$/);
      if (kstMatch) {
        normalizedSource = `${kstMatch[1]}T${kstMatch[2]}:${kstMatch[3] || "00"}+09:00`;
      }
      return normalizedSource;
    }

    function zonedDateTimeParts(value) {
      const normalizedSource = normalizedDateTimeSource(value);
      if (!normalizedSource || /^\d{4}-\d{2}-\d{2}$/.test(normalizedSource)) return null;
      const date = new Date(normalizedSource);
      if (!date || Number.isNaN(date.getTime())) return null;
      const parts = {};
      new Intl.DateTimeFormat("en-CA", {
        timeZone: state.timeZone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
        hourCycle: "h23"
      }).formatToParts(date).forEach((part) => {
        if (part.type !== "literal") parts[part.type] = part.value;
      });
      return parts;
    }

    function zonedDateKey(value) {
      const parts = zonedDateTimeParts(value);
      if (parts?.year && parts?.month && parts?.day) return `${parts.year}-${parts.month}-${parts.day}`;
      const raw = rawDateParts(value);
      if (!raw) return "";
      return `${String(raw.year).padStart(4, "0")}-${String(raw.month).padStart(2, "0")}-${String(raw.day || 1).padStart(2, "0")}`;
    }

    function dashboardTodayKey() {
      return zonedDateKey(DASHBOARD_DATA.generated_at || DASHBOARD_DATA.generated_label || new Date().toISOString());
    }

    function timeOnlyText(value) {
      const parts = zonedDateTimeParts(value);
      if (parts?.hour && parts?.minute) return `${parts.hour}:${parts.minute}`;
      const match = String(value || "").match(/(?:T| )(\d{2}):(\d{2})/);
      return match ? `${match[1]}:${match[2]}` : "";
    }

    function dateTimeText(value) {
      const parts = zonedDateTimeParts(value);
      if (!parts) return dateText(value);
      const zone = selectedTimeZoneShortLabel();
      if (state.language === "en") {
        return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute} ${zone}`;
      }
      return `${Number(parts.year)}년 ${Number(parts.month)}월 ${Number(parts.day)}일 ${parts.hour}:${parts.minute} ${zone}`;
    }

    function generatedAtLabel() {
      const source = DASHBOARD_DATA.generated_at || DASHBOARD_DATA.generated_label;
      const label = dateTimeText(source);
      return label ? `${t("lastUpdatedInline")}: ${label}${state.language === "en" ? "" : ""}` : "";
    }

    function updateLastUpdatedInline() {
      const target = document.getElementById("lastUpdatedInline");
      if (!target) return;
      target.textContent = generatedAtLabel();
    }

    function detailStat(label, value, className = "") {
      return `<div class="detail-stat">
        <span class="detail-label">${escapeHtml(label)}</span>
        <strong class="detail-value ${className}">${escapeHtml(value)}</strong>
      </div>`;
    }

    function detailCurrentValueMarkup(metric) {
      const value = String(displayMetricValue(metric) || "n/a");
      const unit = String(detailChartUnit(metric) || localizedUnit(metric) || "");
      if (unit && !unit.startsWith("$") && value.endsWith(unit)) {
        const numberPart = value.slice(0, -unit.length).trim();
        if (numberPart) {
          return `<strong>${escapeHtml(numberPart)}</strong><span class="detail-current-unit">${escapeHtml(unit)}</span>`;
        }
      }
      return `<strong>${escapeHtml(value)}</strong>`;
    }

    function detailSignedValueLabel(label, value) {
      const raw = String(label || "n/a").replace(/^\s*[+-]\s*/, "");
      if (typeof value !== "number" || !Number.isFinite(value) || value === 0) return raw;
      return `${value > 0 ? "▲" : "▼"} ${raw}`;
    }

    function detailDelta(label, valueLabel, rawValue) {
      const className = directionClass(rawValue);
      return `<span class="detail-delta">
        <span class="detail-delta-label">${escapeHtml(label)}</span>
        <strong class="detail-delta-value ${className}">${escapeHtml(detailSignedValueLabel(valueLabel, rawValue))}</strong>
      </span>`;
    }

    function detailReferenceLegend(metric = null) {
      const bandItem = detailBandStats(metric)
        ? `<button type="button" class="detail-reference-item chart-band-toggle" data-band-toggle aria-pressed="true">
          <span class="detail-reference-dot band" aria-hidden="true"></span>
          <span class="chart-band-legend-text">${escapeHtml(t("percentileBandLegend"))}</span>
          <span class="chart-band-switch" aria-hidden="true"></span>
        </button>`
        : "";
      return `<div class="detail-reference-legend" aria-label="${escapeHtml(t("chart"))}">
        <span class="detail-reference-item"><span class="detail-reference-dot max" aria-hidden="true"></span>${escapeHtml(t("detailReferenceMax"))}</span>
        <span class="detail-reference-item"><span class="detail-reference-dot current" aria-hidden="true"></span>${escapeHtml(t("detailReferenceCurrent"))}</span>
        <span class="detail-reference-item"><span class="detail-reference-dot min" aria-hidden="true"></span>${escapeHtml(t("detailReferenceMin"))}</span>
        ${bandItem}
      </div>`;
    }

    function detailSummaryMarkup(metric) {
      return `<div class="detail-summary-head">
        <div class="detail-summary-main">
          <span class="detail-eyebrow">${escapeHtml(t("currentValue"))}</span>
          <div class="detail-current-value">${detailCurrentValueMarkup(metric)}</div>
          <div class="detail-deltas">
            ${detailDelta(t("previousChange"), displayMetricChange(metric), metric.change_abs)}
            ${detailDelta(t("previousChangePct"), metric.change_pct_label, metric.change_pct)}
            ${detailDelta(t("yoy"), metric.yoy_pct_label, metric.yoy_pct)}
          </div>
        </div>
        ${detailReferenceLegend(metric)}
      </div>`;
    }

    function detailMetaItem(label, value, className = "", attributes = "") {
      return `<div class="detail-meta-item"${attributes ? ` ${attributes}` : ""}>
        <span class="detail-meta-label">${escapeHtml(label)}</span>
        <strong class="detail-meta-value ${className}">${escapeHtml(value || "n/a")}</strong>
      </div>`;
    }

    function detailMetaStrip(metric, options = {}) {
      const items = `<div class="detail-meta-strip">
        ${detailMetaItem(t("visiblePeriod"), displayPeriodLabel(metric), "", `data-period-meta="${escapeHtml(metric.id)}"`)}
        ${detailMetaItem(t("dataAsOf"), dateText(metric.observed_label || metric.observed_at, metric))}
        ${detailMetaItem(t("lastChecked"), lastCheckedText(metric), metric.fetch_status === "failed" ? "negative" : "")}
        ${detailMetaItem(t("nextUpdate"), dateText(metric.next_update_label, metric))}
        ${detailMetaItem(t("updateFrequency"), localizedField(metric, "frequency") || t("irregular"))}
      </div>`;
      if (!options.collapsible) return items;
      const expanded = Boolean(state.detailMetadataExpanded[metric.id]);
      return `<div class="detail-meta-disclosure${expanded ? " is-expanded" : ""}">
        <button class="detail-meta-toggle" type="button" data-detail-meta-toggle="${escapeHtml(metric.id)}" aria-expanded="${expanded}">
          <span>${escapeHtml(t(expanded ? "detailMetaLess" : "detailMetaMore"))}</span>
          <i class="fa-solid fa-chevron-right" aria-hidden="true"></i>
        </button>
        <div class="detail-meta-content"${expanded ? "" : " hidden"}>${items}</div>
      </div>`;
    }

    function displayPointsPeriodLabel(points, metric) {
      const history = Array.isArray(points) ? points : [];
      if (history.length) {
        const start = fullDateText(history[0].date, metric);
        const end = fullDateText(history[history.length - 1].date, metric);
        return start === end ? start : `${start} - ${end}`;
      }
      return fullDateText(metric?.observed_label || metric?.observed_at || "", metric);
    }

    function displayPeriodLabel(metric) {
      return displayPointsPeriodLabel(metric?.history, metric);
    }

    function fetchStatusText(metric) {
      if (metric?.fetch_status === "success") return t("fetchUpdated");
      if (metric?.fetch_status === "failed") return t("fetchFailed");
      if (metric?.fetch_status === "no_new_data") return t("fetchNoNewData");
      return metric?.fetch_status_label || t("fetchNoNewData");
    }

    function fetchedAtText(value) {
      return value ? dateTimeText(value) : "";
    }

    function lastCheckedText(metric) {
      const label = fetchedAtText(metric?.fetched_at || DASHBOARD_DATA.generated_at || "");
      const status = fetchStatusText(metric);
      return label ? `${label} · ${status}` : status;
    }

    function metricUpdatedAtSource(metric) {
      return metric?.fetched_at || DASHBOARD_DATA.generated_at || DASHBOARD_DATA.generated_label || metric?.observed_at || "";
    }

    function metricUpdatedAtAgeClass(metric) {
      const normalizedSource = normalizedDateTimeSource(metricUpdatedAtSource(metric));
      const date = new Date(normalizedSource);
      if (!normalizedSource || Number.isNaN(date.getTime()) || /^\d{4}-\d{2}-\d{2}$/.test(normalizedSource)) {
        return "is-stale";
      }
      const ageMs = Math.max(0, Date.now() - date.getTime());
      if (ageMs < 86400000) return "is-fresh";
      if (ageMs < 604800000) return "is-week-old";
      return "is-stale";
    }

    function metricUpdatedAtText(metric) {
      const source = metricUpdatedAtSource(metric);
      const normalizedSource = normalizedDateTimeSource(source);
      const date = new Date(normalizedSource);
      if (!normalizedSource || Number.isNaN(date.getTime()) || /^\d{4}-\d{2}-\d{2}$/.test(normalizedSource)) {
        return `${dateText(source, metric)} 업데이트`;
      }
      const diffSeconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
      let value;
      let unitKo;
      let unitEn;
      if (diffSeconds < 60) {
        value = diffSeconds;
        unitKo = "초";
        unitEn = "second";
      } else if (diffSeconds < 3600) {
        value = Math.floor(diffSeconds / 60);
        unitKo = "분";
        unitEn = "minute";
      } else if (diffSeconds < 86400) {
        value = Math.floor(diffSeconds / 3600);
        unitKo = "시간";
        unitEn = "hour";
      } else if (diffSeconds < 2592000) {
        value = Math.floor(diffSeconds / 86400);
        unitKo = "일";
        unitEn = "day";
      } else if (diffSeconds < 31536000) {
        value = Math.floor(diffSeconds / 2592000);
        unitKo = "개월";
        unitEn = "month";
      } else {
        value = Math.floor(diffSeconds / 31536000);
        unitKo = "년";
        unitEn = "year";
      }
      if (state.language === "en") {
        return `${value} ${unitEn}${value === 1 ? "" : "s"} ago`;
      }
      return `${value}${unitKo} 전 업데이트`;
    }
