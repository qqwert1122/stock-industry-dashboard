    function metricById(metricId) {
      return (DASHBOARD_DATA.metrics || []).find((metric) => metric.id === metricId) || null;
    }

    function metricHashKey(metric) {
      return String(metric?.history_key || metric?.id || "");
    }

    function metricByHashKey(key) {
      const decoded = String(key || "");
      return (DASHBOARD_DATA.metrics || []).find((metric) => (
        metricHashKey(metric) === decoded || String(metric.id || "") === decoded
      ));
    }

    function hashSegment(value) {
      return encodeURIComponent(String(value || ""));
    }

    function unhashSegment(value) {
      try {
        return decodeURIComponent(String(value || ""));
      } catch (_error) {
        return String(value || "");
      }
    }

    function parseDashboardHash(hash = window.location.hash) {
      const clean = String(hash || "").replace(/^#/, "");
      if (!clean) return null;
      const [kind, ...rest] = clean.split("/");
      if (kind === "o" || kind === "overview") {
        return { type: "overview" };
      }
      if (kind === "m") {
        const category = unhashSegment(rest.join("/") || defaultMarketCategory);
        if (category === overviewCategoryKey) return { type: "overview" };
        return marketCategories.some((item) => item.key === category)
          ? { type: "market", category }
          : null;
      }
      if (kind === "i") {
        const industry = unhashSegment(rest[0] || "");
        const depth = unhashSegment(rest.slice(1).join("/") || "");
        return industry ? { type: "industry", industry, depth } : null;
      }
      if (kind === "future" || kind === "f") {
        const first = unhashSegment(rest[0] || "");
        if (first === "track-record") {
          return { type: "future", view: "track-record", subject: unhashSegment(rest[1] || "") };
        }
        const techId = unhashSegment(rest.join("/") || "");
        return { type: "future", view: "timeline", techId };
      }
      if (kind === "d") {
        const key = unhashSegment(rest.join("/"));
        const metric = metricByHashKey(key);
        return metric ? { type: "detail", metric } : null;
      }
      return null;
    }

    function currentNavHash() {
      if (state.navRoot === "overview") return "#o";
      if (state.navRoot === "market") return `#m/${hashSegment(state.marketCategory || defaultMarketCategory)}`;
      if (state.navRoot === "industry" && state.activeIndustry) {
        const depth = state.activeDepth ? `/${hashSegment(state.activeDepth)}` : "";
        return `#i/${hashSegment(state.activeIndustry)}${depth}`;
      }
      if (state.navRoot === "future") {
        if (state.futureView === "track-record") {
          return state.trackRecordSubject
            ? `#future/track-record/${hashSegment(state.trackRecordSubject)}`
            : "#future/track-record";
        }
        return state.activeFutureId ? `#future/${hashSegment(state.activeFutureId)}` : "#future";
      }
      return "";
    }

    function writeDashboardHash(hash, mode = "push") {
      if (state.applyingHashRoute || !hash) return;
      if (window.location.hash === hash) return;
      const method = mode === "replace" ? "replaceState" : "pushState";
      window.history?.[method]?.(null, "", hash);
    }

    function selectNavForMetric(metric) {
      if (!metric) return;
      if (isPrimaryMarketMetric(metric) || metric.market_category) {
        if ((metric.market_category || metricMarketCategories(metric)[0]) === overviewCategoryKey) {
          state.navRoot = "overview";
          return;
        }
        state.navRoot = "market";
        state.marketCategory = metric.market_category || metricMarketCategories(metric)[0] || defaultMarketCategory;
        return;
      }
      state.navRoot = "industry";
      state.activeIndustry = metric.industry || state.activeIndustry;
      state.activeDepth = metric.industry === "반도체" ? (metric.depth || "") : "";
    }

    function localizedMarketCategory(category) {
      if (category === overviewCategoryKey) return t("marketOverview");
      const item = marketCategories.find((entry) => entry.key === category);
      return item ? t(item.labelKey) : category;
    }

    function normalizeSearchText(value) {
      return String(value || "").toLocaleLowerCase().replace(/\s+/g, " ").trim();
    }

    const hangulInitials = ["ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"];

    function initialSearchText(value) {
      return Array.from(String(value || "")).map((char) => {
        const code = char.charCodeAt(0);
        if (code < 0xac00 || code > 0xd7a3) return char;
        return hangulInitials[Math.floor((code - 0xac00) / 588)] || char;
      }).join("").toLocaleLowerCase();
    }

    function isInitialToken(token) {
      return /^[ㄱ-ㅎ]+$/.test(String(token || ""));
    }

    function compactSearchText(value) {
      return normalizeSearchText(value).replace(/[\s/._·:-]+/g, "");
    }

    function isSubsequence(needle, haystack) {
      const target = compactSearchText(needle);
      const text = compactSearchText(haystack);
      if (!target) return false;
      let index = 0;
      for (const char of text) {
        if (char === target[index]) index += 1;
        if (index >= target.length) return true;
      }
      return false;
    }

    function searchAliasEntries() {
      const aliases = DASHBOARD_DATA.search_aliases || {};
      return Object.entries(aliases).flatMap(([name, values]) => {
        const list = Array.isArray(values) ? values : [values];
        return [{ name, alias: name }, ...list.map((alias) => ({ name, alias }))];
      });
    }

    function aliasesForMetric(metric, fields) {
      const joined = fields.join(" ");
      return searchAliasEntries()
        .filter((entry) => {
          const name = normalizeSearchText(entry.name);
          return name && (joined.includes(name) || name.includes(normalizeSearchText(metric.name)));
        })
        .map((entry) => normalizeSearchText(entry.alias))
        .filter(Boolean);
    }

    function metricSearchFields(metric) {
      return [
        metric.name,
        metric.name_en,
        metric.industry,
        metric.industry_en,
        metric.market_category,
        ...(Array.isArray(metric.also_market_category) ? metric.also_market_category : []),
        metric.depth,
        metric.depth_en,
        metric.group,
        metric.group_en,
        metric.source,
        metric.unit,
        metric.unit_en,
        metricNoteText(metric)
      ].filter(Boolean).map(normalizeSearchText);
    }

    function buildSearchIndex() {
      state.searchIndex = (DASHBOARD_DATA.metrics || []).map((metric, order) => {
        const fields = metricSearchFields(metric);
        const aliases = aliasesForMetric(metric, fields);
        const allFields = [...fields, ...aliases];
        return {
          metric,
          order,
          name: normalizeSearchText(metric.name),
          aliases,
          fields: allFields,
          text: allFields.join(" "),
          initialsText: allFields.map(initialSearchText).join(" ")
        };
      });
    }

    function recentMetricIds() {
      try {
        const parsed = JSON.parse(localStorage.getItem(recentMetricStorageKey) || "[]");
        return Array.isArray(parsed) ? parsed.map(String).slice(0, 10) : [];
      } catch (_error) {
        return [];
      }
    }

    function rememberMetricVisit(metricId) {
      if (!metricId) return;
      const next = [String(metricId), ...recentMetricIds().filter((id) => id !== String(metricId))].slice(0, 10);
      localStorage.setItem(recentMetricStorageKey, JSON.stringify(next));
    }

    function recentSearches() {
      try {
        const parsed = JSON.parse(localStorage.getItem(recentSearchStorageKey) || "[]");
        return Array.isArray(parsed) ? parsed.map(String).filter(Boolean).slice(0, 5) : [];
      } catch (_error) {
        return [];
      }
    }

    function rememberSearchQuery(query) {
      const normalized = normalizeSearchText(query);
      if (normalized.length < 2) return;
      const next = [normalized, ...recentSearches().filter((item) => item !== normalized)].slice(0, 5);
      localStorage.setItem(recentSearchStorageKey, JSON.stringify(next));
    }

    function tokenMatchesEntry(entry, token, fuzzy = false) {
      if (!token) return false;
      if (isInitialToken(token)) return entry.initialsText.includes(token);
      if (entry.text.includes(token)) return true;
      return fuzzy && (isSubsequence(token, entry.text) || isSubsequence(initialSearchText(token), entry.initialsText));
    }

    function searchRank(entry, query, fuzzy = false) {
      if (entry.name === query) return 0;
      if (entry.name.startsWith(query)) return 1;
      if (entry.name.includes(query)) return 2;
      if (entry.aliases.some((alias) => alias.includes(query))) return 3;
      if (fuzzy) return 5;
      return 4;
    }

    function searchBoost(entry) {
      let boost = 0;
      if (isFavoriteMetric(entry.metric.id)) boost -= 2;
      if (recentMetricIds().includes(entry.metric.id)) boost -= 1;
      return boost;
    }

    function runMetricSearch(query) {
      const normalized = normalizeSearchText(query);
      const tokens = normalized.split(" ").filter(Boolean);
      if (!tokens.length) return [];
      const exact = state.searchIndex.filter((entry) => tokens.every((token) => tokenMatchesEntry(entry, token, false)));
      const fuzzy = exact.length ? [] : state.searchIndex.filter((entry) => tokens.every((token) => tokenMatchesEntry(entry, token, true)));
      const matches = exact.length ? exact : fuzzy;
      state.searchFuzzyMode = !exact.length && fuzzy.length > 0;
      state.searchResultMeta = new Map(matches.map((entry) => [entry.metric.id, { fuzzy: state.searchFuzzyMode }]));
      return matches
        .sort((a, b) => (
          searchRank(a, normalized, state.searchFuzzyMode) - searchRank(b, normalized, state.searchFuzzyMode)
          || searchBoost(a) - searchBoost(b)
          || a.order - b.order
        ))
        .map((entry) => entry.metric);
    }

    const countryMeta = {
      ALL: { asset: "global", ko: "전체", en: "All" },
      KR: { asset: "kr", ko: "한국", en: "Korea" },
      US: { asset: "us", ko: "미국", en: "United States" },
      JP: { asset: "jp", ko: "일본", en: "Japan" },
      CN: { asset: "cn", ko: "중국", en: "China" },
      EU: { asset: "eu", ko: "유럽", en: "Europe" },
      TW: { asset: "tw", ko: "대만", en: "Taiwan" },
      NL: { asset: "nl", ko: "네덜란드", en: "Netherlands" },
      APAC: { asset: "apac", ko: "아시아태평양", en: "Asia Pacific" },
      AMERICAS: { asset: "americas", ko: "미주", en: "Americas" },
      GLOBAL: { asset: "global", ko: "글로벌", en: "Global" }
    };

    function normalizedCountryCode(value) {
      const code = String(value || "").trim().toUpperCase();
      return countryMeta[code] ? code : "GLOBAL";
    }

    function metricCountryCode(metric) {
      if (metric?.country) return normalizedCountryCode(metric.country);
      const text = `${metric?.name || ""} ${metric?.source || ""} ${metric?.history_key || ""}`;
      const lowered = text.toLowerCase();
      if (/worldwide|global|world bank|글로벌|전세계/.test(lowered)) return "GLOBAL";
      if (/asia pacific|아시아 태평양/.test(lowered)) return "APAC";
      if (/americas|미주/.test(lowered)) return "AMERICAS";
      if (/bdi|철광석|구리|알루미늄|리튬 가격|usdt\/usdc|비트코인|김치프리미엄|Phase 3 임상/i.test(text)) return "GLOBAL";
      if (/한국|코스피|코스닥|원\/달러|VKOSPI|\.KS|\.KQ|KRX|KOSIS|ECOS|KOFIA/i.test(text)) return "KR";
      if (/일본|BOJ|엔\/달러|엔\/원|boj-/i.test(text)) return "JP";
      if (/중국|위안|CNY/i.test(text)) return "CN";
      if (/유럽|유로시스템|ECB|유로존|ecb-/i.test(text)) return "EU";
      if (/TSMC|대만/i.test(text)) return "TW";
      if (/ASML|네덜란드/i.test(text)) return "NL";
      if (/미국|S&P|나스닥|다우|VIX|Sahm|GDPNow|CNN|WTI|연준|TGA|역레포|하이일드|FRED|FiscalData|FINRA|openFDA|USAspending|EIA|NREL/i.test(text)) return "US";
      return "GLOBAL";
    }

    function eventCountryCode(event) {
      return normalizedCountryCode(event?.country || "GLOBAL");
    }

    function countryLabel(code) {
      const info = countryMeta[normalizedCountryCode(code)] || countryMeta.GLOBAL;
      return state.language === "en" ? info.en : info.ko;
    }

    function countryFlagMarkup(code) {
      const normalized = normalizedCountryCode(code);
      if (normalized === "ALL" || normalized === "GLOBAL") return "";
      const info = countryMeta[normalized] || countryMeta.GLOBAL;
      return `<img class="country-flag-image" src="assets/country-flags/${info.asset}.svg" alt="">`;
    }

    function countryBadgeMarkup(code, className = "metric-country-badge") {
      const normalized = normalizedCountryCode(code);
      if (normalized === "ALL" || normalized === "GLOBAL") return "";
      const info = countryMeta[normalized] || countryMeta.GLOBAL;
      return `<span class="${className}" title="${escapeHtml(countryLabel(normalized))}">${countryFlagMarkup(normalized)}<span class="metric-country-label">${escapeHtml(countryLabel(normalized))}</span></span>`;
    }

    function matchesCountryFilter(code) {
      return state.countryFilter === "ALL" || normalizedCountryCode(code) === state.countryFilter;
    }

    function countryFilteredMetrics(metrics = DASHBOARD_DATA.metrics || []) {
      return metrics.filter((metric) => matchesCountryFilter(metricCountryCode(metric)));
    }

    function availableCountryCodes() {
      const codes = new Set((DASHBOARD_DATA.metrics || []).map(metricCountryCode));
      const events = Array.isArray(DASHBOARD_DATA.calendar?.events) ? DASHBOARD_DATA.calendar.events : [];
      events.forEach((event) => codes.add(eventCountryCode(event)));
      const preferred = ["KR", "US", "JP", "CN", "EU", "TW", "NL", "APAC", "AMERICAS", "GLOBAL"];
      return ["ALL", ...preferred.filter((code) => codes.has(code)), ...[...codes].filter((code) => !preferred.includes(code)).sort()];
    }

    function updateCountryFilterControl() {
      const label = document.getElementById("countryFilterLabel");
      const menu = document.getElementById("countryFilterMenu");
      const toggle = document.getElementById("countryFilterToggle");
      if (label) label.innerHTML = `${countryFlagMarkup(state.countryFilter)}<span>${escapeHtml(countryLabel(state.countryFilter))}</span>`;
      if (toggle) {
        const accessibleLabel = `${t("countrySelect")}: ${countryLabel(state.countryFilter)}`;
        toggle.setAttribute("aria-label", accessibleLabel);
        toggle.setAttribute("title", accessibleLabel);
      }
      if (menu) {
        menu.innerHTML = availableCountryCodes().map((code) => {
          const selected = state.countryFilter === code;
          const flag = countryFlagMarkup(code);
          return `<button class="country-filter-option${flag ? " has-flag" : ""}" type="button" role="menuitemradio" aria-checked="${selected}" data-country-filter="${code}">${flag}<span>${escapeHtml(countryLabel(code))}</span></button>`;
        }).join("");
        menu.querySelectorAll("[data-country-filter]").forEach((button) => {
          button.addEventListener("click", () => setCountryFilter(button.dataset.countryFilter || "ALL"));
        });
      }
    }

    function setCountryFilterOpen(open) {
      const toggle = document.getElementById("countryFilterToggle");
      const menu = document.getElementById("countryFilterMenu");
      if (!toggle || !menu) return;
      const isOpen = Boolean(open);
      toggle.setAttribute("aria-expanded", String(isOpen));
      menu.hidden = !isOpen;
      const chevron = toggle.querySelector(".country-filter-chevron");
      if (chevron) chevron.className = `fa-solid fa-chevron-${isOpen ? "down" : "right"} country-filter-chevron`;
    }

    function setCountryFilter(code) {
      state.countryFilter = availableCountryCodes().includes(code) ? code : "ALL";
      state.favoritePage = 0;
      localStorage.setItem("dashboard-country-filter", state.countryFilter);
      setCountryFilterOpen(false);
      updateCountryFilterControl();
      renderDailyUpdates();
      renderIndustries();
    }

    function initCountryFilter() {
      const saved = normalizedCountryCode(localStorage.getItem("dashboard-country-filter") || "ALL");
      state.countryFilter = availableCountryCodes().includes(saved) ? saved : "ALL";
      updateCountryFilterControl();
      document.getElementById("countryFilterToggle")?.addEventListener("click", () => {
        const toggle = document.getElementById("countryFilterToggle");
        setCountryFilterOpen(toggle?.getAttribute("aria-expanded") !== "true");
      });
      document.addEventListener("click", (event) => {
        const control = document.getElementById("countryFilterControl");
        if (control && !control.contains(event.target)) setCountryFilterOpen(false);
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setCountryFilterOpen(false);
      });
    }

    function placeCountryFilterControl() {
      const control = document.getElementById("countryFilterControl");
      const settingsMenu = document.getElementById("settingsMenu");
      const topbarActions = document.querySelector(".topbar-actions");
      const themeToggle = document.getElementById("themeToggle");
      if (!control || !settingsMenu || !topbarActions || !themeToggle) return;
      if (window.matchMedia("(max-width: 760px)").matches) {
        const afterCurrency = settingsMenu.querySelector('[data-setting-action="currency"]');
        settingsMenu.insertBefore(control, afterCurrency?.nextSibling || null);
      } else {
        topbarActions.insertBefore(control, themeToggle);
      }
    }

    function initCountryFilterPlacement() {
      const media = window.matchMedia("(max-width: 760px)");
      placeCountryFilterControl();
      if (typeof media.addEventListener === "function") media.addEventListener("change", placeCountryFilterControl);
      else media.addListener(placeCountryFilterControl);
    }

    document.addEventListener("marketbrief-analytics-consent-change", updateAnalyticsConsentSettingLabel);

    function metricMarketCategories(metric) {
      const categories = [];
      if (metric?.market_category) categories.push(metric.market_category);
      if (Array.isArray(metric?.also_market_category)) {
        metric.also_market_category.forEach((item) => {
          if (item && !categories.includes(item)) categories.push(item);
        });
      }
      return categories;
    }

    function isPrimaryMarketMetric(metric) {
      return metric?.section === "market";
    }

    function isIndustryMetric(metric) {
      return !isPrimaryMarketMetric(metric);
    }

    function marketMetricsForCategory(category) {
      return countryFilteredMetrics().filter((metric) => metricMarketCategories(metric).includes(category));
    }

    function saveNavState() {
      localStorage.setItem(navStateStorageKey, JSON.stringify({
        navRoot: state.navRoot,
        marketCategory: state.marketCategory,
        activeIndustry: state.activeIndustry,
        activeDepth: state.activeDepth,
        futureCategory: state.futureCategory,
        futureView: state.futureView,
        activeFutureId: state.activeFutureId,
        trackRecordSubject: state.trackRecordSubject
      }));
    }

    function initNavState() {
      const route = parseDashboardHash();
      if (route) {
        applyHashRoute(route, { renderAfter: false });
        return;
      }
      state.navRoot = "overview";
      state.marketCategory = defaultMarketCategory;
    }

    function applyHashRoute(route = parseDashboardHash(), options = {}) {
      if (!route) return false;
      state.applyingHashRoute = true;
      const routeMarketCategory = route.type === "market" ? (route.category || defaultMarketCategory) : "";
      if (route.type === "overview") {
        state.navRoot = "overview";
        state.marketCategory = defaultMarketCategory;
      } else if (route.type === "market") {
        state.navRoot = "market";
        state.marketCategory = routeMarketCategory;
      } else if (route.type === "industry") {
        state.navRoot = "industry";
        state.activeIndustry = route.industry || "";
        state.activeDepth = route.depth || "";
      } else if (route.type === "future") {
        state.navRoot = "future";
        state.futureCategory = futureAllCategory;
        state.futureView = route.view || "timeline";
        state.activeFutureId = route.techId || "";
        state.trackRecordSubject = route.subject || "";
      } else if (route.type === "detail") {
        selectNavForMetric(route.metric);
      }
      saveNavState();
      if (options.renderAfter !== false) {
        render();
        if (route.type === "market") {
          requestAnimationFrame(() => {
            setActiveMarketCategory(routeMarketCategory, { updateHash: false });
            document.getElementById(marketSectionId(routeMarketCategory))?.scrollIntoView({ block: "start" });
          });
        }
        if (route.type === "detail") {
          requestAnimationFrame(() => openMetricDetail(route.metric.id, { updateHash: false, scroll: true }));
        }
        if (route.type === "future" && route.techId) {
          requestAnimationFrame(() => document.getElementById(futureCardId(route.techId))?.scrollIntoView({ block: "center" }));
        }
      }
      state.applyingHashRoute = false;
      return true;
    }

    let menuTransitionTimer = 0;

    function navRootDepth(root) {
      return root === "overview" || root === "root" ? 0 : 1;
    }

    function animateMenuNavTransition(previousRoot, nextRoot) {
      const menu = document.getElementById("industryFilters");
      if (!menu || previousRoot === nextRoot) return;
      if (window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) return;
      const direction = navRootDepth(nextRoot) > navRootDepth(previousRoot) ? "forward" : "back";
      menu.classList.remove("is-nav-enter-forward", "is-nav-enter-back");
      if (menuTransitionTimer) window.clearTimeout(menuTransitionTimer);
      void menu.offsetWidth;
      menu.classList.add(`is-nav-enter-${direction}`);
      menuTransitionTimer = window.setTimeout(() => {
        menu.classList.remove("is-nav-enter-forward", "is-nav-enter-back");
      }, 320);
    }

    function setNavRoot(root, options = {}) {
      const previousRoot = state.navRoot;
      state.navRoot = root === "root" ? "overview" : root;
      if (state.navRoot === "market" && !state.marketCategory) state.marketCategory = defaultMarketCategory;
      if (root === "industry" && !state.activeIndustry) {
        const industries = visibleIndustries();
        state.activeIndustry = industries[0] || "";
      }
      if (state.navRoot === "future" && !state.futureCategory) state.futureCategory = futureAllCategory;
      if (state.navRoot === "future" && !state.futureView) state.futureView = "timeline";
      saveNavState();
      renderFilters();
      animateMenuNavTransition(previousRoot, state.navRoot);
      renderDailyUpdates();
      renderIndustries();
      if (options.updateHash !== false) writeDashboardHash(currentNavHash(), "push");
    }

    function setActiveMarketCategory(category, options = {}) {
      const nextCategory = category || defaultMarketCategory;
      state.navRoot = "market";
      state.marketCategory = nextCategory;
      saveNavState();
      if (options.updateHash !== false) writeDashboardHash(currentNavHash(), options.hashMode || "push");
      document.querySelectorAll("[data-market-category]").forEach((button) => {
        const active = button.dataset.marketCategory === nextCategory;
        button.setAttribute("aria-pressed", String(active));
        button.setAttribute("aria-current", String(active));
      });
    }

    function setMarketCategory(category, options = {}) {
      if (category === overviewCategoryKey) {
        setNavRoot("overview", options);
        return;
      }
      const nextCategory = category || defaultMarketCategory;
      const targetId = marketSectionId(nextCategory);
      if (state.navRoot !== "market" || !document.getElementById(targetId)) {
        state.navRoot = "market";
        state.marketCategory = nextCategory;
        saveNavState();
        renderFilters();
        renderDailyUpdates();
        renderIndustries();
      }
      setActiveMarketCategory(nextCategory, options);
      closeDrawerOnMobile();
      if (options.scroll !== false) {
        requestAnimationFrame(() => {
          document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      }
    }

    function isSearchFiltering() {
      return state.searchActive && Boolean(normalizeSearchText(state.searchQuery));
    }

    function searchResultIds() {
      return new Set((state.searchResults || []).map((metric) => metric.id));
    }

    function updateSearchSummary() {
      const summary = document.getElementById("metricSearchSummary");
      if (!summary) return;
      const query = normalizeSearchText(state.searchQuery);
      summary.textContent = query
        ? `${t("metricSearchCount")} ${state.searchResults.length}${state.searchFuzzyMode ? ` · ${t("similarResults")}` : ""}`
        : "";
    }

    function renderMetricSearchHost() {
      const host = document.getElementById("metricSearchHost");
      const toggle = document.getElementById("searchToggle");
      const floatingToggle = document.getElementById("floatingSearchToggle");
      if (!host || !toggle) return;
      document.body.classList.toggle("search-active", state.searchActive);
      toggle.setAttribute("aria-pressed", String(state.searchActive));
      floatingToggle?.setAttribute("aria-pressed", String(state.searchActive));
      updateFloatingSearchButtonVisibility();
      host.hidden = !state.searchActive;
      if (!state.searchActive) {
        host.innerHTML = "";
        return;
      }
      host.innerHTML = `<div class="metric-search-box">
        <i class="fa-solid fa-magnifying-glass" aria-hidden="true"></i>
        <input class="metric-search-input" id="metricSearchInput" type="search" autocomplete="off" spellcheck="false"
          value="${escapeHtml(state.searchQuery)}" placeholder="${escapeHtml(t("metricSearchPlaceholder"))}" aria-label="${escapeHtml(t("metricSearch"))}">
        <button class="metric-search-close" id="metricSearchClose" type="button" aria-label="${escapeHtml(t("closeMenu"))}" title="${escapeHtml(t("closeMenu"))}">
          <i class="fa-solid fa-xmark" aria-hidden="true"></i>
        </button>
      </div>
      <div class="metric-search-summary" id="metricSearchSummary"></div>
      `;
      const input = document.getElementById("metricSearchInput");
      input?.addEventListener("input", () => scheduleMetricSearch(input.value));
      document.getElementById("metricSearchClose")?.addEventListener("click", closeMetricSearch);
      updateSearchSummary();
      updateSearchViewportOffset();
    }

    function openMetricSearch() {
      if (!state.searchActive) {
        state.searchRestoreScrollY = window.scrollY;
      }
      state.searchActive = true;
      renderMetricSearchHost();
      window.setTimeout(() => document.getElementById("metricSearchInput")?.focus({ preventScroll: true }), 30);
    }

    function closeMetricSearch() {
      window.clearTimeout(searchDebounceTimer);
      state.searchActive = false;
      state.searchQuery = "";
      state.searchResults = [];
      state.searchResultMeta = new Map();
      state.searchSelectedIndex = -1;
      state.searchFuzzyMode = false;
      renderMetricSearchHost();
      renderDailyUpdates();
      renderIndustries();
      window.requestAnimationFrame(() => window.scrollTo({ top: state.searchRestoreScrollY || 0, behavior: "auto" }));
    }

    function applyMetricSearch(query) {
      state.searchQuery = query;
      state.searchResults = runMetricSearch(query);
      state.searchSelectedIndex = state.searchResults.length ? 0 : -1;
      if (state.searchResults.length) rememberSearchQuery(query);
      if (!normalizeSearchText(query)) {
        state.searchResultMeta = new Map();
        state.searchFuzzyMode = false;
      }
      updateSearchSummary();
      renderDailyUpdates();
      renderIndustries();
    }

    function scheduleMetricSearch(query) {
      state.searchQuery = query;
      window.clearTimeout(searchDebounceTimer);
      searchDebounceTimer = window.setTimeout(() => applyMetricSearch(query), 250);
    }

    function isTypingTarget(target) {
      const tag = String(target?.tagName || "").toLowerCase();
      return tag === "input" || tag === "textarea" || tag === "select" || Boolean(target?.isContentEditable);
    }

    function moveSearchSelection(delta) {
      if (!state.searchResults.length) return;
      const count = state.searchResults.length;
      state.searchSelectedIndex = (state.searchSelectedIndex + delta + count) % count;
      renderDailyUpdates();
      renderIndustries();
      const metricId = state.searchResults[state.searchSelectedIndex]?.id;
      document.querySelector(`[data-metric-id="${metricId}"]`)?.scrollIntoView({ block: "nearest" });
    }

    function openSelectedSearchResult() {
      const metric = state.searchResults[state.searchSelectedIndex] || state.searchResults[0];
      if (!metric) return;
      closeMetricSearch();
      openMetricDetail(metric.id);
    }

    function updateSearchViewportOffset() {
      if (!window.visualViewport) return;
      const offset = Math.max(12, window.innerHeight - window.visualViewport.height - window.visualViewport.offsetTop + 12);
      document.documentElement.style.setProperty("--search-bottom-offset", `${Math.round(offset)}px`);
    }

    function hasHangul(value) {
      return /[가-힣]/.test(String(value || ""));
    }

    function englishFallbackSentence(text) {
      if (/순매수|매수|매도|수급|외국인|개인|기관/.test(text)) {
        return "Tracks investor trading flows and helps show which group is buying or selling the market.";
      }
      if (/공포|탐욕|심리|변동성/.test(text)) {
        return "Shows market sentiment and risk appetite.";
      }
      if (/침체|경기|실업|성장/.test(text)) {
        return "Helps read the economic cycle and recession risk.";
      }
      if (/금리|스프레드|채권|회사채/.test(text)) {
        return "Tracks rates, credit conditions, and funding stress.";
      }
      if (/환율|원\/달러/.test(text)) {
        return "Tracks currency moves that affect exporters, foreign flows, and market liquidity.";
      }
      if (/가격|원자재|유가|철광석|구리|알루미늄|리튬/.test(text)) {
        return "Tracks price movements that affect costs, margins, and demand expectations.";
      }
      if (/판매|매출|수출|CAPEX|투자/.test(text)) {
        return "Tracks demand and investment momentum for the related industry.";
      }
      if (/캘린더|일정|발표|결정|휴장|만기/.test(text)) {
        return "Scheduled market event.";
      }
      return "Market indicator used to track investment conditions.";
    }

    function englishGenericText(value, fallback = "Market indicator") {
      const original = String(value || "");
      if (!original) return "";
      if (!hasHangul(original)) return original;
      if (englishTextFallbacks[original]) return englishTextFallbacks[original];
      if (englishMeaningFallbacks[original]) return englishMeaningFallbacks[original];
      if (englishMetricNameFallbacks[original]) return englishMetricNameFallbacks[original];
      if (englishIndustryFallbacks[original]) return englishIndustryFallbacks[original];
      if (englishGroupFallbacks[original]) return englishGroupFallbacks[original];
      if (englishDepthFallbacks[original]) return englishDepthFallbacks[original];

      const flowMatch = original.match(/^(코스피|코스닥|K200 선물|선물)?\s*(개인|외국인|기관합계|기관|금융투자|보험|투신|사모|은행|기타금융|연기금|기타법인)\s+(20일 누적 순매수|순매수|매수|매도)$/);
      if (flowMatch) {
        const market = flowMatch[1] ? `${englishMarketFallbacks[flowMatch[1]] || flowMatch[1]} ` : "";
        return `${market}${englishInvestorFallbacks[flowMatch[2]] || flowMatch[2]} ${englishFlowMeasureFallbacks[flowMatch[3]] || flowMatch[3]}`.trim();
      }

      const exportMatch = original.match(/^한국 수출 (.+)\(([^)]+)\)$/);
      if (exportMatch) {
        const item = englishGenericText(exportMatch[1], "Export Item");
        return `Korea Exports: ${item} (${exportMatch[2]})`;
      }

      const stockMatch = original.match(/^(.+) 주가$/);
      if (stockMatch) {
        const company = englishGenericText(stockMatch[1], "Company");
        return `${company} Stock Price`;
      }

      const releaseMatch = original.match(/^미국 (.+) 발표$/);
      if (releaseMatch) return `US ${englishGenericText(releaseMatch[1], "Data")} release`;

      let translated = original;
      Object.entries(englishInvestorFallbacks)
        .sort((a, b) => b[0].length - a[0].length)
        .forEach(([source, target]) => {
          translated = translated.replaceAll(source, target);
        });
      Object.entries(englishFlowMeasureFallbacks)
        .sort((a, b) => b[0].length - a[0].length)
        .forEach(([source, target]) => {
          translated = translated.replaceAll(source, target);
        });
      englishPhraseFallbacks
        .sort((a, b) => b[0].length - a[0].length)
        .forEach(([source, target]) => {
          translated = translated.replaceAll(source, target);
        });
      Object.entries(englishMarketFallbacks)
        .sort((a, b) => b[0].length - a[0].length)
        .forEach(([source, target]) => {
          translated = translated.replaceAll(source, target);
        });
      translated = translated
        .replace(/(\d+)일/g, "$1d")
        .replace(/(\d+)년/g, "$1y")
        .replace(/(\d+)개월/g, "$1mo")
        .replace(/에서/g, " in ")
        .replace(/동안/g, " for ")
        .replace(/입니다|합니다|하세요|됩니다|합니다\.|입니다\./g, "")
        .replace(/[가-힣]+/g, "")
        .replace(/[·]/g, "/")
        .replace(/\s*\/\s*/g, "/")
        .replace(/\s+/g, " ")
        .trim();
      if (translated && !hasHangul(translated)) return localizedValueLabel(translated);
      return fallback || englishFallbackSentence(original);
    }

    function ensureEnglish(value, fallback = "Market indicator") {
      const text = String(value || "");
      if (state.language !== "en" || !text) return text;
      return hasHangul(text) ? englishGenericText(text, fallback) : text;
    }

    function englishMetricName(value) {
      const text = String(value || "");
      if (!text) return "";
      if (englishMetricNameFallbacks[text]) return englishMetricNameFallbacks[text];
      const usReleaseMatch = text.match(/^미국 (.+) 발표$/);
      if (usReleaseMatch) return `US ${usReleaseMatch[1]} release`;
      if (hasHangul(text)) return englishGenericText(text, "Metric");
      return text;
    }

    function localizedMetricName(metricId, fallback = "") {
      const metric = metricById(metricId);
      if (metric) return localizedField(metric, "name");
      return state.language === "en" ? englishMetricName(fallback) : fallback;
    }

    function localizedValueLabel(value) {
      const text = String(value ?? "");
      if (state.language !== "en" || !text) return text;
      return text
        .replace(/\s*K건/g, "k")
        .replace(/\s*M대/g, "M units")
        .replace(/\s*조원/g, " tn KRW")
        .replace(/\s*억원/g, " KRW 100mn")
        .replace(/\s*원/g, " KRW")
        .replace(/\s*점/g, " pts")
        .replace(/\s*배/g, "x")
        .replace(/\s*건/g, " events")
        .replace(/\s+/g, " ")
        .trim();
    }

    function localizedText(value) {
      const text = String(value || "");
      if (state.language !== "en" || !text) return text;
      if (englishTextFallbacks[text]) return englishTextFallbacks[text];
      if (englishMeaningFallbacks[text]) return englishMeaningFallbacks[text];
      if (englishMetricNameFallbacks[text]) return englishMetricNameFallbacks[text];
      if (englishIndustryFallbacks[text]) return englishIndustryFallbacks[text];
      if (englishGroupFallbacks[text]) return englishGroupFallbacks[text];
      if (englishDepthFallbacks[text]) return englishDepthFallbacks[text];
      if (englishFrequencyFallbacks[text]) return englishFrequencyFallbacks[text];
      const translated = localizedValueLabel(englishMetricName(text));
      return hasHangul(translated) ? englishGenericText(translated, englishFallbackSentence(text)) : translated;
    }

    function localizedMeaning(item) {
      if (!item) return "";
      const raw = item.meaning || "";
      if (state.language !== "en") return raw;
      if (item.meaning_en) return item.meaning_en;
      if (englishMeaningFallbacks[raw]) return englishMeaningFallbacks[raw];
      const industry = localizedIndustry(item.industry);
      if (raw.includes("흐름을 이해할 때 참고하는 보조 지표입니다.")) {
        return `Proxy indicator used to monitor ${industry || "sector"} trends.`;
      }
      const translated = localizedText(raw);
      return hasHangul(translated) ? englishFallbackSentence(raw) : translated;
    }

    function localizedIndustry(industry) {
      if (state.language !== "en") return industry || "";
      return ensureEnglish(DASHBOARD_DATA.industry_labels_en?.[industry] || englishIndustryFallbacks[industry] || industry || "", "Industry");
    }

    function localizedField(item, field) {
      if (!item) return "";
      if (state.language !== "en") return item[field] || "";
      const translated = item[`${field}_en`];
      if (translated) return ensureEnglish(translated, field === "meaning" ? englishFallbackSentence(item[field] || "") : "Metric");
      if (field === "name") return englishMetricName(item.name);
      if (field === "meaning") return localizedMeaning(item);
      if (field === "industry") return localizedIndustry(item.industry);
      if (field === "group") return localizedGroup(item.group, [item]);
      if (field === "depth") return localizedDepth(item.depth, [item]);
      if (field === "frequency") {
        const frequency = String(item.frequency || "").replace(/\s+/g, "");
        return englishFrequencyFallbacks[frequency] || item.frequency || "";
      }
      if (field === "unit") return localizedUnit(item);
      return localizedText(item[field] || "");
    }

    function metricMeaningParts(metric) {
      const explicitDescription = String(localizedField(metric, "description") || "").trim();
      const explicitInterpretation = String(localizedField(metric, "interpretation_context") || "").trim();
      if (explicitDescription) {
        return { description: explicitDescription, interpretation: explicitInterpretation };
      }

      const meaning = String(localizedField(metric, "meaning") || "").trim();
      if (!meaning) return { description: "", interpretation: explicitInterpretation };

      const sentences = meaning.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [meaning];
      let description = String(sentences.shift() || "").trim();
      const interpretation = [...sentences.map((sentence) => sentence.trim()).filter(Boolean), explicitInterpretation];

      // When a definition and a value judgement share one sentence, keep the definition in the table.
      const judgementStart = description.search(/\s+(?=(?:높을수록|낮을수록|증가하면|감소하면|늘면|줄면|오르면|내리면|급등하면|급락하면|마이너스\(|0보다|100보다|기준선을|저점에서|고점에서|역사적으로))/);
      if (judgementStart > 0) {
        interpretation.unshift(description.slice(judgementStart).trim());
        description = description.slice(0, judgementStart).trim();
      }
      return { description, interpretation: interpretation.filter(Boolean).join(" ") };
    }

    function metricDescriptionText(metric) {
      return metricMeaningParts(metric).description;
    }

    function metricInterpretationContext(metric) {
      return metricMeaningParts(metric).interpretation;
    }

    function localizedGroup(group, items = []) {
      if (state.language !== "en") return group || "";
      const first = items.find((item) => item.group === group && item.group_en);
      return ensureEnglish(first?.group_en || englishGroupFallbacks[group] || group || "", "Group");
    }

    function localizedDepth(depth, items = []) {
      if (state.language !== "en") return depth || "";
      const first = items.find((item) => item.depth === depth && item.depth_en);
      return ensureEnglish(first?.depth_en || englishDepthFallbacks[depth] || depth || "", "Section");
    }

    function localizedUnit(metric) {
      if (!metric) return "";
      if (state.language !== "en") return metric.unit || "";
      return metric.unit_en || englishUnitFallbacks[metric.unit] || metric.unit || "";
    }

    function formatMetricNumberWithUnit(value, unit, signed = false, isChange = false) {
      if (typeof value !== "number" || !Number.isFinite(value)) return "n/a";
      const text = numberText(value, signed);
      if (unit === "$B") {
        const prefix = signed ? (value > 0 ? "+" : value < 0 ? "-" : "") : "";
        return `${prefix}$${numberText(Math.abs(value))}B`;
      }
      if (unit === "%") return `${text}${isChange ? "%p" : "%"}`;
      if (!unit) return text;
      return `${text} ${unit}`;
    }

    function numberText(value, signed = false) {
      if (typeof value !== "number" || !Number.isFinite(value)) return "n/a";
      const abs = Math.abs(value);
      const digits = abs >= 100 ? 1 : 2;
      const formatted = abs.toLocaleString(state.language === "en" ? "en-US" : "ko-KR", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits
      });
      if (!signed || value === 0) return formatted;
      return `${value > 0 ? "+" : "-"}${formatted}`;
    }

    function dollarUnitScale(metric) {
      const unit = String(metric.unit || "");
      const rate = usdKrwRate();
      const english = state.language === "en";
      if (unit === "$B") return { scale: rate / 1000, unit: english ? "tn KRW" : "조원" };
      if (unit.includes("백만달러")) {
        return english ? { scale: rate / 1000, unit: "bn KRW" } : { scale: rate / 100, unit: "억원" };
      }
      if (unit === "$" || unit.includes("달러") || unit.toUpperCase().includes("USD")) {
        return { scale: rate, unit: english ? "KRW" : "원" };
      }
      return null;
    }

    function isDollarMetric(metric) {
      return Boolean(dollarUnitScale(metric));
    }

    function usdKrwRate() {
      const match = DASHBOARD_DATA.metrics.find((metric) => {
        const name = String(metric.name || "").toUpperCase();
        return typeof metric.value === "number" &&
          Number.isFinite(metric.value) &&
          String(metric.unit || "") === "원" &&
          (name.includes("환율") || name.includes("원/달러") || name.includes("USD/KRW"));
      });
      return match?.value || 1350;
    }

    function displayMetricValue(metric) {
      const scale = state.currency === "krw" ? dollarUnitScale(metric) : null;
      if (scale && typeof metric.value === "number" && Number.isFinite(metric.value)) {
        const separator = state.language === "en" ? " " : "";
        return `${numberText(metric.value * scale.scale)}${separator}${scale.unit}`;
      }
      if (state.language === "en" && typeof metric.value === "number" && Number.isFinite(metric.value)) {
        return formatMetricNumberWithUnit(metric.value, localizedUnit(metric));
      }
      if (!scale || typeof metric.value !== "number" || !Number.isFinite(metric.value)) {
        return state.language === "en" ? localizedValueLabel(metric.display_value) : metric.display_value;
      }
      return `${numberText(metric.value * scale.scale)}${scale.unit}`;
    }

    function displayMetricChange(metric) {
      const scale = state.currency === "krw" ? dollarUnitScale(metric) : null;
      if (scale && typeof metric.change_abs === "number" && Number.isFinite(metric.change_abs)) {
        const separator = state.language === "en" ? " " : "";
        return `${numberText(metric.change_abs * scale.scale, true)}${separator}${scale.unit}`;
      }
      if (state.language === "en" && typeof metric.change_abs === "number" && Number.isFinite(metric.change_abs)) {
        return formatMetricNumberWithUnit(metric.change_abs, localizedUnit(metric), true, true);
      }
      if (!scale || typeof metric.change_abs !== "number" || !Number.isFinite(metric.change_abs)) {
        return state.language === "en" ? localizedValueLabel(metric.change_abs_label) : metric.change_abs_label;
      }
      return `${numberText(metric.change_abs * scale.scale, true)}${scale.unit}`;
    }

    function displayHistory(history, metric) {
      const scale = state.currency === "krw" ? dollarUnitScale(metric || {}) : null;
      if (!scale) return history;
      return (history || []).map((point) => ({
        ...point,
        value: point.value * scale.scale
      }));
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[char]));
    }

    function regexEscape(value) {
      return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    function searchHighlightTokens() {
      if (!isSearchFiltering()) return [];
      return normalizeSearchText(state.searchQuery)
        .split(" ")
        .filter((token) => token.length >= 2 && !isInitialToken(token))
        .sort((a, b) => b.length - a.length)
        .slice(0, 6);
    }

    function highlightSearchText(value) {
      const text = String(value ?? "");
      const tokens = searchHighlightTokens();
      if (!tokens.length) return escapeHtml(text);
      const pattern = new RegExp(`(${tokens.map(regexEscape).join("|")})`, "gi");
      return escapeHtml(text).replace(pattern, '<mark class="search-mark">$1</mark>');
    }

    function directionClass(value) {
      if (typeof value !== "number" || !Number.isFinite(value) || value === 0) return "";
      return value > 0 ? "positive" : "negative";
    }

    function trendIconClass(value) {
      if (typeof value !== "number" || !Number.isFinite(value) || value === 0) return "fa-minus";
      return value > 0 ? "fa-arrow-trend-up" : "fa-arrow-trend-down";
    }

    function metricChangeBadge(metric) {
      const className = directionClass(metric.change_pct);
      const label = metric.change_pct_label || "n/a";
      return `<span class="metric-change-badge ${className}">
        <i class="fa-solid ${trendIconClass(metric.change_pct)}" aria-hidden="true"></i>
        <span>${escapeHtml(label)}</span>
      </span>`;
    }

    function groupRank(group) {
      if (group === "대표주가") return 10000;
      const index = groupOrder.indexOf(group);
      return index === -1 ? 999 : index;
    }

    const depthOrder = ["전체 업황", "메모리 반도체", "AI/GPU", "CPU/프로세서", "파운드리", "장비", "패키징/후공정", "소자/부품"];

    function depthRank(depth) {
      const index = depthOrder.indexOf(depth);
      return index === -1 ? 999 : index;
    }

    function groupMetrics(items, keyFn) {
      if (Map.groupBy) return Map.groupBy(items, keyFn);
      return items.reduce((map, item) => {
        const key = keyFn(item);
        map.set(key, [...(map.get(key) || []), item]);
        return map;
      }, new Map());
    }

    function baseVisibleIndustries() {
      return DASHBOARD_DATA.industries.filter((industry) =>
        DASHBOARD_DATA.metrics.some((metric) => metric.industry === industry && isIndustryMetric(metric))
      );
    }

    function storedIndustryOrder() {
      try {
        const parsed = JSON.parse(localStorage.getItem("dashboard-industry-order") || "[]");
        return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string") : [];
      } catch {
        return [];
      }
    }

    function orderedIndustries(industries, order = null) {
      const selectedOrder = order || state.draftIndustryOrder || storedIndustryOrder();
      const rank = new Map(selectedOrder.map((industry, index) => [industry, index]));
      return [...industries].sort((a, b) => {
        const aRank = rank.has(a) ? rank.get(a) : Number.MAX_SAFE_INTEGER;
        const bRank = rank.has(b) ? rank.get(b) : Number.MAX_SAFE_INTEGER;
        if (aRank !== bRank) return aRank - bRank;
        return industries.indexOf(a) - industries.indexOf(b);
      });
    }

    function visibleIndustries() {
      return orderedIndustries(baseVisibleIndustries());
    }

    function idSegment(value) {
      return Array.from(String(value || "")).map((char) => char.charCodeAt(0).toString(36)).join("-");
    }

    function industryId(industry) {
      return `industry-${idSegment(industry)}`;
    }

    function depthId(industry, depth) {
      return `${industryId(industry)}-depth-${idSegment(depth)}`;
    }

    function semiconductorDepthEntries() {
      const semiconductorMetrics = DASHBOARD_DATA.metrics.filter((metric) => metric.industry === "반도체");
      return [...groupMetrics(semiconductorMetrics, (metric) => metric.depth || "전체 업황").entries()]
        .sort(([a], [b]) => depthRank(a) - depthRank(b) || String(a).localeCompare(String(b), "ko"))
        .filter(([depth, items]) => depth !== "전체 업황" && items.length);
    }

    function setActiveIndustry(industry, depth = "", options = {}) {
      if (!industry) return;
      state.navRoot = "industry";
      state.activeIndustry = industry;
      state.activeDepth = depth || "";
      saveNavState();
      if (options.updateHash !== false) writeDashboardHash(currentNavHash(), "push");
      document.querySelectorAll("[data-industry]").forEach((button) => {
        const active = button.dataset.industry === industry;
        button.setAttribute("aria-pressed", String(active));
        button.setAttribute("aria-current", String(active && !state.activeDepth));
      });
      document.querySelectorAll("[data-menu-depth]").forEach((button) => {
        const active = button.dataset.depthIndustry === industry && button.dataset.depthName === state.activeDepth;
        button.setAttribute("aria-pressed", String(active));
        button.setAttribute("aria-current", String(active));
      });
    }

    function renderMenuDepths(industry) {
      if (industry !== "반도체") return "";
      const depthItems = semiconductorDepthEntries().map(([depth, items]) => `
        <div class="menu-depth-item">
          <button type="button" class="menu-depth-button" data-menu-depth data-depth-industry="${escapeHtml(industry)}" data-depth-name="${escapeHtml(depth)}" data-target="${depthId(industry, depth)}" aria-pressed="${state.activeIndustry === industry && state.activeDepth === depth}" aria-current="${state.activeIndustry === industry && state.activeDepth === depth}" ${state.isReordering ? 'tabindex="-1"' : ""}>
            ${escapeHtml(localizedDepth(depth, items))}
          </button>
        </div>
      `).join("");
      return depthItems ? `<div class="menu-depth-list">${depthItems}</div>` : "";
    }

    function setBranchLine(container, markerSelector, topProperty, heightProperty, branchHeight, endInset = 0, startOvershoot = 0) {
      const markers = [...container.querySelectorAll(markerSelector)];
      if (!markers.length) return;
      const containerBox = container.getBoundingClientRect();
      const firstBox = markers[0].getBoundingClientRect();
      const lastBox = markers[markers.length - 1].getBoundingClientRect();
      const top = firstBox.top - containerBox.top + firstBox.height / 2 - branchHeight - startOvershoot;
      const end = lastBox.top - containerBox.top + lastBox.height / 2 - endInset;
      const topPx = Math.max(0, Math.round(top));
      const endPx = Math.max(topPx, Math.round(end));
      container.style.setProperty(topProperty, `${topPx}px`);
      container.style.setProperty(heightProperty, `${endPx - topPx}px`);
    }

    function updateBranchLines() {
      document.querySelectorAll(".depth-tree").forEach((tree) => {
        const cornerHeight = Number.parseFloat(getComputedStyle(tree).getPropertyValue("--depth-corner-height")) || 17;
        setBranchLine(tree, ".depth-title", "--depth-branch-top", "--depth-branch-height", cornerHeight, cornerHeight);
      });
    }

    function scheduleBranchLineUpdate() {
      requestAnimationFrame(updateBranchLines);
    }

    function renderFilters() {
      const menu = document.getElementById("industryFilters");
      if (state.navRoot === "overview" || state.navRoot === "root") {
        menu.innerHTML = `
          <div class="menu-item"><button type="button" data-nav-root="overview" aria-pressed="${state.navRoot === "overview"}" aria-current="${state.navRoot === "overview"}">${escapeHtml(t("marketOverview"))}</button></div>
          <div class="menu-item"><button type="button" data-nav-root="market" aria-pressed="false">${escapeHtml(t("marketNav"))}</button></div>
          <div class="menu-item"><button type="button" data-nav-root="industry" aria-pressed="false">${escapeHtml(t("indicatorNav"))}</button></div>
          <div class="menu-item"><button type="button" data-nav-root="future" aria-pressed="false">${escapeHtml(t("futureNav"))}</button></div>
        `;
        menu.querySelectorAll("[data-nav-root]").forEach((button) => {
          button.addEventListener("click", () => setNavRoot(button.dataset.navRoot));
        });
        return;
      }

      if (state.navRoot === "market") {
        menu.innerHTML = `
          <div class="menu-item"><button type="button" data-nav-root="overview" aria-pressed="false">← ${escapeHtml(t("back"))}</button></div>
          ${marketCategories.map((category) => `
            <div class="menu-item" data-menu-item data-market-category-item="${escapeHtml(category.key)}">
              <button type="button" data-market-category="${escapeHtml(category.key)}" data-target="${marketSectionId(category.key)}" aria-pressed="${state.marketCategory === category.key}" aria-current="${state.marketCategory === category.key}">
                ${escapeHtml(t(category.labelKey))}
              </button>
            </div>
          `).join("")}
        `;
        menu.querySelector("[data-nav-root]")?.addEventListener("click", () => setNavRoot("overview"));
        menu.querySelectorAll("[data-market-category]").forEach((button) => {
          button.addEventListener("click", () => setMarketCategory(button.dataset.marketCategory));
        });
        initMenuScrollDrag();
        return;
      }

      if (state.navRoot === "future") {
        const categories = futureCategories();
        menu.innerHTML = `
          <div class="menu-item"><button type="button" data-nav-root="overview" aria-pressed="false">← ${escapeHtml(t("back"))}</button></div>
          <div class="menu-item">
            <button type="button" data-future-view="track-record" aria-pressed="${state.futureView === "track-record"}" aria-current="${state.futureView === "track-record"}">
              ${escapeHtml(t("futureTrackRecordTitle"))}
            </button>
          </div>
          ${categories.map((category) => `
            <div class="menu-item">
              <button type="button" data-future-category="${escapeHtml(category)}" aria-pressed="${state.futureView !== "track-record" && state.futureCategory === category}" aria-current="${state.futureView !== "track-record" && state.futureCategory === category}">
                ${escapeHtml(localizedFutureCategory(category))}
              </button>
            </div>
          `).join("")}
        `;
        menu.querySelector("[data-nav-root]")?.addEventListener("click", () => setNavRoot("overview"));
        menu.querySelector("[data-future-view]")?.addEventListener("click", () => setFutureTrackRecordView());
        menu.querySelectorAll("[data-future-category]").forEach((button) => {
          button.addEventListener("click", () => setFutureCategory(button.dataset.futureCategory || futureAllCategory));
        });
        initMenuScrollDrag();
        return;
      }

      const industries = visibleIndustries();
      if (!state.activeIndustry && industries.length) {
        state.activeIndustry = industries[0];
      }
      menu.innerHTML = `
        <div class="menu-item"><button type="button" data-nav-root="overview" aria-pressed="false">← ${escapeHtml(t("back"))}</button></div>
        ${industries.map((industry) => `
        <div class="menu-item" data-menu-item data-industry-item="${escapeHtml(industry)}" draggable="${state.isReordering}">
          <button type="button" data-industry="${escapeHtml(industry)}" data-target="${industryId(industry)}" aria-pressed="${state.activeIndustry === industry}" aria-current="${state.activeIndustry === industry && !state.activeDepth}" ${state.isReordering ? 'tabindex="-1"' : ""}>
            ${escapeHtml(localizedIndustry(industry))}
          </button>
          ${renderMenuDepths(industry)}
          <span class="drag-handle" aria-hidden="true"><i class="fa-solid fa-grip-lines"></i></span>
        </div>
      `).join("")}`;
      menu.querySelector("[data-nav-root]")?.addEventListener("click", () => setNavRoot("overview"));
      document.querySelectorAll("[data-industry]").forEach((button) => {
        button.addEventListener("click", () => {
          if (state.isReordering) return;
          const industry = button.dataset.industry;
          const target = document.getElementById(button.dataset.target);
          if (!industry || !target) return;
          setActiveIndustry(industry);
          target.scrollIntoView({ behavior: "smooth", block: "start" });
          closeDrawerOnMobile();
        });
      });
      document.querySelectorAll("[data-menu-depth]").forEach((button) => {
        button.addEventListener("click", () => {
          if (state.isReordering) return;
          const industry = button.dataset.depthIndustry;
          const depth = button.dataset.depthName;
          const target = document.getElementById(button.dataset.target);
          if (!industry || !depth || !target) return;
          setActiveIndustry(industry, depth);
          target.scrollIntoView({ behavior: "smooth", block: "start" });
          closeDrawerOnMobile();
        });
      });
      initMenuDrag();
      initMenuScrollDrag();
      scheduleBranchLineUpdate();
    }
