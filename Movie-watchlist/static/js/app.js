/* Shared code for every page: API helper, watchlist state, cards, toasts, editor. */
(() => {
  const TYPE_LABEL = { movie: "Movie", tv: "TV show", anime: "Anime" };
  const STATUS_LABEL = {
    plan_to_watch: "Plan to watch", watching: "Watching", completed: "Completed", dropped: "Dropped",
  };
  // Movies have no "watching" state; shows and anime do.
  const STATUSES_FOR = {
    movie: ["plan_to_watch", "completed", "dropped"],
    tv: ["plan_to_watch", "watching", "completed", "dropped"],
    anime: ["plan_to_watch", "watching", "completed", "dropped"],
  };

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function api(path, { method = "GET", body, signal } = {}) {
    const res = await fetch(path, {
      method, signal,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) throw new Error((data && data.error) || "Something went wrong. Try again.");
    return data;
  }

  /* ---------- Toasts ---------- */

  function toast(message, { action, kind, ms = 5000 } = {}) {
    const host = document.getElementById("toasts");
    while (host.children.length >= 3) host.firstChild.remove();
    const el = document.createElement("div");
    el.className = "toast" + (kind === "error" ? " error" : "");
    el.innerHTML = `<span>${esc(message)}</span>`;
    if (action) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = action.label;
      b.onclick = () => { el.remove(); action.run(); };
      el.append(b);
    }
    host.append(el);
    setTimeout(() => el.remove(), ms);
  }

  /* ---------- Library: the single source of truth for what's in your list ----------
     Keyed by "type:id" because TMDB and AniList ids overlap. Every change updates the
     screen immediately and talks to the server afterwards (reverting if it fails). */

  const Library = {
    items: new Map(),
    _loading: null,
    key: (type, id) => `${type}:${id}`,

    load() {
      if (!this._loading) {
        this._loading = api("/api/watchlist")
          .then((list) => {
            this.items.clear();
            list.forEach((i) => this.items.set(this.key(i.media_type, i.tmdb_id), i));
            notify(null);
            return list;
          })
          .catch((e) => { this._loading = null; throw e; });
      }
      return this._loading;
    },

    get(type, id) { return this.items.get(this.key(type, id)); },
    all() { return [...this.items.values()].sort((a, b) => (b.id ?? 1e12) - (a.id ?? 1e12)); },

    async add(base, extra = {}) {
      const k = this.key(base.media_type, base.tmdb_id);
      const existing = this.items.get(k);
      if (existing) return { added: false, item: existing };
      this.items.set(k, {
        id: null, pending: true, tmdb_id: base.tmdb_id, title: base.title, poster: base.poster,
        media_type: base.media_type, status: extra.status || "plan_to_watch",
        rating: extra.rating ?? null, review: extra.review || "",
      });
      notify(k);
      try {
        const res = await api("/api/watchlist", {
          method: "POST",
          body: {
            tmdb_id: base.tmdb_id, title: base.title, poster: base.poster, media_type: base.media_type,
            status: extra.status, rating: extra.rating, review: extra.review,
          },
        });
        this.items.set(k, res.item);
        notify(k);
        return res;
      } catch (e) {
        this.items.delete(k);
        notify(k);
        throw e;
      }
    },

    async save(item, patch) {
      const k = this.key(item.media_type, item.tmdb_id);
      const before = { ...item };
      Object.assign(item, patch);
      notify(k);
      try {
        const fresh = await api(`/api/watchlist/${item.id}`, { method: "PATCH", body: patch });
        this.items.set(k, fresh);
        notify(k);
        return fresh;
      } catch (e) {
        this.items.set(k, before);
        notify(k);
        throw e;
      }
    },

    async remove(item) {
      const k = this.key(item.media_type, item.tmdb_id);
      const copy = { ...item };
      this.items.delete(k);
      notify(k);
      try {
        await api(`/api/watchlist/${item.id}`, { method: "DELETE" });
        return copy;
      } catch (e) {
        this.items.set(k, copy);
        notify(k);
        throw e;
      }
    },
  };

  function notify(key) {
    document.dispatchEvent(new CustomEvent("library", { detail: { key } }));
    if (key === null) document.querySelectorAll(".card[data-key]").forEach(syncCard);
    else document.querySelectorAll(`.card[data-key="${key}"]`).forEach(syncCard);
  }

  /* ---------- Cards ---------- */

  const ICON_PLUS = '<svg class="i-plus" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
  const ICON_CHECK = '<svg class="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 13l4 4L19 7"/></svg>';

  // Cards only carry a key in the HTML; the full item lives here so click handlers can find it.
  const catalog = new Map();

  function posterInner(item, badge) {
    const img = item.poster
      ? `<img src="${esc(item.poster)}" alt="" loading="lazy" decoding="async" width="342" height="513" data-title="${esc(item.title)}">`
      : esc(item.title);
    return img + (badge ? `<span class="score" title="${esc(badge.title)}">★ ${esc(badge.value)}</span>` : "");
  }

  /* mode "browse": poster links to details, + button adds to the list (Discover).
     mode "library": poster opens the editor, shows your status and rating (Watchlist). */
  function cardHTML(item, { mode = "browse" } = {}) {
    const k = Library.key(item.media_type, item.tmdb_id);
    catalog.set(k, item);
    const href = `/details/${item.media_type}/${item.tmdb_id}`;
    const empty = item.poster ? "" : " empty";

    if (mode === "library") {
      const badge = item.rating ? { value: item.rating, title: "Your rating" } : null;
      return `<article class="card" data-key="${k}" data-title="${esc(item.title)}">
        <button type="button" class="poster${empty}" data-edit aria-label="Edit ${esc(item.title)}">${posterInner(item, badge)}</button>
        <a class="card-title" href="${href}">${esc(item.title)}</a>
        <p class="status ${esc(item.status)}">${STATUS_LABEL[item.status] || esc(item.status)}</p>
      </article>`;
    }

    const badge = item.rating ? { value: item.rating, title: "Average rating" } : null;
    return `<article class="card" data-key="${k}" data-title="${esc(item.title)}">
      <a class="poster${empty}" href="${href}" tabindex="-1" aria-hidden="true">${posterInner(item, badge)}</a>
      <button type="button" class="quick" data-quick>${ICON_PLUS}${ICON_CHECK}</button>
      <a class="card-title" href="${href}">${esc(item.title)}</a>
      ${item.year ? `<p class="card-meta">${esc(item.year)}</p>` : ""}
      ${item.because ? `<p class="card-meta because" title="Because you rated ${esc(item.because)}">Because you rated ${esc(item.because)}</p>` : ""}
    </article>`;
  }

  function syncCard(card) {
    const q = card.querySelector(".quick");
    if (!q) return;
    const lib = Library.items.get(card.dataset.key);
    q.classList.toggle("in", !!lib);
    q.classList.toggle("busy", !!(lib && lib.pending));
    q.setAttribute("aria-label", lib
      ? `${card.dataset.title} is in your watchlist. Edit entry`
      : `Add ${card.dataset.title} to watchlist`);
    q.title = lib ? "In your list. Click to edit." : "Add to watchlist";
  }

  function renderGrid(container, items, opts) {
    container.innerHTML = items.map((i) => cardHTML(i, opts)).join("");
    container.querySelectorAll(".card").forEach(syncCard);
  }

  function skeletons(n = 12) {
    return Array.from({ length: n }, () =>
      `<div class="card skel" aria-hidden="true"><div class="poster"></div><div class="line"></div><div class="line short"></div></div>`).join("");
  }

  // Broken poster image -> show the title instead of a broken icon.
  document.addEventListener("error", (e) => {
    const img = e.target;
    if (img.tagName === "IMG" && img.closest(".poster")) {
      const poster = img.closest(".poster");
      poster.classList.add("empty");
      img.replaceWith(document.createTextNode(img.dataset.title || ""));
    }
  }, true);

  /* Quick add / edit buttons, handled once for the whole page. */
  document.addEventListener("click", async (e) => {
    const quick = e.target.closest("[data-quick]");
    const edit = e.target.closest("[data-edit]");
    const card = (quick || edit)?.closest(".card");
    if (!card) return;
    // A double-click on "+" must not add and then open the editor: the dialog would
    // appear under the cursor and the second click would land on something inside it.
    if (quick && e.detail > 1) return;
    const k = card.dataset.key;
    const existing = Library.items.get(k);

    if (existing) {
      if (!existing.pending) Editor.open(existing);
      return;
    }
    if (!quick) return;
    const item = catalog.get(k);
    try {
      const res = await Library.add(item);
      if (res.added) {
        toast(`Added ${item.title}`, {
          action: { label: "Undo", run: () => Library.remove(res.item).catch((err) => toast(err.message, { kind: "error" })) },
        });
      }
    } catch (err) {
      toast(err.message, { kind: "error" });
    }
  });

  /* Warm the details cache when a mouse hovers a title, so the next page opens instantly. */
  const warmed = new Set();
  document.addEventListener("pointerover", (e) => {
    if (e.pointerType !== "mouse") return;
    const a = e.target.closest('a[href^="/details/"]');
    if (!a || warmed.has(a.pathname)) return;
    warmed.add(a.pathname);
    fetch(a.pathname.replace("/details/", "/api/details/")).catch(() => {});
  });

  /* ---------- Editor dialog ---------- */

  const Editor = (() => {
    const dlg = document.getElementById("editor");
    const els = {
      thumb: document.getElementById("ed-thumb"), title: document.getElementById("ed-title"),
      type: document.getElementById("ed-type"), status: document.getElementById("ed-status"),
      rating: document.getElementById("ed-rating"), review: document.getElementById("ed-review"),
      details: document.getElementById("ed-details"),
    };
    let item = null, status = null, rating = null;

    function drawStatus() {
      els.status.innerHTML = STATUSES_FOR[item.media_type].map((s) =>
        `<button type="button" class="chip" role="radio" aria-checked="${s === status}" data-v="${s}">${STATUS_LABEL[s]}</button>`).join("");
    }
    function drawRating() {
      els.rating.innerHTML = Array.from({ length: 10 }, (_, i) => i + 1).map((n) =>
        `<button type="button" role="radio" aria-checked="${n === rating}" aria-label="${n} out of 10" data-v="${n}">${n}</button>`).join("");
    }

    els.status.addEventListener("click", (e) => {
      const b = e.target.closest("[data-v]");
      if (b) { status = b.dataset.v; drawStatus(); }
    });
    els.rating.addEventListener("click", (e) => {
      const b = e.target.closest("[data-v]");
      if (b) { rating = rating === +b.dataset.v ? null : +b.dataset.v; drawRating(); }
    });
    document.getElementById("ed-clear-rating").onclick = () => { rating = null; drawRating(); };

    function close() { dlg.close(); }
    document.getElementById("ed-close").onclick = close;
    dlg.addEventListener("click", (e) => { if (e.target === dlg) close(); }); // backdrop click
    dlg.addEventListener("close", () => { document.documentElement.style.overflow = ""; });

    async function save() {
      const target = item;
      const patch = { status, rating, review: els.review.value.trim() };
      close();
      try {
        await Library.save(target, patch);
        toast("Saved");
      } catch (err) {
        toast(err.message, { kind: "error" });
      }
    }
    document.getElementById("ed-save").onclick = save;
    els.review.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) save();
    });

    document.getElementById("ed-remove").onclick = async () => {
      const target = item;
      close();
      try {
        const removed = await Library.remove(target);
        toast(`Removed ${removed.title}`, {
          action: {
            label: "Undo",
            run: () => Library.add(removed, { status: removed.status, rating: removed.rating, review: removed.review })
              .catch((err) => toast(err.message, { kind: "error" })),
          },
        });
      } catch (err) {
        toast(err.message, { kind: "error" });
      }
    };

    return {
      open(it) {
        item = it; status = it.status; rating = it.rating || null;
        els.title.textContent = it.title;
        els.type.textContent = TYPE_LABEL[it.media_type];
        if (it.poster) { els.thumb.src = it.poster; els.thumb.style.visibility = ""; }
        else els.thumb.style.visibility = "hidden";
        els.review.value = it.review || "";
        els.details.href = `/details/${it.media_type}/${it.tmdb_id}`;
        drawStatus(); drawRating();
        document.documentElement.style.overflow = "hidden";
        dlg.showModal();
      },
      get isOpen() { return dlg.open; },
    };
  })();

  /* Press / anywhere to search. */
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || Editor.isOpen) return;
    const t = e.target;
    if (t.matches("input, textarea, select") || t.isContentEditable) return;
    e.preventDefault();
    const q = document.getElementById("q");
    if (q) q.focus();
    else location.href = "/#search";
  });

  function syncAll(root = document) { root.querySelectorAll(".card[data-key]").forEach(syncCard); }

  window.MH = { esc, api, toast, Library, Editor, cardHTML, renderGrid, syncAll, skeletons, TYPE_LABEL, STATUS_LABEL, STATUSES_FOR };
})();
