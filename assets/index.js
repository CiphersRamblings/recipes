(() => {
  const cards = [...document.querySelectorAll(".card")];
  const q = document.getElementById("q");
  const chips = document.getElementById("chips");
  const count = document.getElementById("count");
  const empty = document.getElementById("empty");
  const spinBtn = document.getElementById("spin");
  const spinLabel = document.getElementById("spin-label");
  let tag = "";

  // ---------- search + tag filter
  function apply() {
    const terms = q.value.toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const c of cards) {
      const okTag = !tag || c.dataset.tags.split("|").includes(tag);
      const okText = terms.every(t => c.dataset.search.includes(t));
      c.hidden = !(okTag && okText);
      if (!c.hidden) shown++;
    }
    const filtered = tag || terms.length;
    count.textContent = filtered ? `${shown} of ${cards.length} recipes` : `${cards.length} recipes`;
    empty.hidden = shown > 0 || !cards.length;
    spinLabel.textContent = tag ? `Surprise me: ${tag}` : filtered ? "Pick one of these" : "What should I make?";
  }

  function setTag(t) {
    tag = t;
    chips.querySelectorAll(".chip").forEach(b => b.classList.toggle("is-on", b.dataset.tag === t));
    history.replaceState(null, "", t ? "#tag=" + encodeURIComponent(t) : location.pathname);
    apply();
  }

  chips.addEventListener("click", ev => {
    const b = ev.target.closest(".chip");
    if (b) setTag(b.dataset.tag === tag ? "" : b.dataset.tag);
  });
  q.addEventListener("input", apply);
  const m = location.hash.match(/^#tag=(.+)$/);
  m ? setTag(decodeURIComponent(m[1])) : apply();

  // ---------- randomizer
  const dlg = document.getElementById("picker");
  const title = document.getElementById("pick-title");
  const meta = document.getElementById("pick-meta");
  const desc = document.getElementById("pick-desc");
  const go = document.getElementById("pick-go");
  const again = document.getElementById("pick-again");
  let last = null, spinning = false;

  function pool() {
    const visible = cards.filter(c => !c.hidden);
    return visible.length ? visible : cards;
  }

  function spin() {
    const p = pool();
    if (!p.length || spinning) return;
    spinning = true;
    if (!dlg.open) dlg.showModal();
    const choices = p.length > 1 ? p.filter(c => c !== last) : p;
    const winner = choices[Math.floor(Math.random() * choices.length)];
    last = winner;
    const calm = matchMedia("(prefers-reduced-motion: reduce)").matches || p.length < 2;
    const ticks = calm ? 0 : 16;
    dlg.classList.add("is-spinning");
    let i = 0;
    (function tick() {
      if (i < ticks) {
        title.textContent = p[Math.floor(Math.random() * p.length)].dataset.title;
        i++;
        setTimeout(tick, 30 + i * i * 1.1);
      } else {
        title.textContent = winner.dataset.title;
        meta.textContent = winner.dataset.meta;
        desc.textContent = winner.dataset.desc;
        go.href = winner.getAttribute("href");
        dlg.classList.remove("is-spinning");
        spinning = false;
        go.focus();
      }
    })();
  }

  spinBtn.addEventListener("click", spin);
  again.addEventListener("click", spin);
  document.getElementById("pick-close").addEventListener("click", () => dlg.close());
  dlg.addEventListener("click", ev => { if (ev.target === dlg && !spinning) dlg.close(); });
  document.addEventListener("keydown", ev => {
    if (ev.key.toLowerCase() === "r" && document.activeElement !== q && !dlg.open &&
        !ev.metaKey && !ev.ctrlKey && !ev.altKey) spin();
  });
})();
