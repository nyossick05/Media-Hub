/* Stats: figures, bars and a rating histogram. Numbers come from /api/stats. */
(() => {
  const { api, esc, STATUS_LABEL, TYPE_LABEL } = MH;
  const root = document.getElementById("stats");
  const TYPE_COLOR = { movie: "var(--t-movie)", tv: "var(--t-tv)", anime: "var(--t-anime)" };
  const TYPE_PLURAL = { movie: "Movies", tv: "TV shows", anime: "Anime" };
  let retries = 0;

  const bars = (rows, max) => `<div class="bars">${rows.map(([label, n]) => `
    <div class="bar"><span>${esc(label)}</span>
      <div class="track"><div class="fill" data-w="${max ? (n / max) * 100 : 0}"></div></div>
      <span class="n">${n}</span></div>`).join("")}</div>`;

  function render(s) {
    if (!s.total) {
      root.innerHTML = `<div class="empty-state"><strong>Nothing to count yet</strong>
        Add a few titles and your numbers will show up here.<br><a class="btn" href="/#search">Find something to watch</a></div>`;
      return;
    }

    const c = s.status_counts;
    const figures = [
      [s.total, s.total === 1 ? "title in your list" : "titles in your list"],
      [c.completed || 0, "completed"],
      [c.watching || 0, "watching now"],
      ...(s.avg_rating ? [[s.avg_rating, `average rating from ${s.rated} ${s.rated === 1 ? "title" : "titles"}`]] : []),
    ];

    const statusRows = Object.keys(STATUS_LABEL).map((k) => [STATUS_LABEL[k], c[k] || 0]);
    const statusMax = Math.max(...statusRows.map((r) => r[1]));

    const types = Object.keys(TYPE_PLURAL).filter((t) => s.type_counts[t]);
    const maxHist = Math.max(...Object.values(s.histogram));
    const genreMax = s.top_genres.length ? s.top_genres[0][1] : 0;

    root.innerHTML = `
      <div class="figures">${figures.map(([n, label]) => `<div class="figure"><b>${n}</b><span>${esc(label)}</span></div>`).join("")}</div>

      <section class="section"><div class="section-head"><h2>Where things stand</h2></div>${bars(statusRows, statusMax)}</section>

      <section class="section"><div class="section-head"><h2>What you watch</h2></div>
        <div class="stack" role="img" aria-label="${types.map((t) => `${s.type_counts[t]} ${TYPE_PLURAL[t]}`).join(", ")}">
          ${types.map((t) => `<span style="width:${(s.type_counts[t] / s.total) * 100}%;background:${TYPE_COLOR[t]}"></span>`).join("")}
        </div>
        <div class="legend">${types.map((t) => `<span><i style="background:${TYPE_COLOR[t]}"></i>${TYPE_PLURAL[t]} ${s.type_counts[t]}</span>`).join("")}</div>
      </section>

      ${s.rated ? `<section class="section"><div class="section-head"><h2>How you rate</h2></div>
        <div class="histogram" role="img" aria-label="Number of titles at each rating from 1 to 10">
          ${Object.entries(s.histogram).map(([r, n]) => `<div title="${n} rated ${r}">
            <span>${n || ""}</span><span class="col${n ? "" : " zero"}" style="height:${maxHist ? (n / maxHist) * 100 : 0}%"></span><span>${r}</span></div>`).join("")}
        </div></section>` : ""}

      ${s.top_genres.length ? `<section class="section"><div class="section-head"><h2>Favourite genres</h2></div>${bars(s.top_genres, genreMax)}</section>` : ""}

      ${s.genres_pending ? `<p class="card-meta" style="margin-top:32px">Still collecting genres for some titles. This page refreshes itself.</p>` : ""}`;

    requestAnimationFrame(() => requestAnimationFrame(() =>
      root.querySelectorAll(".fill").forEach((el) => { el.style.width = el.dataset.w + "%"; })));
  }

  async function load() {
    try {
      const s = await api("/api/stats");
      render(s);
      if (s.genres_pending && retries++ < 3) setTimeout(load, 4000);
    } catch (err) {
      root.innerHTML = `<div class="empty-state"><strong>Couldn't load your stats</strong>${esc(err.message)}
        <br><button type="button" class="btn secondary" onclick="location.reload()">Reload</button></div>`;
    }
  }
  load();
})();
