// Presentation only. The Sequences page re-renders its strip and its sequence list every 250 ms by
// replacing innerHTML, which would restart any CSS animation and skip every width transition. This
// file watches those two containers and (1) plays the landing animation once per newly recognised
// pose, continuing it across re-renders, and (2) lets each progress bar grow from its previous value.
// It reads the DOM only; it never touches the page's state, requests or timers. Safe to remove.
(() => {
  const seen = document.getElementById('seen'), seqs = document.getElementById('seqs');
  if (!seen || !seqs || !window.MutationObserver) return;
  const LAND = 320;                      // ms, matches cell-land in wordless.css
  let born = [];                         // when the cell at each strip position first appeared

  new MutationObserver(() => {
    const cells = seen.querySelectorAll(':scope > .sign'), now = performance.now();
    if (seen.querySelector(':scope > .match, :scope > .wrong, :scope > .missing, :scope > .extra')) { born = []; return; }  // scored strip: CSS staggers it
    born.length = Math.min(born.length, cells.length);
    while (born.length < cells.length) born.push(now);
    cells.forEach((c, i) => {
      const age = now - born[i];
      if (age >= LAND) return;
      for (const el of [c, c.previousElementSibling]) {
        if (!el || (el !== c && !el.classList.contains('arrow'))) continue;
        el.classList.add('land'); el.style.animationDelay = -age + 'ms';
      }
    });
  }).observe(seen, {childList: true});

  let prev = {};                         // sequence id -> last bar width
  new MutationObserver(() => {
    const next = {};
    seqs.querySelectorAll('.seq').forEach(row => {
      const key = row.querySelector('[data-show]'), bar = row.querySelector('.bar i');
      if (!key || !bar) return;
      const id = key.dataset.show, to = bar.style.width, from = prev[id];
      next[id] = to;
      if (from !== undefined && from !== to) { bar.style.width = from; bar.getBoundingClientRect(); bar.style.width = to; }
    });
    prev = next;
  }).observe(seqs, {childList: true});
})();
