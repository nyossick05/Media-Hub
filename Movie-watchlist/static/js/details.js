/* Details page for one movie, show or anime. */
(() => {
  const { api, Library, Editor, toast, esc, TYPE_LABEL, STATUS_LABEL } = MH;
  const root = document.getElementById("details");
  const type = root.dataset.type;
  const id = Number(root.dataset.id);
  const detail = document.getElementById("detail");
  let data = null;

  // "Back" goes to where you came from (search results, watchlist) when there is somewhere to go.
  document.getElementById("back").addEventListener("click", (e) => {
    if (history.length > 1 && document.referrer.startsWith(location.origin)) { e.preventDefault(); history.back(); }
  });

  function facts(d) {
    const out = [];
    if (d.year) out.push(`<span>${esc(d.year)}</span>`);
    if (d.rating) out.push(`<span class="score-inline" title="Average rating">★ ${esc(d.rating)}</span>`);
    if (d.seasons) out.push(`<span>${d.seasons} ${d.seasons === 1 ? "season" : "seasons"}</span>`);
    if (d.episodes) out.push(`<span>${d.episodes} episodes</span>`);
    if (d.runtime) out.push(`<span>${d.runtime} min${d.episodes ? " per episode" : ""}</span>`);
    if (d.status) out.push(`<span>${esc(d.status)}</span>`);
    return out.join("");
  }

  function actions() {
    const box = document.getElementById("actions");
    if (!box || !data) return;
    const lib = Library.get(type, id);
    if (!lib) {
      box.innerHTML = `<button type="button" class="btn" id="add">Add to watchlist</button>`;
      return;
    }
    box.innerHTML = `
      <span class="status ${esc(lib.status)}">${STATUS_LABEL[lib.status]}</span>
      ${lib.rating ? `<span class="score-inline" style="color:var(--gold);font-weight:600" title="Your rating">★ ${lib.rating}</span>` : ""}
      <button type="button" class="btn secondary" id="edit" ${lib.pending ? "disabled" : ""}>Edit entry</button>`;
  }

  function render(d) {
    data = d;
    document.title = `${d.title} - Media Hub`;

    const hero = document.getElementById("hero");
    if (d.backdrop) {
      hero.classList.remove("plain");
      hero.insertAdjacentHTML("beforeend", `<img src="${esc(d.backdrop)}" alt="" fetchpriority="high">`);
    }

    detail.innerHTML = `
      <div class="art">${d.poster
        ? `<img src="${esc(d.poster)}" alt="Poster for ${esc(d.title)}" width="240" height="360" fetchpriority="high">`
        : `<div class="poster empty">${esc(d.title)}</div>`}</div>
      <div class="info">
        <h1>${esc(d.title)}</h1>
        <div class="facts"><span>${TYPE_LABEL[type]}</span>${facts(d)}</div>
        ${d.genres.length ? `<div class="genres">${d.genres.map((g) => `<span>${esc(g)}</span>`).join("")}</div>` : ""}
        <p class="overview">${esc(d.overview) || "No description available."}</p>
        <div class="actions" id="actions"></div>
      </div>`;
    actions();
  }

  detail.addEventListener("click", async (e) => {
    if (e.target.closest("#edit")) {
      const lib = Library.get(type, id);
      if (lib && !lib.pending) Editor.open(lib);
    } else if (e.target.closest("#add")) {
      try {
        const res = await Library.add({ tmdb_id: id, title: data.title, poster: data.poster, media_type: type });
        toast(res.added ? `Added ${data.title}` : `${data.title} is already in your watchlist`, {
          action: res.added ? { label: "Undo", run: () => Library.remove(res.item).catch(() => {}) } : undefined,
        });
      } catch (err) {
        toast(err.message, { kind: "error" });
      }
    }
  });

  document.addEventListener("library", actions);

  async function load() {
    try {
      render(await api(`/api/details/${type}/${id}`));
      Library.load().catch(() => {});
    } catch (err) {
      detail.innerHTML = `<div class="empty-state"><strong>Couldn't load this title</strong>${esc(err.message)}
        <br><button type="button" class="btn secondary" id="retry">Try again</button></div>`;
      document.getElementById("retry").onclick = load;
    }
  }
  load();
})();
