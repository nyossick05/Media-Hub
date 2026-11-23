/* Discover: live search across movies, TV and anime, plus trending and recommendations. */
(() => {
  const { api, Library, syncAll, cardHTML, renderGrid, skeletons, esc, toast } = MH;
  const $ = (id) => document.getElementById(id);

  const TYPES = ["movie", "tv", "anime"];
  const PLURAL = { movie: "Movies", tv: "TV shows", anime: "Anime" };
  const PREVIEW = 8; // titles per type when viewing "All"

  const input = $("q"), box = $("searchbox"), results = $("results"), notice = $("notice");
  const searchView = $("search-view"), browseView = $("browse-view");

  let data = null;          // last search response
  let shownQuery = "";      // the query `data` belongs to
  let filter = "all";
  let seq = 0;              // lets us ignore responses that arrive out of order
  let controller = null;    // lets us cancel the request that's now out of date
  let timer = null;

  /* ---------- Search ---------- */

  function onInput() {
    const val = input.value.trim();
    $("clear").hidden = !input.value;
    $("hint").hidden = !!input.value;
    clearTimeout(timer);
    history.replaceState(null, "", val ? `?q=${encodeURIComponent(val)}` : location.pathname);

    if (val.length < 2) {
      seq++; controller?.abort();
      box.classList.remove("busy");
      searchView.hidden = true; browseView.hidden = false;
      return;
    }
    timer = setTimeout(() => search(val), 250);
  }

  async function search(val) {
    const mine = ++seq;
    controller?.abort();
    controller = new AbortController();
    browseView.hidden = true; searchView.hidden = false;
    box.classList.add("busy");

    // First search: show placeholders. Later searches: keep old results, dimmed, to avoid flicker.
    if (!data) { notice.innerHTML = ""; results.innerHTML = `<div class="grid">${skeletons(10)}</div>`; }
    else results.firstElementChild?.classList.add("dim");

    try {
      const res = await api(`/api/search?q=${encodeURIComponent(val)}`, { signal: controller.signal });
      if (mine !== seq) return;
      data = res; shownQuery = val;
      render();
    } catch (err) {
      if (err.name === "AbortError" || mine !== seq) return;
      results.innerHTML = "";
      notice.innerHTML = `<div class="notice"><span>Search isn't responding. Check your connection and try again.</span>
        <button type="button" class="btn link" data-retry>Try again</button></div>`;
    } finally {
      if (mine === seq) box.classList.remove("busy");
    }
  }

  function render() {
    const total = TYPES.reduce((n, t) => n + data[t].length, 0);

    $("type-filter").innerHTML =
      `<button type="button" class="chip" data-filter="all" aria-pressed="${filter === "all"}">All <span class="n">${total}</span></button>` +
      TYPES.map((t) => `<button type="button" class="chip" data-filter="${t}" aria-pressed="${filter === t}">${PLURAL[t]} <span class="n">${data[t].length}</span></button>`).join("");

    notice.innerHTML = data.failed.length
      ? `<div class="notice"><span>${data.failed.map((t) => PLURAL[t]).join(" and ")} didn't load, so this list may be missing some titles.</span>
         <button type="button" class="btn link" data-retry>Try again</button></div>`
      : "";

    if (total === 0 && !data.failed.length) {
      results.innerHTML = `<div class="empty-state"><strong>No results for “${esc(shownQuery)}”</strong>
        Check the spelling, or try fewer words.</div>`;
      return;
    }

    const visible = filter === "all" ? TYPES : [filter];
    results.innerHTML = visible.filter((t) => data[t].length).map((t) => {
      const items = filter === "all" ? data[t].slice(0, PREVIEW) : data[t];
      const more = filter === "all" && data[t].length > PREVIEW;
      return `<section class="section">
        <div class="section-head"><h2>${PLURAL[t]}</h2><span class="count">${data[t].length}</span>
          ${more ? `<button type="button" class="btn link spacer" data-filter="${t}">See all ${data[t].length}</button>` : ""}
        </div>
        <div class="grid">${items.map((i) => cardHTML(i)).join("")}</div>
      </section>`;
    }).join("");
    syncAll(results);
  }

  input.addEventListener("input", onInput);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const val = input.value.trim();
      if (val.length >= 2) { clearTimeout(timer); search(val); }
    } else if (e.key === "Escape" && input.value) {
      input.value = ""; onInput();
    }
  });
  $("clear").addEventListener("click", () => { input.value = ""; onInput(); input.focus(); });

  // Chips, "See all" and "Try again" are all handled here.
  document.addEventListener("click", (e) => {
    const f = e.target.closest("[data-filter]");
    if (f && data) { filter = f.dataset.filter; render(); window.scrollTo({ top: 0 }); return; }
    if (e.target.closest("[data-retry]")) search(input.value.trim());
  });

  /* ---------- Trending ---------- */

  const trendCache = new Map();
  let trendType = "movie";

  function loadTrend(type) {
    if (!trendCache.has(type)) {
      trendCache.set(type, api(`/api/trending/${type}`).catch((e) => { trendCache.delete(type); throw e; }));
    }
    return trendCache.get(type);
  }

  async function showTrend(type) {
    trendType = type;
    document.querySelectorAll("#trend-tabs .chip").forEach((c) => c.setAttribute("aria-pressed", c.dataset.type === type));
    const grid = $("trend-grid");
    grid.innerHTML = skeletons(12);
    try {
      const items = await loadTrend(type);
      if (type !== trendType) return;
      renderGrid(grid, items);
    } catch (err) {
      if (type !== trendType) return;
      grid.innerHTML = `<div class="empty-state"><strong>Couldn't load trending titles</strong>${esc(err.message)}
        <br><button type="button" class="btn secondary" id="retry-trend">Try again</button></div>`;
      $("retry-trend").onclick = () => showTrend(type);
    }
  }

  $("trend-tabs").addEventListener("click", (e) => {
    const c = e.target.closest("[data-type]");
    if (c) showTrend(c.dataset.type);
  });

  /* ---------- For you ---------- */

  async function showForYou() {
    const grid = $("foryou-grid");
    $("foryou").hidden = false;
    grid.innerHTML = skeletons(6);
    try {
      const res = await api("/api/recommendations");
      if (!res.items.length) { $("foryou").hidden = true; return; }
      renderGrid(grid, res.items.slice(0, 12));
    } catch (err) {
      $("foryou").hidden = true;
    }
  }
  $("shuffle").addEventListener("click", showForYou);

  /* ---------- Start up ---------- */

  showTrend("movie");
  ["tv", "anime"].forEach((t) => loadTrend(t).catch(() => {})); // warm the other tabs

  Library.load().then(() => {
    if (Library.all().some((i) => i.rating)) showForYou();
  }).catch(() => {});

  const initial = new URLSearchParams(location.search).get("q");
  if (initial) { input.value = initial; onInput(); clearTimeout(timer); search(initial.trim()); }
  if (location.hash === "#search" || matchMedia("(pointer: fine)").matches) input.focus();
})();
