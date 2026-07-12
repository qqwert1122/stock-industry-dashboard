    function renderIndustries() {
      const metrics = countryFilteredMetrics();
      const stack = document.getElementById("industryStack");
      if (isSearchFiltering()) {
        const resultIds = searchResultIds();
        const matched = countryFilteredMetrics(state.searchResults || []).filter((metric) => resultIds.has(metric.id));
        if (!matched.length) {
          document.getElementById("empty").style.display = "none";
          stack.innerHTML = `<div class="empty" style="display:block">『${escapeHtml(state.searchQuery)}』${escapeHtml(t("metricSearchEmpty"))}</div>`;
          return;
        }
        document.getElementById("empty").style.display = "none";
        const marketHtml = [{ key: overviewCategoryKey }, ...marketCategories].map((category) => {
          const items = marketMetricsForCategory(category.key).filter((metric) => resultIds.has(metric.id));
          return items.length ? renderMarketCategory(category.key, items) : "";
        }).join("");
        const byIndustry = matched.reduce((map, metric) => {
          if (!isIndustryMetric(metric)) return map;
          map.set(metric.industry, [...(map.get(metric.industry) || []), metric]);
          return map;
        }, new Map());
        const industryHtml = visibleIndustries()
          .filter((industry) => byIndustry.has(industry))
          .map((industry) => renderIndustry(industry, byIndustry.get(industry)))
          .join("");
        stack.innerHTML = marketHtml + industryHtml;
        initMetricRows();
        scheduleBranchLineUpdate();
        return;
      }
      if (state.navRoot === "overview") {
        document.getElementById("empty").style.display = "none";
        stack.innerHTML = "";
        return;
      }
      if (state.navRoot === "market") {
        document.getElementById("empty").style.display = "none";
        const favorites = renderFavoriteMetrics(favoriteMetrics().filter(isPrimaryMarketMetric), { context: true });
        const categories = marketCategories.map((category) => {
          if (category.key === "캘린더") return renderEventCalendar();
          return renderMarketCategory(category.key, marketMetricsForCategory(category.key));
        }).join("");
        stack.innerHTML = favorites + categories;
        initMetricRows();
        initFavoriteButtons(stack);
        initFavoritePager(stack);
        initDailyUpdateLinks();
        scheduleBranchLineUpdate();
        updateActiveFromScroll();
        return;
      }
      if (state.navRoot === "future") {
        document.getElementById("empty").style.display = "none";
        stack.innerHTML = state.futureView === "track-record" ? renderFutureTrackRecord() : renderFutureTimeline();
        if (state.futureView === "track-record") {
          initFutureTrackRecord();
        } else {
          initFutureTimeline();
        }
        return;
      }
      if (state.navRoot === "root") {
        document.getElementById("empty").style.display = "none";
        stack.innerHTML = "";
        return;
      }
      const industryMetrics = metrics.filter(isIndustryMetric);
      document.getElementById("empty").style.display = industryMetrics.length ? "none" : "block";
      const byIndustry = metrics.reduce((map, metric) => {
        if (!isIndustryMetric(metric)) return map;
        map.set(metric.industry, [...(map.get(metric.industry) || []), metric]);
        return map;
      }, new Map());
      const favorites = renderFavoriteMetrics(favoriteMetrics().filter(isIndustryMetric), { context: true });
      const industries = visibleIndustries()
        .filter((industry) => byIndustry.has(industry))
        .map((industry) => renderIndustry(industry, byIndustry.get(industry)))
        .join("");
      stack.innerHTML = favorites + industries;
      initMetricRows();
      initFavoriteButtons(stack);
      initFavoritePager(stack);
      initDailyUpdateLinks();
      scheduleBranchLineUpdate();
      updateActiveFromScroll();
    }

    function toggleMetricRow(row, options = {}) {
      if (mobileDrawerQuery.matches) {
        const metric = metricById(row.dataset.metricId);
        if (metric) openMetricDetail(metric.id, { updateHash: options.updateHash !== false });
        return;
      }
      const detail = document.getElementById(row.dataset.detailId);
      const toggle = row.querySelector("[data-metric-toggle]");
      if (!detail || !toggle) return;
      const expanded = !row.classList.contains("is-expanded");
      row.classList.toggle("is-expanded", expanded);
      detail.classList.toggle("is-open", expanded);
      detail.setAttribute("aria-hidden", String(!expanded));
      toggle.setAttribute("aria-expanded", String(expanded));
      if (expanded) {
        if (state.compareBaseMetricId !== row.dataset.metricId) {
          resetCompareState(row.dataset.metricId);
        }
        initDetailRange(row.dataset.metricId, detail);
        initCompareControls(detail);
        const scroller = detail.querySelector(".detail-chart-scroll");
        if (scroller) {
          requestAnimationFrame(() => {
            scroller.scrollLeft = Math.max(0, scroller.scrollWidth - scroller.clientWidth);
            scheduleDynamicDetailAxis(scroller.closest(".detail-chart"));
            updateMetricDetailHeight(detail);
          });
        }
        requestAnimationFrame(() => updateMetricDetailHeight(detail));
      } else {
        updateMetricDetailHeight(detail);
      }
      if (options.updateHash !== false) {
        const metric = metricById(row.dataset.metricId);
        writeDashboardHash(expanded && metric ? `#d/${hashSegment(metricHashKey(metric))}` : currentNavHash(), "replace");
      }
      scheduleBranchLineUpdate();
    }

    function tooltipMarkup(point) {
      return `<div class="detail-tooltip-title">${escapeHtml(point.dataset.tooltipTitle || "")}</div>
        <div class="detail-tooltip-row">
          <span class="detail-tooltip-label">${escapeHtml(t("tooltipPeriod"))}</span>
          <span class="detail-tooltip-value">${escapeHtml(point.dataset.tooltipDate || "")}</span>
        </div>
        <div class="detail-tooltip-row">
          <span class="detail-tooltip-label">${escapeHtml(t("tooltipValue"))}</span>
          <span class="detail-tooltip-value">${escapeHtml(point.dataset.tooltipValue || "")}</span>
        </div>
        <div class="detail-tooltip-row">
          <span class="detail-tooltip-label">${escapeHtml(t("tooltipChange"))}</span>
          <span class="detail-tooltip-value">${escapeHtml(point.dataset.tooltipChange || "")}</span>
        </div>`;
    }

    function showDetailTooltip(point, pinned = false) {
      const chart = point.closest(".detail-chart");
      const tooltip = chart?.querySelector(".detail-chart-tooltip");
      if (!chart || !tooltip) return;
      chart.dataset.tooltipPinned = pinned ? "true" : "false";
      tooltip.innerHTML = tooltipMarkup(point);
      tooltip.classList.add("is-visible");
      const chartRect = chart.getBoundingClientRect();
      const pointRect = point.getBoundingClientRect();
      const rawLeft = pointRect.left + pointRect.width / 2 - chartRect.left;
      const rawTop = pointRect.top - chartRect.top;
      const tooltipWidth = tooltip.offsetWidth || 180;
      const tooltipHeight = tooltip.offsetHeight || 80;
      const left = Math.min(Math.max(rawLeft, tooltipWidth / 2 + 4), chartRect.width - tooltipWidth / 2 - 4);
      const top = Math.min(Math.max(rawTop + 4, 4), Math.max(4, chartRect.height - tooltipHeight - 16));
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
    }

    function hideDetailTooltip(chart, force = false) {
      if (!chart) return;
      if (!force && chart.dataset.tooltipPinned === "true") return;
      chart.dataset.tooltipPinned = "false";
      const tooltip = chart.querySelector(".detail-chart-tooltip");
      tooltip?.classList.remove("is-visible");
    }

    function detailChartGeometry(chart) {
      const axis = chart?.querySelector(".detail-chart-axis");
      const scroller = chart?.querySelector(".detail-chart-scroll");
      const plot = chart?.querySelector(".chart-detail");
      if (!axis || !scroller || !plot) return null;
      const viewBoxWidth = plot.viewBox?.baseVal?.width || 1;
      const renderedWidth = plot.getBoundingClientRect().width || plot.clientWidth || viewBoxWidth;
      const scale = renderedWidth / Math.max(viewBoxWidth, 1);
      return {
        axis,
        scroller,
        plot,
        axisGuideStart: Number(axis.dataset.axisGuideStart) || 40,
        axisY: Number(plot.dataset.chartAxisY) || Number(axis.dataset.axisY) || 126,
        levelMinY: Number(axis.dataset.levelMinY) || 12,
        levelMaxY: Number(axis.dataset.levelMaxY) || 116,
        left: Number(plot.dataset.chartLeft) || 1,
        right: Number(plot.dataset.chartRight) || viewBoxWidth,
        top: Number(plot.dataset.chartTop) || 18,
        bottom: Number(plot.dataset.chartBottom) || 146,
        visibleLeft: scroller.scrollLeft / Math.max(scale, 0.001),
        visibleRight: (scroller.scrollLeft + scroller.clientWidth) / Math.max(scale, 0.001)
      };
    }

    function detailChartAllPoints(chart) {
      const plot = chart?.querySelector(".chart-detail");
      if (!plot) return [];
      return [...plot.querySelectorAll(".detail-point-hit")]
        .map((point) => ({
          element: point,
          x: Number(point.dataset.pointX),
          value: Number(point.dataset.pointValue)
        }))
        .filter((point) =>
          Number.isFinite(point.x) &&
          Number.isFinite(point.value)
        );
    }

    function detailChartVisiblePoints(chart) {
      const geometry = detailChartGeometry(chart);
      const points = detailChartAllPoints(chart);
      if (!geometry || !points.length) return [];
      const visible = points.filter((point) =>
        point.x >= geometry.visibleLeft - 1 &&
        point.x <= geometry.visibleRight + 1
      );
      return visible.length ? visible : points;
    }

    function dynamicDetailChartState(chart) {
      const geometry = detailChartGeometry(chart);
      const points = detailChartAllPoints(chart);
      if (!geometry || !points.length) return null;
      const visiblePoints = detailChartVisiblePoints(chart);
      if (!visiblePoints.length) return null;
      const high = visiblePoints.reduce((selected, point) => point.value > selected.value ? point : selected, visiblePoints[0]);
      const low = visiblePoints.reduce((selected, point) => point.value < selected.value ? point : selected, visiblePoints[0]);
      let min = low.value;
      let max = high.value;
      if (Math.abs(max - min) < 1e-9) {
        const pad = Math.max(Math.abs(max) * 0.01, 1);
        min -= pad;
        max += pad;
      }
      const span = max - min || 1;
      const unclampedYFor = (value) => geometry.bottom - ((value - min) / span) * (geometry.bottom - geometry.top);
      const yFor = (value) => Math.min(geometry.bottom, Math.max(geometry.top, unclampedYFor(value)));
      return { ...geometry, points, visiblePoints, high, low, min, max, span, yFor };
    }

    function dynamicAxisEntries(chart, state = dynamicDetailChartState(chart)) {
      if (!state) return [];
      const currentValue = Number(state.axis.dataset.currentValue);
      const currentAbove = Number.isFinite(currentValue) && currentValue > state.high.value;
      const currentBelow = Number.isFinite(currentValue) && currentValue < state.low.value;
      const entries = [];
      if (!currentAbove) {
        entries.push({ value: state.high.value, y: state.yFor(state.high.value), type: "max" });
      }
      if (!currentBelow) {
        entries.push({ value: state.low.value, y: state.yFor(state.low.value), type: "min" });
      }
      if (Number.isFinite(currentValue)) {
        entries.push({
          value: currentValue,
          y: state.yFor(currentValue),
          type: currentAbove || currentBelow ? "current edge-current" : "current"
        });
      }
      const merged = [];
      entries.forEach((entry) => {
        const existing = merged.find((item) => Math.abs(item.value - entry.value) < 1e-9);
        if (existing) {
          existing.type = `${existing.type} ${entry.type}`;
        } else {
          merged.push({ ...entry });
        }
      });
      return merged;
    }

    function updateDynamicDetailPlot(state) {
      const pointsAttr = state.points
        .map((point) => `${point.x.toFixed(1)},${state.yFor(point.value).toFixed(1)}`)
        .join(" ");
      state.plot.querySelector(".trend-line")?.setAttribute("points", pointsAttr);
      state.points.forEach((point) => {
        const y = state.yFor(point.value);
        point.element.setAttribute("cy", y.toFixed(1));
        point.element.dataset.pointY = y.toFixed(1);
      });
      const currentValue = Number(state.axis.dataset.currentValue);
      const currentDot = state.plot.querySelector(".current-dot");
      if (currentDot && Number.isFinite(currentValue)) {
        currentDot.setAttribute("cy", state.yFor(currentValue).toFixed(1));
      }
      const band = state.plot.querySelector(".pct-band");
      if (band) {
        const p20 = Number(band.dataset.bandP20);
        const p80 = Number(band.dataset.bandP80);
        if (Number.isFinite(p20) && Number.isFinite(p80)) {
          const y80 = state.yFor(p80);
          const y20 = state.yFor(p20);
          band.setAttribute("y", Math.min(y80, y20).toFixed(1));
          band.setAttribute("height", Math.max(1, Math.abs(y20 - y80)).toFixed(1));
        }
      }
      const median = state.plot.querySelector(".pct-band-median");
      if (median) {
        const medianValue = Number(median.dataset.bandMedian);
        if (Number.isFinite(medianValue)) {
          const y = state.yFor(medianValue).toFixed(1);
          median.setAttribute("y1", y);
          median.setAttribute("y2", y);
        }
      }
    }

    function updateDynamicLevelLines(state, levels) {
      state.plot.querySelectorAll(".chart-background-line.level-line").forEach((line) => line.remove());
      const lines = levels.map((level) => `
        <line x1="${state.left}" y1="${level.y.toFixed(1)}" x2="${state.right}" y2="${level.y.toFixed(1)}" class="chart-background-line level-line ${level.className}"></line>
      `).join("");
      const insertTarget = state.plot.querySelector(".chart-background-line") || state.plot.querySelector(".axis-line");
      if (insertTarget) {
        insertTarget.insertAdjacentHTML("beforebegin", lines);
      } else {
        state.plot.insertAdjacentHTML("afterbegin", lines);
      }
    }

    function renderDynamicDetailAxis(chart) {
      const state = dynamicDetailChartState(chart);
      if (!state) return;
      updateDynamicDetailPlot(state);
      const entries = dynamicAxisEntries(chart, state);
      if (!entries.length) return;
      const levels = separatedLabelPositions(
        entries.map((entry) => ({
          value: entry.value,
          label: formatAxisValue(entry.value),
          y: Math.min(state.levelMaxY, Math.max(state.levelMinY, entry.y)),
          className: entry.type.split(/\s+/).map((type) => `level-${type}`).join(" ")
        })),
        state.levelMinY,
        state.levelMaxY
      );
      updateDynamicLevelLines(state, levels);
      const labels = levels.map((level) => `
        <g>
          <text class="${level.className}" x="${state.axisGuideStart.toFixed(1)}" y="${level.labelY.toFixed(1)}" text-anchor="end" dominant-baseline="middle">${escapeHtml(level.label)}</text>
        </g>
      `).join("");
      state.axis.innerHTML = `${labels}<line x1="${state.axisGuideStart}" y1="${state.axisY}" x2="${state.axis.viewBox.baseVal.width}" y2="${state.axisY}" class="axis-line"></line>`;
    }

    function scheduleDynamicDetailAxis(chart) {
      if (!chart || chart.dataset.axisFrame === "true") return;
      chart.dataset.axisFrame = "true";
      requestAnimationFrame(() => {
        chart.dataset.axisFrame = "false";
        renderDynamicDetailAxis(chart);
      });
    }

    function initDynamicDetailAxes(root = document) {
      root.querySelectorAll(".detail-chart").forEach((chart) => {
        scheduleDynamicDetailAxis(chart);
      });
    }

    function initDetailChartTooltips() {
      bindDetailTooltipsWithin(document);
    }

    function bindDetailTooltipsWithin(root) {
      root.querySelectorAll(".detail-point-hit").forEach((point) => {
        point.addEventListener("mouseenter", () => showDetailTooltip(point, false));
        point.addEventListener("focus", () => showDetailTooltip(point, false));
        point.addEventListener("click", (event) => {
          event.stopPropagation();
          showDetailTooltip(point, true);
        });
        point.addEventListener("mouseleave", () => hideDetailTooltip(point.closest(".detail-chart")));
        point.addEventListener("blur", () => hideDetailTooltip(point.closest(".detail-chart")));
      });
      root.querySelectorAll(".detail-chart-scroll").forEach((scroller) => {
        scroller.addEventListener("scroll", () => {
          const chart = scroller.closest(".detail-chart");
          hideDetailTooltip(chart, true);
          scheduleDynamicDetailAxis(chart);
        }, { passive: true });
      });
      root.querySelectorAll("[data-band-toggle]").forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          const chart = button.closest(".detail-chart")
            || button.closest(".detail-chart-section")?.querySelector(".detail-chart")
            || button.closest(".metric-detail-panel")?.querySelector(".detail-chart");
          if (!chart) return;
          const enabled = button.getAttribute("aria-pressed") !== "true";
          button.setAttribute("aria-pressed", String(enabled));
          chart.classList.toggle("is-band-hidden", !enabled);
        });
      });
      initDynamicDetailAxes(root);
    }

    function initMetricRows() {
      document.querySelectorAll("[data-metric-row]").forEach((row) => {
        row.addEventListener("click", () => toggleMetricRow(row));
      });
      initInterpretationToggles();
      initFavoriteButtons();
      initNoteButtons();
      initCsvButtons();
      initCompareControls();
      initDetailChartTooltips();
    }

    function initCompareControls(root = document) {
      root.querySelectorAll("[data-compare-toggle]").forEach((button) => {
        if (button.dataset.compareBound === "true") return;
        button.dataset.compareBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          toggleComparePanel(button.dataset.compareToggle);
        });
      });
      root.querySelectorAll("[data-compare-search]").forEach((input) => {
        if (input.dataset.compareBound === "true") return;
        input.dataset.compareBound = "true";
        input.addEventListener("click", (event) => event.stopPropagation());
        input.addEventListener("input", () => scheduleCompareSearch(input.value));
      });
      root.querySelectorAll("[data-compare-add]").forEach((button) => {
        if (button.dataset.compareBound === "true") return;
        button.dataset.compareBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          addCompareMetric(button.dataset.compareAdd);
        });
      });
      root.querySelectorAll("[data-compare-add-first]").forEach((button) => {
        if (button.dataset.compareBound === "true") return;
        button.dataset.compareBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          addFirstCompareResult(button.dataset.compareAddFirst);
        });
      });
      root.querySelectorAll("[data-compare-remove]").forEach((button) => {
        if (button.dataset.compareBound === "true") return;
        button.dataset.compareBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          removeCompareMetric(button.dataset.compareRemove);
        });
      });
      root.querySelectorAll("[data-compare-mode]").forEach((button) => {
        if (button.dataset.compareBound === "true") return;
        button.dataset.compareBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          setCompareMode(button.dataset.compareMode);
        });
      });
      root.querySelectorAll("[data-compare-range]").forEach((button) => {
        if (button.dataset.compareBound === "true") return;
        button.dataset.compareBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          setCompareRange(button.dataset.compareRange);
        });
      });
      root.querySelectorAll("[data-compare-recent]").forEach((button) => {
        if (button.dataset.compareBound === "true") return;
        button.dataset.compareBound = "true";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          restoreRecentCompare(button.dataset.compareRecent);
        });
      });
    }

    function currentMenuOrder() {
      return [...document.querySelectorAll("[data-menu-item]")]
        .map((item) => item.dataset.industryItem)
        .filter(Boolean);
    }

    function dragDirection(container) {
      return getComputedStyle(container).display === "flex" ? "horizontal" : "vertical";
    }

    function initMenuDrag() {
      document.querySelectorAll("[data-menu-item]").forEach((item) => {
        item.draggable = state.isReordering;
        item.addEventListener("dragstart", (event) => {
          if (!state.isReordering) {
            event.preventDefault();
            return;
          }
          state.draggedMenuItem = item;
          item.classList.add("is-dragging");
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", item.dataset.industryItem || "");
        });
        item.addEventListener("dragend", () => {
          item.classList.remove("is-dragging");
          state.draggedMenuItem = null;
          state.draftIndustryOrder = currentMenuOrder();
        });
      });

      const menu = document.getElementById("industryFilters");
      menu.ondragover = (event) => {
        if (!state.isReordering || !state.draggedMenuItem) return;
        event.preventDefault();
        const target = event.target.closest("[data-menu-item]");
        if (!target || target === state.draggedMenuItem || !menu.contains(target)) return;
        const rect = target.getBoundingClientRect();
        const horizontal = dragDirection(menu) === "horizontal";
        const insertAfter = horizontal
          ? event.clientX > rect.left + rect.width / 2
          : event.clientY > rect.top + rect.height / 2;
        menu.insertBefore(state.draggedMenuItem, insertAfter ? target.nextSibling : target);
      };
      menu.ondrop = (event) => {
        if (!state.isReordering) return;
        event.preventDefault();
        state.draftIndustryOrder = currentMenuOrder();
      };
    }

    function initMenuScrollDrag() {
      const menu = document.getElementById("industryFilters");
      if (!menu || menu.dataset.scrollDragReady === "true") return;
      menu.dataset.scrollDragReady = "true";
      let dragState = null;

      menu.addEventListener("pointerdown", (event) => {
        if (state.isReordering || event.button !== 0 || menu.scrollHeight <= menu.clientHeight) return;
        dragState = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          startScrollTop: menu.scrollTop,
          moved: false,
          captured: false
        };
      });

      menu.addEventListener("pointermove", (event) => {
        if (!dragState || dragState.pointerId !== event.pointerId || state.isReordering) return;
        const deltaX = event.clientX - dragState.startX;
        const deltaY = event.clientY - dragState.startY;
        const dragThreshold = event.pointerType === "touch" ? 12 : 7;
        if (Math.abs(deltaY) > dragThreshold && Math.abs(deltaY) > Math.abs(deltaX)) {
          const maxScrollTop = Math.max(0, menu.scrollHeight - menu.clientHeight);
          const nextScrollTop = Math.min(maxScrollTop, Math.max(0, dragState.startScrollTop - deltaY));
          dragState.moved = true;
          suppressMenuClick = true;
          menu.classList.add("is-drag-scrolling");
          if (!dragState.captured) {
            menu.setPointerCapture?.(event.pointerId);
            dragState.captured = true;
          }
          menu.scrollTop = nextScrollTop;
          event.preventDefault();
        }
      });

      const stopDrag = (event) => {
        if (!dragState || dragState.pointerId !== event.pointerId) return;
        if (dragState.moved) {
          window.setTimeout(() => {
            suppressMenuClick = false;
          }, 80);
        }
        menu.classList.remove("is-drag-scrolling");
        if (dragState.captured) {
          menu.releasePointerCapture?.(event.pointerId);
        }
        dragState = null;
      };

      menu.addEventListener("pointerup", stopDrag);
      menu.addEventListener("pointercancel", stopDrag);
      menu.addEventListener("click", (event) => {
        if (!suppressMenuClick) return;
        event.preventDefault();
        event.stopPropagation();
        suppressMenuClick = false;
      }, true);
    }

    function setSettingsOpen(open) {
      const toggle = document.getElementById("settingsToggle");
      const menu = document.getElementById("settingsMenu");
      toggle.setAttribute("aria-expanded", String(open));
      menu.hidden = !open;
    }

    function updateThemeSettingLabel() {
      const label = document.getElementById("themeSettingLabel");
      if (!label) return;
      label.textContent = document.body.classList.contains("theme-dark") ? t("darkModeState") : t("lightMode");
    }

    function themeToggleLabelText(theme = null) {
      const selectedTheme = theme || (document.body.classList.contains("theme-dark") ? "dark" : "light");
      return selectedTheme === "dark" ? t("themeDarkName") : t("themeLightName");
    }

    function updateThemeToggleLabel() {
      const label = document.getElementById("themeToggleLabel");
      if (!label) return;
      label.textContent = themeToggleLabelText();
    }

    function updateTimeZoneSettingLabel() {
      const label = document.getElementById("timeZoneSettingLabel");
      const button = document.getElementById("timeZoneSettingButton");
      const currentKey = selectedTimeZoneKey();
      const nextKey = currentKey === "us" ? "korea" : "us";
      const actionText = nextKey === "us" ? t("timeZoneSwitchUs") : t("timeZoneSwitchKorea");
      const currentText = currentKey === "us" ? t("timeZoneCurrentUs") : t("timeZoneCurrentKorea");
      const nextFullText = nextKey === "us" ? t("timeZoneUs") : t("timeZoneKorea");
      const optionText = currentKey === "us" ? t("timeZoneUsOption") : t("timeZoneKoreaOption");
      if (label) {
        label.textContent = optionText;
        label.title = selectedTimeZoneLabel();
      }
      if (button) {
        button.setAttribute("aria-label", `${t("timeZone")}: ${currentText}. ${actionText} (${nextFullText})`);
        button.title = actionText;
      }
    }

    function animateToggleContent(toggle, outgoing, incoming, label, nextLabel, swapState) {
      if (!toggle) {
        swapState();
        return;
      }
      toggle.disabled = true;
      [outgoing, incoming, label].forEach((element) => {
        element?.classList.remove("is-exiting", "is-entering");
      });
      void toggle.offsetWidth;
      outgoing?.classList.add("is-exiting");
      label?.classList.add("is-exiting");
      window.setTimeout(() => {
        swapState();
        if (label) {
          label.textContent = nextLabel;
          label.classList.remove("is-exiting");
          label.classList.add("is-entering");
        }
        incoming?.classList.add("is-entering");
      }, 150);
      window.setTimeout(() => {
        [outgoing, incoming, label].forEach((element) => {
          element?.classList.remove("is-exiting", "is-entering");
        });
        toggle.disabled = false;
      }, 470);
    }

    function updateLanguageText() {
      document.documentElement.lang = state.language;
      document.querySelectorAll("[data-i18n]").forEach((element) => {
        element.textContent = t(element.dataset.i18n);
      });
      document.querySelector(".side-menu")?.setAttribute("aria-label", t("menuLabel"));
      document.getElementById("mobileDrawer")?.setAttribute("aria-label", t("menuLabel"));
      document.getElementById("mobileMenuToggle")?.setAttribute("aria-label", t("openMenu"));
      document.getElementById("drawerClose")?.setAttribute("aria-label", t("closeMenu"));
      document.getElementById("settingsToggle")?.setAttribute("aria-label", t("settings"));
      document.getElementById("scrollTopButton")?.setAttribute("aria-label", t("scrollTop"));
      document.getElementById("scrollTopButton")?.setAttribute("title", t("scrollTop"));
      document.getElementById("searchToggle")?.setAttribute("aria-label", t("metricSearch"));
      document.getElementById("searchToggle")?.setAttribute("title", t("metricSearch"));
      document.getElementById("floatingSearchToggle")?.setAttribute("aria-label", t("metricSearch"));
      document.getElementById("floatingSearchToggle")?.setAttribute("title", t("metricSearch"));
      document.getElementById("signalHistoryToggle")?.setAttribute("aria-label", t("signalHistoryTitle"));
      document.getElementById("signalHistoryToggle")?.setAttribute("title", t("signalHistoryTitle"));
      document.getElementById("signalDrawer")?.setAttribute("aria-label", t("signalHistoryTitle"));
      document.getElementById("signalDrawerSheetHandle")?.setAttribute("aria-label", t("signalHistoryClose"));
      document.getElementById("signalDrawerSheetHandle")?.setAttribute("title", t("signalHistoryClose"));
      document.getElementById("signalDrawerClose")?.setAttribute("aria-label", t("signalHistoryClose"));
      document.getElementById("metricDetailDrawer")?.setAttribute("aria-label", t("metricDetailDrawerTitle"));
      document.getElementById("metricDetailSheetHandle")?.setAttribute("aria-label", t("metricDetailDrawerClose"));
      document.getElementById("metricDetailSheetHandle")?.setAttribute("title", t("metricDetailDrawerClose"));
      document.getElementById("metricDetailDrawerClose")?.setAttribute("aria-label", t("metricDetailDrawerClose"));
      document.getElementById("themeToggle")?.setAttribute("aria-label", t("toggleTheme"));
      document.getElementById("themeToggle")?.setAttribute("title", t("toggleTheme"));
      updateCurrencySettingLabel();
      document.getElementById("noteModalClose")?.setAttribute("aria-label", t("close"));
      const noteModalTitle = document.getElementById("noteModalTitle");
      if (noteModalTitle) noteModalTitle.textContent = t("noteTitle");
      const noteModalText = document.getElementById("noteModalText");
      if (noteModalText) {
        noteModalText.placeholder = t("notePlaceholder");
        noteModalText.maxLength = noteMaxLength;
      }
      const noteSaveButton = document.getElementById("noteSaveButton");
      if (noteSaveButton) noteSaveButton.textContent = t("save");
      const noteCancelButton = document.getElementById("noteCancelButton");
      if (noteCancelButton) noteCancelButton.textContent = t("cancel");
      updateNoteCharCount();
      const noteHistoryTitle = document.getElementById("noteHistoryTitle");
      if (noteHistoryTitle) noteHistoryTitle.textContent = t("noteHistory");
      if (!document.getElementById("noteModal")?.hidden && state.activeNoteMetricId) {
        renderNoteHistory(metricById(state.activeNoteMetricId));
      }
      const languageLabel = document.getElementById("languageSettingLabel");
      if (languageLabel) languageLabel.textContent = t(state.language === "ko" ? "languageKorean" : "languageEnglish");
      updateThemeSettingLabel();
      updateAnalyticsConsentSettingLabel();
      updateTimeZoneSettingLabel();
      updateThemeToggleLabel();
      updateCurrencyButton();
      updateCountryFilterControl();
      updateLastUpdatedInline();
      renderMetricSearchHost();
    }

    function updateAnalyticsConsentSettingLabel() {
      const label = document.getElementById("analyticsConsentSettingLabel");
      if (!label) return;
      const enabled = localStorage.getItem("marketbrief.analytics-consent") === "accepted";
      label.textContent = t(enabled ? "analyticsEnabled" : "analyticsDisabled");
    }

    function setLanguage(language) {
      state.language = language === "en" ? "en" : "ko";
      localStorage.setItem("dashboard-language", state.language);
      updateLanguageText();
      document.dispatchEvent(new Event("marketbrief-language-change"));
      renderFilters();
      renderDailyUpdates();
      renderIndustries();
      if (state.activeMetricDetailId) renderMetricDetailDrawer(state.activeMetricDetailId);
    }

    function initLanguage() {
      state.language = localStorage.getItem("dashboard-language") === "en" ? "en" : "ko";
      updateLanguageText();
    }

    function applyTimeZone(timeZone) {
      state.timeZone = timeZone === timeZoneOptions.us ? timeZoneOptions.us : timeZoneOptions.korea;
      localStorage.setItem("dashboard-timezone", state.timeZone);
      updateTimeZoneSettingLabel();
      updateLastUpdatedInline();
      if (document.body.classList.contains("signal-drawer-open")) renderSignalDrawer();
      if (document.body.classList.contains("offline-fallback")) showOfflineBanner(true);
      if (state.activeMetricDetailId) renderMetricDetailDrawer(state.activeMetricDetailId);
    }

    function toggleTimeZone() {
      applyTimeZone(state.timeZone === timeZoneOptions.korea ? timeZoneOptions.us : timeZoneOptions.korea);
      renderDailyUpdates();
      renderIndustries();
    }

    function initTimeZone() {
      const saved = localStorage.getItem("dashboard-timezone");
      applyTimeZone(saved === timeZoneOptions.us ? timeZoneOptions.us : timeZoneOptions.korea);
    }

    function updateReorderControls() {
      document.querySelector(".sidebar")?.classList.toggle("is-reordering", state.isReordering);
      document.getElementById("reorderActions").hidden = !state.isReordering;
    }

    function startMenuReorder() {
      if (state.navRoot !== "industry") {
        state.navRoot = "industry";
      }
      state.isReordering = true;
      state.draftIndustryOrder = visibleIndustries();
      setSettingsOpen(false);
      updateReorderControls();
      renderFilters();
    }

    function cancelMenuReorder() {
      state.isReordering = false;
      state.draftIndustryOrder = null;
      updateReorderControls();
      renderFilters();
    }

    function saveMenuReorder() {
      const order = currentMenuOrder();
      localStorage.setItem("dashboard-industry-order", JSON.stringify(order));
      state.isReordering = false;
      state.draftIndustryOrder = null;
      updateReorderControls();
      renderFilters();
      renderIndustries();
    }

    function initSettings() {
      const settings = document.getElementById("menuSettings");
      const toggle = document.getElementById("settingsToggle");
      toggle.addEventListener("click", () => {
        setSettingsOpen(toggle.getAttribute("aria-expanded") !== "true");
      });
      document.addEventListener("click", (event) => {
        if (!settings.contains(event.target)) setSettingsOpen(false);
      });
      document.querySelector('[data-setting-action="theme"]').addEventListener("click", () => {
        animateThemeToggle(document.body.classList.contains("theme-dark") ? "light" : "dark");
      });
      document.querySelector('[data-setting-action="currency"]').addEventListener("click", () => {
        animateCurrencyToggle(state.currency === "usd" ? "krw" : "usd");
      });
      document.querySelector('[data-setting-action="language"]').addEventListener("click", () => {
        setLanguage(state.language === "ko" ? "en" : "ko");
      });
      document.querySelector('[data-setting-action="timezone"]').addEventListener("click", toggleTimeZone);
      document.querySelector('[data-setting-action="reorder"]').addEventListener("click", startMenuReorder);
      document.querySelector('[data-setting-action="notes-export"]').addEventListener("click", exportMetricNotes);
      document.querySelector('[data-setting-action="notes-import"]').addEventListener("click", () => {
        document.getElementById("notesImportInput")?.click();
      });
      document.getElementById("reorderCancel").addEventListener("click", cancelMenuReorder);
      document.getElementById("reorderSave").addEventListener("click", saveMenuReorder);
      updateReorderControls();
    }

    function applyTheme(theme, options = {}) {
      const isDark = theme === "dark";
      document.body.classList.toggle("theme-dark", isDark);
      localStorage.setItem("dashboard-theme", isDark ? "dark" : "light");
      updateThemeSettingLabel();
      if (options.updateToggleLabel !== false) updateThemeToggleLabel();
    }

    function animateThemeToggle(nextTheme) {
      const toggle = document.getElementById("themeToggle");
      const isDark = document.body.classList.contains("theme-dark");
      const outgoing = toggle.querySelector(isDark ? ".theme-icon-moon" : ".theme-icon-sun");
      const incoming = toggle.querySelector(isDark ? ".theme-icon-sun" : ".theme-icon-moon");
      const label = document.getElementById("themeToggleLabel");
      animateToggleContent(toggle, outgoing, incoming, label, themeToggleLabelText(nextTheme), () => {
        applyTheme(nextTheme, { updateToggleLabel: false });
      });
    }

    function initTheme() {
      const saved = localStorage.getItem("dashboard-theme");
      const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      applyTheme(saved || (prefersDark ? "dark" : "light"));
      requestAnimationFrame(() => document.body.classList.add("theme-ready"));
      document.getElementById("themeToggle").addEventListener("click", () => {
        animateThemeToggle(document.body.classList.contains("theme-dark") ? "light" : "dark");
      });
    }

    function currencyToggleLabelText(currency = state.currency) {
      return currency === "krw" ? t("currencyKrwName") : t("currencyUsdName");
    }

    function updateCurrencySettingLabel() {
      const label = document.getElementById("currencySettingLabel");
      if (label) label.textContent = currencyToggleLabelText();
    }

    function updateCurrencyButton(options = {}) {
      const toggle = document.getElementById("currencyToggle");
      if (!toggle) return;
      const isKrw = state.currency === "krw";
      toggle.setAttribute("aria-label", isKrw ? t("showUsd") : t("showKrw"));
      toggle.setAttribute("title", isKrw ? t("showUsd") : t("showKrw"));
      const label = document.getElementById("currencyToggleLabel");
      if (label && options.updateLabel !== false) label.textContent = currencyToggleLabelText();
    }

    function applyCurrency(currency, options = {}) {
      state.currency = currency === "krw" ? "krw" : "usd";
      document.body.classList.toggle("currency-krw", state.currency === "krw");
      document.body.classList.toggle("currency-usd", state.currency === "usd");
      localStorage.setItem("dashboard-currency", state.currency);
      updateCurrencyButton(options);
      updateCurrencySettingLabel();
    }

    function animateCurrencyToggle(nextCurrency) {
      const toggle = document.getElementById("currencyToggle");
      const isKrw = state.currency === "krw";
      const outgoing = toggle.querySelector(isKrw ? ".currency-icon-won" : ".currency-icon-dollar");
      const incoming = toggle.querySelector(isKrw ? ".currency-icon-dollar" : ".currency-icon-won");
      const label = document.getElementById("currencyToggleLabel");
      animateToggleContent(toggle, outgoing, incoming, label, currencyToggleLabelText(nextCurrency), () => {
        applyCurrency(nextCurrency, { updateLabel: false });
        renderDailyUpdates();
        renderIndustries();
      });
    }

    function initCurrency() {
      applyCurrency(localStorage.getItem("dashboard-currency") === "krw" ? "krw" : "usd");
      document.getElementById("currencyToggle").addEventListener("click", () => {
        animateCurrencyToggle(state.currency === "usd" ? "krw" : "usd");
      });
    }

    function initScrollTopButton() {
      document.getElementById("scrollTopButton")?.addEventListener("click", () => {
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
      updateScrollTopButtonVisibility();
    }

    function updateScrollTopButtonVisibility() {
      const revealAt = Math.max(280, window.innerHeight * 0.35);
      document.body.classList.toggle("show-scroll-top", window.scrollY > revealAt);
    }

    function updateFloatingSearchButtonVisibility() {
      const topbar = document.querySelector(".topbar");
      const hiddenByScroll = topbar ? topbar.getBoundingClientRect().bottom <= 0 : window.scrollY > 160;
      const shouldShow = hiddenByScroll && !state.searchActive && !mobileDrawerQuery.matches;
      document.body.classList.toggle("show-floating-search", shouldShow);
    }

    function setDrawerOpen(open) {
      const drawer = document.getElementById("mobileDrawer");
      const toggle = document.getElementById("mobileMenuToggle");
      const backdrop = document.getElementById("drawerBackdrop");
      if (!drawer || !toggle || !backdrop) return;
      const shouldOpen = Boolean(open && mobileDrawerQuery.matches);
      document.body.classList.toggle("drawer-open", shouldOpen);
      toggle.setAttribute("aria-expanded", String(shouldOpen));
      drawer.setAttribute("aria-hidden", String(mobileDrawerQuery.matches && !shouldOpen));
      backdrop.hidden = !shouldOpen;
      if (shouldOpen) {
        document.getElementById("drawerClose")?.focus({ preventScroll: true });
      }
    }

    function closeDrawerOnMobile() {
      if (mobileDrawerQuery.matches) setDrawerOpen(false);
    }

    function signalEvents() {
      const events = Array.isArray(state.signalLog?.events) ? state.signalLog.events : [];
      return [...events].sort((a, b) => String(b.observed_at || b.ts || "").localeCompare(String(a.observed_at || a.ts || "")));
    }

    function signalEventKey(event) {
      return [event?.ts || event?.observed_at || "", event?.rule_key || "", event?.direction || "", event?.metric_id || ""].join("|");
    }

    function activeSignalEvents() {
      const latest = new Map();
      signalEvents().forEach((event) => {
        if (!latest.has(event.rule_key)) latest.set(event.rule_key, event);
      });
      return [...latest.values()].filter((event) => event.direction === "triggered");
    }

    function signalFilterKeys() {
      const keys = [...new Set(signalEvents().map((event) => event.metric_name || event.rule_key).filter(Boolean))];
      return ["current", "all", "triggered", ...keys.slice(0, 10)];
    }

    function localizedSignalMetricName(event) {
      if (!event) return "";
      if (event.metric_id) return localizedMetricName(event.metric_id, event.metric_name || event.rule_key || "");
      return state.language === "en" ? englishMetricName(event.metric_name || event.rule_key || "") : (event.metric_name || event.rule_key || "");
    }

    function localizedSignalMessage(event) {
      if (!event?.message) return "";
      return state.language === "en" ? localizedText(event.message) : event.message;
    }

    function signalFilterLabel(key) {
      if (key === "current") return t("signalCurrent");
      if (key === "all") return t("signalAll");
      if (key === "triggered") return t("signalTriggeredOnly");
      const event = signalEvents().find((item) => item.metric_name === key || item.rule_key === key);
      return event ? localizedSignalMetricName(event) : localizedText(key);
    }

    function signalEventMatchesFilter(event) {
      if (state.signalFilter === "current") return false;
      if (state.signalFilter === "all") return true;
      if (state.signalFilter === "triggered") return event.direction === "triggered";
      return event.metric_name === state.signalFilter || event.rule_key === state.signalFilter;
    }

    function signalEventDateTimeText(event) {
      const source = event.ts || event.observed_at || "";
      return timeOnlyText(source) ? dateTimeText(source) : dateText(event.observed_at || source);
    }

    function signalEventRelativeTimeText(event) {
      const source = event.ts || event.observed_at || "";
      const normalizedSource = normalizedDateTimeSource(source);
      const date = new Date(normalizedSource);
      if (!normalizedSource || Number.isNaN(date.getTime())) return signalEventDateTimeText(event);
      const diffMs = date.getTime() - Date.now();
      const absoluteMs = Math.abs(diffMs);
      if (absoluteMs < 60_000) return state.language === "en" ? "Just now" : "방금 전";
      let unit = "minute";
      let divisor = 60_000;
      if (absoluteMs >= 365 * 86_400_000) {
        unit = "year";
        divisor = 365 * 86_400_000;
      } else if (absoluteMs >= 30 * 86_400_000) {
        unit = "month";
        divisor = 30 * 86_400_000;
      } else if (absoluteMs >= 86_400_000) {
        unit = "day";
        divisor = 86_400_000;
      } else if (absoluteMs >= 3_600_000) {
        unit = "hour";
        divisor = 3_600_000;
      }
      const amount = Math.max(1, Math.round(absoluteMs / divisor));
      const signedAmount = diffMs < 0 ? -amount : amount;
      return new Intl.RelativeTimeFormat(state.language === "en" ? "en" : "ko", { numeric: "always" }).format(signedAmount, unit);
    }

    function signalEventValueMarkup(event) {
      const metric = metricById(event.metric_id);
      const currentValue = metric?.display_value ?? metric?.value ?? event.display_value ?? event.value ?? "";
      const threshold = event.threshold_label || "";
      return `<div class="signal-card-value-line">
        <span class="signal-card-value-main is-current">${escapeHtml(localizedValueLabel(currentValue))}</span>
        ${signalEventChangeMarkup(event)}
        ${threshold ? `<span class="signal-card-threshold">${escapeHtml(threshold)}</span>` : ""}
      </div>`;
    }

    function signalEventChangeMarkup(event) {
      const metric = metricById(event.metric_id);
      const metricChange = metric ? displayMetricChange(metric) : "";
      const metricChangePct = metric?.change_pct_label || "";
      const value = typeof metric?.change_pct === "number" && Number.isFinite(metric.change_pct) ? metric.change_pct : 0;
      const label = [metricChange, metricChangePct].filter(Boolean).join(" · ");
      return label ? `<span class="signal-card-value-change ${directionClass(value)}">(${escapeHtml(label)})</span>` : "";
    }

    function localizedSignalContextLabel(key) {
      const labels = state.language === "en"
        ? { KS11: "KOSPI", GSPC: "S&P 500", USDKRW: "USD/KRW" }
        : { KS11: "코스피", GSPC: "S&P 500", USDKRW: "원/달러" };
      return labels[key] || key;
    }

    function signalEntryMarkup(event, isActive = false) {
      const triggered = event.direction === "triggered";
      const context = event.context || {};
      const contextMarkup = Object.entries(context)
        .map(([key, value]) => `<span class="signal-card-context-item">${escapeHtml(localizedSignalContextLabel(key))} ${escapeHtml(numberText(Number(value)))}</span>`)
        .join("");
      const title = localizedSignalMetricName(event) || t("metric");
      const statusText = triggered ? t("signalTriggered") : t("signalCleared");
      const source = event.ts || event.observed_at || "";
      return `<button class="signal-card-primary" type="button" data-signal-metric="${escapeHtml(event.metric_id || "")}">
          <div class="signal-card-header">
            <span class="signal-status-circle ${isActive ? "is-active" : ""}" role="img" aria-label="${escapeHtml(statusText)}"></span>
            <div class="signal-card-heading">
              <span class="signal-card-title">${escapeHtml(title)}</span>
              <time class="signal-card-time" datetime="${escapeHtml(source)}" title="${escapeHtml(signalEventDateTimeText(event))}">${escapeHtml(signalEventRelativeTimeText(event))}</time>
            </div>
          </div>
          <div class="signal-card-content">
          ${signalEventValueMarkup(event)}
            ${event.message ? `<p class="signal-card-message">${escapeHtml(localizedSignalMessage(event))}</p>` : ""}
          </div>
        </button>
        ${contextMarkup ? `<div class="signal-card-context">${contextMarkup}</div>` : ""}`;
    }

    function signalCardMarkup(event, isActive = false) {
      const triggered = event.direction === "triggered";
      return `<article class="signal-card ${triggered ? "is-triggered" : ""} ${isActive ? "is-active" : ""} ${event.backfilled ? "is-backfilled" : ""}">
        ${signalEntryMarkup(event, isActive)}
      </article>`;
    }

    function signalHistoryItemMarkup(event, isActive = false) {
      const triggered = event.direction === "triggered";
      return `<article class="signal-history-item ${triggered ? "is-triggered" : ""} ${isActive ? "is-active" : ""} ${event.backfilled ? "is-backfilled" : ""}">
        ${signalEntryMarkup(event, isActive)}
      </article>`;
    }

    function renderSignalDrawer() {
      const body = document.getElementById("signalDrawerBody");
      if (!body) return;
      const active = activeSignalEvents();
      const showingCurrent = state.signalFilter === "current";
      const matchingEvents = showingCurrent ? [] : signalEvents().filter(signalEventMatchesFilter);
      const totalPages = Math.max(1, Math.ceil(matchingEvents.length / signalHistoryPageSize));
      state.signalHistoryPage = Math.max(0, Math.min(state.signalHistoryPage, totalPages - 1));
      const pageStart = state.signalHistoryPage * signalHistoryPageSize;
      const filtered = matchingEvents.slice(pageStart, pageStart + signalHistoryPageSize);
      const filters = signalFilterKeys();
      body.innerHTML = `
        <section class="signal-section">
          <div class="signal-filter-row">
            ${filters.map((key) => `<button class="signal-filter-chip" type="button" data-signal-filter="${escapeHtml(key)}" aria-pressed="${state.signalFilter === key}">${escapeHtml(signalFilterLabel(key))}</button>`).join("")}
          </div>
          ${showingCurrent
            ? (active.length ? `<div class="signal-history-list">${active.map((event) => signalHistoryItemMarkup(event, true)).join("")}</div>` : `<div class="empty" style="display:block">${escapeHtml(t("signalCurrentEmpty"))}</div>`)
            : (filtered.length ? `<div class="signal-history-list">${filtered.map(signalHistoryItemMarkup).join("")}</div>
          <nav class="signal-history-pagination" aria-label="${escapeHtml(t("signalHistory"))}">
            <button class="signal-history-page-button" type="button" data-signal-page="-1" ${state.signalHistoryPage === 0 ? "disabled" : ""}>${escapeHtml(t("signalPreviousPage"))}</button>
            <span class="signal-history-page-status">${state.signalHistoryPage + 1} / ${totalPages}</span>
            <button class="signal-history-page-button" type="button" data-signal-page="1" ${state.signalHistoryPage >= totalPages - 1 ? "disabled" : ""}>${escapeHtml(t("signalNextPage"))}</button>
          </nav>` : `<div class="empty" style="display:block">${escapeHtml(t("signalHistoryEmpty"))}</div>`)}
        </section>`;
      body.querySelectorAll("[data-signal-filter]").forEach((button) => {
        button.addEventListener("click", () => {
          state.signalFilter = button.dataset.signalFilter || "current";
          state.signalHistoryPage = 0;
          renderSignalDrawer();
        });
      });
      body.querySelectorAll("[data-signal-page]").forEach((button) => {
        button.addEventListener("click", () => {
          state.signalHistoryPage += Number(button.dataset.signalPage || 0);
          renderSignalDrawer();
        });
      });
      body.querySelectorAll("[data-signal-metric]").forEach((card) => {
        card.addEventListener("click", () => {
          openMetricDetail(card.dataset.signalMetric, { preserveSignal: true });
        });
      });
    }

    function latestSignalTimestamp() {
      return signalEvents()[0]?.ts || signalEvents()[0]?.observed_at || "";
    }

    function updateSignalUnreadDot() {
      const dot = document.getElementById("signalHistoryDot");
      if (!dot) return;
      const lastRead = localStorage.getItem(signalHistoryReadStorageKey) || "";
      const latest = latestSignalTimestamp();
      dot.hidden = !latest || latest <= lastRead;
    }

    function setSignalDrawerOpen(open) {
      const drawer = document.getElementById("signalDrawer");
      const backdrop = document.getElementById("signalDrawerBackdrop");
      const toggle = document.getElementById("signalHistoryToggle");
      if (!drawer || !backdrop || !toggle) return;
      if (open) {
        setDrawerOpen(false);
        setMetricDetailDrawerOpen(false);
      }
      document.body.classList.toggle("signal-drawer-open", Boolean(open));
      drawer.setAttribute("aria-hidden", String(!open));
      toggle.setAttribute("aria-expanded", String(Boolean(open)));
      backdrop.hidden = !open;
      if (open) {
        localStorage.setItem(signalHistoryReadStorageKey, latestSignalTimestamp() || new Date().toISOString());
        updateSignalUnreadDot();
        renderSignalDrawer();
      }
    }

    function initSignalHistory() {
      fetch("data/signal_log.json")
        .then((response) => (response.ok ? response.json() : { events: [] }))
        .then((data) => {
          state.signalLog = data && Array.isArray(data.events) ? data : { events: [] };
          updateSignalUnreadDot();
          renderSignalDrawer();
          if (state.navRoot === "overview") renderDailyUpdates();
        })
        .catch(() => {
          state.signalLog = { events: [] };
          renderSignalDrawer();
          if (state.navRoot === "overview") renderDailyUpdates();
        });
      document.getElementById("signalHistoryToggle")?.addEventListener("click", () => {
        setSignalDrawerOpen(!document.body.classList.contains("signal-drawer-open"));
      });
      document.getElementById("signalDrawerSheetHandle")?.addEventListener("click", () => setSignalDrawerOpen(false));
      document.getElementById("signalDrawerBack")?.addEventListener("click", () => setSignalDrawerOpen(false));
      document.getElementById("signalDrawerClose")?.addEventListener("click", () => setSignalDrawerOpen(false));
      document.getElementById("signalDrawerBackdrop")?.addEventListener("click", () => setSignalDrawerOpen(false));
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setSignalDrawerOpen(false);
      });
    }

    function initMetricDetailDrawer() {
      document.getElementById("metricDetailSheetHandle")?.addEventListener("click", () => setMetricDetailDrawerOpen(false));
      document.getElementById("metricDetailDrawerClose")?.addEventListener("click", () => setMetricDetailDrawerOpen(false));
      document.getElementById("metricDetailDrawerBackdrop")?.addEventListener("click", () => setMetricDetailDrawerOpen(false));
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setMetricDetailDrawerOpen(false);
      });
    }

    function showOfflineBanner(show = true) {
      const banner = document.getElementById("offlineBanner");
      if (!banner) return;
      document.body.classList.toggle("offline-fallback", Boolean(show));
      const label = generatedAtLabel().replace(`${t("lastUpdatedInline")}: `, "");
      banner.textContent = `${t("offlineData")} — ${label} ${t("offlineAsOf")}`;
    }

    function initPwaSupport() {
      if (navigator.onLine === false) showOfflineBanner(true);
      window.addEventListener("online", () => showOfflineBanner(false));
      window.addEventListener("offline", () => showOfflineBanner(true));
      if ("serviceWorker" in navigator && window.location.protocol !== "file:") {
        navigator.serviceWorker.register("service-worker.js", { scope: "./" }).catch(() => {});
        navigator.serviceWorker.addEventListener("message", (event) => {
          if (event.data?.type === "offline-fallback") showOfflineBanner(true);
        });
      }
    }

    function initMobileDrawer() {
      const toggle = document.getElementById("mobileMenuToggle");
      const close = document.getElementById("drawerClose");
      const backdrop = document.getElementById("drawerBackdrop");
      toggle?.addEventListener("click", () => {
        setDrawerOpen(!document.body.classList.contains("drawer-open"));
      });
      close?.addEventListener("click", () => setDrawerOpen(false));
      backdrop?.addEventListener("click", () => setDrawerOpen(false));
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setDrawerOpen(false);
      });
      if (mobileDrawerQuery.addEventListener) {
        mobileDrawerQuery.addEventListener("change", () => setDrawerOpen(false));
      } else if (mobileDrawerQuery.addListener) {
        mobileDrawerQuery.addListener(() => setDrawerOpen(false));
      }
      setDrawerOpen(false);
    }

    function initMetricSearch() {
      buildSearchIndex();
      const toggleSearch = () => {
        if (state.searchActive) {
          closeMetricSearch();
        } else {
          openMetricSearch();
        }
      };
      document.getElementById("searchToggle")?.addEventListener("click", toggleSearch);
      document.getElementById("floatingSearchToggle")?.addEventListener("click", toggleSearch);
      document.addEventListener("click", (event) => {
        if (!state.searchActive || normalizeSearchText(state.searchQuery)) return;
        if (event.target.closest("#metricSearchHost") || event.target.closest("#searchToggle") || event.target.closest("#floatingSearchToggle")) return;
        closeMetricSearch();
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "/" && !state.searchActive && !isTypingTarget(event.target)) {
          event.preventDefault();
          openMetricSearch();
          return;
        }
        if (!state.searchActive) return;
        if (event.key === "ArrowDown") {
          event.preventDefault();
          moveSearchSelection(1);
          return;
        }
        if (event.key === "ArrowUp") {
          event.preventDefault();
          moveSearchSelection(-1);
          return;
        }
        if (event.key === "Enter" && state.searchResults.length) {
          event.preventDefault();
          openSelectedSearchResult();
          return;
        }
        if (event.key === "Escape") {
          closeMetricSearch();
        }
      });
      if (window.visualViewport) {
        window.visualViewport.addEventListener("resize", updateSearchViewportOffset);
        window.visualViewport.addEventListener("scroll", updateSearchViewportOffset);
      }
      updateFloatingSearchButtonVisibility();
    }

    function updateActiveFromScroll() {
      if (state.navRoot === "market") {
        const sections = [...document.querySelectorAll("[data-market-section]")];
        if (!sections.length) return;
        const anchor = Math.min(120, window.innerHeight * 0.22);
        let current = sections[0];
        const scrollRoot = document.scrollingElement || document.documentElement;
        const atPageEnd = scrollRoot.scrollTop + window.innerHeight >= scrollRoot.scrollHeight - 4;
        for (const section of sections) {
          if (section.getBoundingClientRect().top <= anchor) {
            current = section;
          } else {
            break;
          }
        }
        if (atPageEnd) current = sections[sections.length - 1];
        setActiveMarketCategory(current.dataset.marketCategory || defaultMarketCategory, { updateHash: false });
        return;
      }
      if (state.navRoot !== "industry") return;
      const sections = [...document.querySelectorAll("[data-industry-section]")];
      if (!sections.length) return;
      const anchor = window.innerHeight * 0.5;
      let current = sections[0];
      for (const section of sections) {
        if (section.getBoundingClientRect().top <= anchor) {
          current = section;
        } else {
          break;
        }
      }
      let currentDepth = "";
      if (current.dataset.industryName === "반도체") {
        for (const section of current.querySelectorAll("[data-depth-section]")) {
          if (section.getBoundingClientRect().top <= anchor) {
            currentDepth = section.dataset.depthName || "";
          } else {
            break;
          }
        }
      }
      setActiveIndustry(current.dataset.industryName, currentDepth, { updateHash: false });
    }

    function onScrollSpy() {
      if (scrollSpyFrame) return;
      scrollSpyFrame = requestAnimationFrame(() => {
        scrollSpyFrame = 0;
        updateScrollTopButtonVisibility();
        updateFloatingSearchButtonVisibility();
        updateActiveFromScroll();
      });
    }

    let resizeRenderFrame = 0;
    let lastDashboardViewportWidth = window.innerWidth;
    function onDashboardResize() {
      onScrollSpy();
      updateFloatingSearchButtonVisibility();
      scheduleBranchLineUpdate();
      const viewportWidth = window.innerWidth;
      if (viewportWidth === lastDashboardViewportWidth) return;
      lastDashboardViewportWidth = viewportWidth;
      if (resizeRenderFrame) return;
      resizeRenderFrame = requestAnimationFrame(() => {
        resizeRenderFrame = 0;
        renderIndustries();
      });
    }

    window.addEventListener("scroll", onScrollSpy, { passive: true });
    window.addEventListener("resize", onDashboardResize);
    document.addEventListener("click", (event) => {
      if (event.target.closest(".detail-point-hit")) return;
      document.querySelectorAll(".detail-chart").forEach((chart) => hideDetailTooltip(chart, true));
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        document.querySelectorAll(".detail-chart").forEach((chart) => hideDetailTooltip(chart, true));
      }
    });

    function render() {
      renderFilters();
      renderDailyUpdates();
      renderIndustries();
    }

    function initHashRouting() {
      window.addEventListener("hashchange", () => {
        applyHashRoute(parseDashboardHash());
      });
      const route = parseDashboardHash();
      if (route?.type === "detail") {
        requestAnimationFrame(() => openMetricDetail(route.metric.id, { updateHash: false, scroll: true }));
      }
      if (route?.type === "future" && route.techId) {
        requestAnimationFrame(() => document.getElementById(futureCardId(route.techId))?.scrollIntoView({ block: "center" }));
      }
    }

    initLanguage();
    initTimeZone();
    initSettings();
    initTheme();
    initCurrency();
    initCountryFilterPlacement();
    initCountryFilter();
    initFavoriteMetrics();
    initMetricNotes();
    initNavState();
    initMetricSearch();
    initScrollTopButton();
    initMobileDrawer();
    initSignalHistory();
    initMetricDetailDrawer();
    initPwaSupport();
    render();
    initHashRouting();
    loadBriefingIndex();
