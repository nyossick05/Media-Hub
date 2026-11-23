/* Watchlist: everything is filtered in the browser, so filters respond instantly. */
(() => {
  const { Library, renderGrid, skeletons, esc, TYPE_LABEL, STATUS_LABEL } = MH;
  const $ = (id) => document.getElementById(id);
  const grid = $("grid");

  const state = { type: "all", status: "all", text: "", sort: "added" };
  const TYPE_CHIPS = [["all", "All"], ["movie", "Movies"], ["tv", "TV shows"], ["anime", "Anime"]];
  const STATUS_CHIPS = [["all", "Any status"], ...Object.entries(STATUS_LABEL)];

  const matches = (i, skip) =>
    (skip === "type" || state.type === "all" || i.media_type === state.type) &&
    (skip === "status" || state.status === "all" || i.status === state.status) &&
    (!state.text || i.title.toLowerCase().includes(state.text));

  function drawChips() {
    const items = Library.all();
    // Each row counts what you'd get if you picked that chip, given the other row's filter.
    $("type-chips").innerHTML = TYPE_CHIPS.map(([v, label]) => {
      const n = items.filter((i) => matches(i, "type") && (v === "all" || i.media_type === v)).length;
      return `<button type="button" class="chip" data-type="${v}" aria-pressed="${state.type === v}">${label} <span class="n">${n}</span></button>`;
    }).join("");
    $("status-chips").innerHTML = STATUS_CHIPS.map(([v, label]) => {
      const n = items.filter((i) => matches(i, "status") && (v === "all" || i.status === v)).length;
      return `<button type="button" class="chip" data-status="${v}" aria-pressed="${state.status === v}">${label} <span class="n">${n}</span></button>`;
    }).join("");
  }

  function draw() {
    const all = Library.all();
    drawChips();

    if (!all.length) {
      grid.style.display = "block";
      grid.innerHTML = `<div class="empty-state"><strong>Your watchlist is empty</strong>
        Search for a movie, show or anime and press the plus on its poster.
        <br><a class="btn" href="/#search">Find something to watch</a></div>`;
      return;
    }

    let list = all.filter((i) => matches(i));
    if (state.sort === "title") list.sort((a, b) => a.title.localeCompare(b.title));
    else if (state.sort === "rating") list.sort((a, b) => (b.rating || 0) - (a.rating || 0) || a.title.localeCompare(b.title));

    if (!list.length) {
      grid.style.display = "block";
      grid.innerHTML = `<div class="empty-state"><strong>Nothing matches those filters</strong>
        <button type="button" class="btn secondary" id="reset">Clear filters</button></div>`;
      $("reset").onclick = () => {
        Object.assign(state, { type: "all", status: "all", text: "" });
        $("wl-search").value = "";
        draw();
      };
      return;
    }
    grid.style.display = "";
    renderGrid(grid, list, { mode: "library" });
  }

  $("type-chips").addEventListener("click", (e) => {
    const c = e.target.closest("[data-type]");
    if (c) { state.type = c.dataset.type; draw(); }
  });
  $("status-chips").addEventListener("click", (e) => {
    const c = e.target.closest("[data-status]");
    if (c) { state.status = c.dataset.status; draw(); }
  });
  $("wl-search").addEventListener("input", (e) => { state.text = e.target.value.trim().toLowerCase(); draw(); });
  $("wl-sort").addEventListener("change", (e) => { state.sort = e.target.value; draw(); });

  // Any add, edit or remove (including Undo) redraws the list.
  document.addEventListener("library", () => { if (Library._loading) draw(); });

  grid.innerHTML = skeletons(12);
  Library.load().then(draw).catch((err) => {
    grid.style.display = "block";
    grid.innerHTML = `<div class="empty-state"><strong>Couldn't load your watchlist</strong>${esc(err.message)}
      <br><button type="button" class="btn secondary" onclick="location.reload()">Reload</button></div>`;
  });
})();
