/* Reading pages as an open book (screens at least 1000 px wide). Pages have one fixed size (LW x LH) that is
   scaled to fit the window, so every section paginates the same way on every screen and the page numbers
   (assets/page-map.js, made by scripts/build_page_map.py) count on through the whole book.
   The page's own markup is the book: the article, its notes and links flow into 3:4 pages (CSS
   columns), two pages show at once, and a page turn plays a 3D leaf made from the real pages,
   so links, selection, folded answers, figures, tables and code stay live. Narrow screens,
   printing, missing JavaScript, or ?layout=scroll keep the scrolling page. Progress uses the
   same storage as the scrolling reader (assets/book.js skips its own progress code in the book). */
(function () {
'use strict';
const html = document.documentElement;
const done = () => html.classList.remove('book-wait');
const main = document.querySelector('main.reading');
const wideQuery = matchMedia('(min-width: 1000px)');
if (!main || !wideQuery.matches || /[?&]layout=scroll/.test(location.search)) { done(); return; }
const article = main.querySelector(':scope > article');
if (!article) { done(); return; }
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
const PADX = 44, G = 88, LW = 560, LH = 747, BASE_FS = 13.5;
let scale = 1, shrink = 1, tight = 1, PW = 0, PH = 0, CW = 0, CH = 0, cols = 1, spread = 0, busy = false, printing = false, pendingAnchor = null;
let scaler, spreadEl, win, flow, folioEl, pctEl, meterEl, prevBtn, nextBtn, leftHead = '', rightHead = '';

/* ---------- build the book from the page's own markup ---------- */
function build() {
  const kids = [...main.children];
  const flowParts = kids.filter(el => el.matches('.chapter-status, article, .chapter-milestone, .last-updated, .page-history'));
  const toolParts = kids.filter(el => el.matches('.reader-tools, .notebook-page-header, .section-path'));
  const chip = main.querySelector('.notebook-chip');
  leftHead = (chip ? chip.textContent : 'Otahque · Django field notes').trim().toUpperCase();
  rightHead = document.title.split(' · ')[0].trim().toUpperCase();
  const bar = document.createElement('div'); bar.className = 'reader-toolbar'; bar.append(...toolParts);
  const stage = document.createElement('div'); stage.className = 'stage';
  prevBtn = document.createElement('button'); prevBtn.type = 'button'; prevBtn.className = 'side-btn'; prevBtn.setAttribute('aria-label', 'Previous pages'); prevBtn.title = 'Previous pages'; prevBtn.innerHTML = '<span aria-hidden="true">‹</span>';
  nextBtn = document.createElement('button'); nextBtn.type = 'button'; nextBtn.className = 'side-btn'; nextBtn.setAttribute('aria-label', 'Next pages'); nextBtn.title = 'Next pages'; nextBtn.innerHTML = '<span aria-hidden="true">›</span>';
  spreadEl = document.createElement('div'); spreadEl.className = 'book-spread';
  win = document.createElement('div'); win.className = 'window';
  flow = document.createElement('div'); flow.className = 'flow';
  flow.append(...flowParts);
  const slotL = document.createElement('div'); slotL.className = 'chrome-slot chrome-slot-left';
  const slotR = document.createElement('div'); slotR.className = 'chrome-slot chrome-slot-right';
  win.append(flow, slotL, slotR); spreadEl.append(win);
  scaler = document.createElement('div'); scaler.className = 'book-scaler'; scaler.append(spreadEl);
  stage.append(prevBtn, scaler, nextBtn);
  folioEl = document.createElement('p'); folioEl.className = 'folio'; folioEl.setAttribute('role', 'status'); folioEl.setAttribute('aria-live', 'polite');
  // Below the book: the resume offer (when there is one) and the page count, so nothing above the book moves it.
  const foot = document.createElement('div'); foot.className = 'book-foot';
  const banner = main.querySelector('.resume-banner'); if (banner) foot.append(banner);
  pctEl = document.createElement('span'); pctEl.className = 'folio-pct'; pctEl.setAttribute('aria-hidden', 'true');
  meterEl = document.createElement('span'); meterEl.className = 'folio-meter'; meterEl.setAttribute('aria-hidden', 'true'); meterEl.innerHTML = '<i></i>';
  foot.append(folioEl, meterEl, pctEl);
  // The report link sits under the book, not on a page of its own; the arrows replace the end-of-page links.
  const report = main.querySelector('.feedback-cta a');
  if (report) { const a = report.cloneNode(true); a.className = 'foot-report'; a.textContent = 'Report an issue'; foot.append(a); }
  main.append(bar, stage, foot);
  if (!main.querySelector('.reading-progress')) {
    const pb = document.createElement('div'); pb.className = 'reading-progress'; pb.hidden = true;
    const label = document.title.split(' · ')[0].replace(/"/g, '');
    pb.innerHTML = `<div class="reading-progress-track" role="progressbar" aria-label="Reading progress: ${label.replace(/</g, '&lt;')}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><span class="reading-progress-fill"></span></div><span class="reading-progress-label" aria-hidden="true">0%</span>`;
    main.prepend(pb);
  }
  flow.querySelectorAll('img[loading="lazy"]').forEach(img => { img.loading = 'eager'; });
  flow.querySelectorAll('details.answer-reveal').forEach(d => { d.open = true; });   // a book prints its answers   // pages far to the right must be ready when they turn in
  html.classList.add('is-book');
}
try { build(); } catch (e) { html.classList.remove('is-book'); done(); throw e; }

/* ---------- progress storage: same keys and shape as the scrolling reader ---------- */
const PROGRESS_KEY = 'otahque-progress', EDITION = 'six-part-v1';
const loadProgress = () => { try { return (JSON.parse(localStorage.getItem(PROGRESS_KEY)) || {})[EDITION] || {}; } catch (e) { return {}; } };
const saveProgress = all => { try { const s = JSON.parse(localStorage.getItem(PROGRESS_KEY)) || {}; s[EDITION] = all; localStorage.setItem(PROGRESS_KEY, JSON.stringify(s)); } catch (e) { /* storage unavailable */ } };
const key = main.dataset.progressKey || '';
const pageMap = window.OTAHQUE_PAGES || null;
const pageKey = (() => { let p = location.pathname.replace(/\/+$/, ''); if (!/\.html$/.test(p)) p += '.html'; if (!pageMap) return ''; return Object.keys(pageMap.starts).find(k => p.endsWith('/' + k)) || ''; })();
const pageBase = pageKey ? pageMap.starts[pageKey] - 1 : 0;   // pages before this one in the whole book
const saved = (key && loadProgress()[key]) || {max: 0, position: 0};
let saveTimer = null;

/* ---------- geometry ---------- */
function size() {
  // Everything in the page that is not the book (header, toolbar, foot, margins) is measured, so the book fills the rest of the window.
  const chromeH = document.body.offsetHeight - scaler.offsetHeight;
  const H = Math.max(420, innerHeight - chromeH - 5);
  const availW = document.documentElement.clientWidth - 2 * (54 + 18) - 24;   // clientWidth excludes the scrollbar
  const mult = {small: .9, large: 1.12}[html.dataset.text] || 1;               // the text-size control scales the whole page
  const fit = Math.min(1.3, availW / (2 * LW), H / LH);
  scale = Math.min(availW / (2 * LW), Math.max(.55, fit * mult));
  PW = LW; PH = LH; CW = PW - 2 * PADX; CH = PH - 58 - 52;                     // the page itself never changes size
  const fs = Math.max(11.5, BASE_FS * shrink);
  scaler.style.width = (2 * LW * scale).toFixed(1) + 'px'; scaler.style.height = (LH * scale).toFixed(1) + 'px';
  spreadEl.style.transform = `scale(${scale.toFixed(4)})`;
  const set = (k, v) => spreadEl.style.setProperty(k, v);
  set('--pw', PW + 'px'); set('--ph', PH + 'px'); set('--cw', CW + 'px'); set('--ch', CH + 'px');
  alignChrome();
  set('--reading-size', fs.toFixed(2) + 'px'); set('--rule-step', (fs * 1.62 * tight).toFixed(2) + 'px');
}
function alignChrome() {                              // the toolbar row can sit lower when a banner is above it
  const bar = main.querySelector('.reader-toolbar'), layout = main.closest('.reader-layout'); if (!bar) return;
  const r = bar.getBoundingClientRect(), mid = r.top + r.height / 2;
  const summary = document.querySelector('.book-drawer > summary'); if (summary) summary.style.top = Math.round(mid - summary.offsetHeight / 2) + 'px';
  const side = document.querySelector('.chapter-sidebar');
  if (side && layout) side.style.top = Math.round(mid - layout.getBoundingClientRect().top - side.offsetHeight / 2) + 'px';
}
addEventListener('scroll', () => alignChrome(), {passive: true});
const colOf = el => {                                // which page (column) holds an element's top
  const r = el.getBoundingClientRect(), f = flow.getBoundingClientRect();
  return Math.max(0, Math.min(cols - 1, Math.floor(((r.left - f.left) / scale + 2) / PW)));
};
const measure = () => { cols = Math.max(1, Math.round((flow.scrollWidth + G) / PW)); };
const spreads = () => Math.ceil(cols / 2);
// No section ends on a blank or nearly empty right-hand page. Lines may come a little closer (at most 10%) so a short
// tail fits the page before; the last page's content may be shared across both pages of the last spread (balance), or a
// nearly empty last page share its spread with the page before it (evenOut).
const clearBreaks = () => flow.querySelectorAll('[data-balance]').forEach(el => { el.style.breakBefore = ''; el.removeAttribute('data-balance'); });
function layout() {
  // The page map records the fit chosen when the book was built (scripts/build_page_map.py): apply it in one pass.
  const known = !/[?&]fit=search/.test(location.search) && pageMap && pageMap.fits && pageMap.fits[pageKey];
  if (known) {
    tight = known.t; clearBreaks(); layoutPages();
    const el = known.b >= 0 ? flow.querySelectorAll(BREAKABLE)[known.b] : null;
    if (el) { el.style.breakBefore = 'column'; el.setAttribute('data-balance', ''); measure(); }
    if (cols === pageMap.counts[pageKey]) { recordFit(); return; }
  }
  search(); recordFit();
}
function recordFit() {                                   // read by scripts/build_page_map.py
  const el = flow.querySelector('[data-balance]');
  html.dataset.fit = JSON.stringify({t: tight, b: el ? [...flow.querySelectorAll(BREAKABLE)].indexOf(el) : -1});
}
function search() {
  // Done when the count is even and the last page is at least a quarter full (or the last spread is shared).
  const settled = () => cols % 2 === 0 && (cols < 2 || usedOn(cols - 1) >= CH * .25);
  const attempt = () => { clearBreaks(); layoutPages(); if (settled()) return true;
    if (cols % 2) return balance() && settled(); return evenOut(); };
  for (const t of [1, .98, .96, .94, .92, .9]) { tight = t; if (attempt()) return; }
  tight = 1; clearBreaks(); layoutPages();                 // nothing fits better: plain layout, shared where possible
  if (cols % 2) balance(); else evenOut();
}
// How far down a page the content reaches (logical px): the last fragment of the book's final block, when it ends there.
function usedOn(col) {
  let el = flow.lastElementChild;
  while (el && el.lastElementChild && !/^(P|PRE|TABLE|FIGURE|UL|OL|H[1-6]|BLOCKQUOTE)$/.test(el.tagName)) el = el.lastElementChild;
  const rs = el ? el.getClientRects() : []; if (!rs.length) return CH;
  const r = rs[rs.length - 1], f = flow.getBoundingClientRect();
  if (Math.floor(((r.left - f.left) / scale + 2) / PW) !== col) return CH;
  return (r.bottom - f.top) / scale;
}
// Where a page break may go: before a block anywhere in the text (a heading or code label stays with what follows it).
const BREAKABLE = 'article p, article ul, article ol, article li, article pre, article .code-block, article .code-label, article h2, article h3, article h4, article figure, article tr, article .callout, article blockquote';
function breakTarget(el) {
  const prev = el.previousElementSibling;
  if (prev && (/^H[2-4]$/.test(prev.tagName) || prev.matches('.code-label, p.question'))) return prev;
  return el;
}
// A last spread whose right-hand page is nearly empty is shared like a printed chapter ending: a page break goes before
// the block nearest the middle of the left-hand page, so both pages of the spread end about equally full.
function evenOut() {
  if (cols < 2) return true;
  const u = usedOn(cols - 1);
  if (u > CH * .4) return true;
  const page = cols - 2, f = flow.getBoundingClientRect(), y = el => (el.getBoundingClientRect().top - f.top) / scale;
  const target = (CH + u) / 2;
  let best = null, score = Infinity;
  for (let el of flow.querySelectorAll(BREAKABLE)) {
    if (!el.getBoundingClientRect().height || colOf(el) !== page || y(el) < u + 24) continue;
    el = breakTarget(el);
    if (colOf(el) !== page || y(el) < u + 24) continue;
    const d = Math.abs(y(el) - target);
    if (d < score) { score = d; best = el; }
  }
  if (!best) return false;
  best.style.breakBefore = 'column'; best.setAttribute('data-balance', '');
  const before = cols; measure();
  if (cols !== before) { clearBreaks(); measure(); return false; }
  return true;
}
// A chapter overview is meant to be one spread: if it runs over, its text shrinks a little until it fits
// (the same on every screen, because the page size is fixed).
function layoutPages() {
  shrink = 1; size(); measure();
  if (!main.classList.contains('chapter-overview')) return;
  for (let k = 0; k < 6 && cols > 2; k++) { shrink *= .94; size(); measure(); }
  if (cols > 2) { shrink = 1; size(); measure(); }   // it cannot fit even so: keep the normal size
}
// A section that ends on a left-hand page would leave the right-hand page blank. Instead the last page's content is
// shared across both pages of the last spread: a page break goes before the block nearest the middle of that page.
function balance(page) {
  clearBreaks(); measure();
  if (cols % 2 === 0) return true;
  const last = page === undefined ? cols - 1 : page, f = flow.getBoundingClientRect(), y = el => (el.getBoundingClientRect().top - f.top) / scale;
  const onLast = [...flow.querySelectorAll(BREAKABLE)].filter(el => el.getBoundingClientRect().height > 0 && colOf(el) === last && y(el) >= 24);
  const used = Math.max(0, ...onLast.map(el => (el.getBoundingClientRect().bottom - f.top) / scale));
  let best = null, score = Infinity;
  for (let el of onLast) {
    el = breakTarget(el);                                         // a heading or label goes with what it heads
    if (colOf(el) !== last || y(el) < 24) continue;
    const d = Math.abs(y(el) - used / 2);
    if (d < score) { score = d; best = el; }
  }
  if (!best) return false;
  best.style.breakBefore = 'column'; best.setAttribute('data-balance', '');
  const before = cols; measure();
  if (cols !== before + 1) { clearBreaks(); measure(); return false; }
  return true;
}

/* ---------- page chrome (running heads, page numbers, gutter) ---------- */
function chrome(col) {
  const left = col % 2 === 0, blank = col < 0 || col >= cols;
  const lab = blank ? '' : (left ? leftHead : rightHead).replace(/</g, '&lt;');
  // The rare right-hand page that nothing can fill is a ruled page for the reader's notes, not a blank one.
  const notes = col === cols && cols % 2 === 1 ? '<span class="notes-title">Notes</span><i class="notes-lines"></i>' : '';
  return `<div class="chrome ${left ? 'chrome-left' : 'chrome-right'}${notes ? ' notes' : ''}"><span class="rh">${lab}</span>${notes}<span class="pn">${blank ? '' : pageBase + col + 1}</span><i class="gutter"></i></div>`;
}
function renderChrome() {
  win.querySelector('.chrome-slot-left').innerHTML = chrome(spread * 2);
  win.querySelector('.chrome-slot-right').innerHTML = chrome(spread * 2 + 1);
}
function face(col) {                                 // a standalone, inert copy of one page
  const el = document.createElement('div'); el.className = 'face-page'; el.style.width = PW + 'px'; el.style.height = PH + 'px';
  if (col >= 0 && col < cols) {
    const f = flow.cloneNode(true); f.className = 'flow clone';
    f.querySelectorAll('[id]').forEach(n => n.removeAttribute('id'));
    f.style.transform = `translateX(${-col * PW}px)`; el.appendChild(f);
  }
  el.insertAdjacentHTML('beforeend', chrome(col));
  el.setAttribute('inert', ''); el.setAttribute('aria-hidden', 'true'); return el;
}

/* ---------- showing a spread, progress, reading position ---------- */
const menuLinks = () => [...document.querySelectorAll('.chapter-menu nav > ol > li > a')];
function markMenu() {
  const links = menuLinks(); if (!links.length) return;
  const heads = [...flow.querySelectorAll('h2[id]')].filter(h => colOf(h) <= spread * 2 + 1);
  const cur = heads.length ? heads[heads.length - 1].id : (flow.querySelector('h2[id]') || {}).id;
  links.forEach(a => { const on = a.hash.slice(1) === cur; a.parentElement.classList.toggle('is-current', on); if (on) a.setAttribute('aria-current', 'location'); else a.removeAttribute('aria-current'); });
}
function show(k, opts = {}) {
  spread = Math.max(0, Math.min(spreads() - 1, k));
  flow.style.transform = `translateX(${-spread * 2 * PW}px)`;
  renderChrome(); markMenu();
  prevBtn.disabled = spread === 0 && !sectionPrev; nextBtn.disabled = spread >= spreads() - 1 && !sectionNext;
  const fraction = Math.min(1, (spread * 2 + 2) / cols);
  const firstPage = pageBase + spread * 2 + 1, lastPage = pageBase + Math.min(cols, spread * 2 + 2);
  folioEl.textContent = (firstPage === lastPage ? `Page ${firstPage}` : `Pages ${firstPage}–${lastPage}`) + (pageMap && pageMap.totals && pageMap.totals[pageKey] ? ` of ${pageMap.totals[pageKey]}` : '');
  html.dataset.spread = spread; html.dataset.spreads = spreads();
  pctEl.textContent = `${Math.round(fraction * 100)}% of this section read`;
  meterEl.firstChild.style.width = Math.round(fraction * 100) + '%'; meterEl.classList.toggle('is-complete', fraction >= .98);
  const bar = main.querySelector('.reading-progress');
  if (bar) {
    bar.hidden = false; const p = Math.round(fraction * 100);
    bar.querySelector('.reading-progress-fill').style.width = p + '%'; bar.querySelector('.reading-progress-label').textContent = p + '%';
    bar.querySelector('[role=progressbar]').setAttribute('aria-valuenow', p); bar.classList.toggle('is-complete', p >= 98);
    if (key && !opts.silent) {
      saved.max = Math.max(saved.max || 0, fraction); saved.position = (spread * 2) / cols; saved.updated = Date.now();
      const head = [...flow.querySelectorAll('h2[id]')].filter(h => colOf(h) <= spread * 2 + 1).pop(); saved.section = head ? head.textContent : '';
      clearTimeout(saveTimer); saveTimer = setTimeout(() => { const all = loadProgress(); all[key] = saved; saveProgress(all); }, 400);
    }
  }
}
const goToElement = (el, opts) => { if (el && flow.contains(el)) show(Math.floor(colOf(el) / 2), opts); };
function goToHash() {
  const id = decodeURIComponent(location.hash.slice(1));
  if (!id || id === 'last') return false;
  const el = document.getElementById(id);
  if (!el || !flow.contains(el)) return false;
  goToElement(el, {silent: true}); return true;
}
const lockWindow = () => { win.scrollLeft = 0; win.scrollTop = 0; };

/* ---------- the turn ---------- */
const endLinks = [...main.querySelectorAll('.chapter-end a')];
const endHref = test => { const a = endLinks.find(l => test(l.textContent.trim())); return a ? a.getAttribute('href') : ''; };
const sectionPrev = main.dataset.readerPrev || endHref(t => t.startsWith('←'));
const sectionNext = main.dataset.readerNext || endHref(t => t.endsWith('→'));
const goTo = (dest, back) => { location.href = dest + (back ? '#last' : ''); };
async function turn(dir) {
  if (busy) return;
  const target = spread + dir, boundary = target < 0 || target >= spreads();
  const dest = dir > 0 ? sectionNext : sectionPrev;
  if (boundary && !dest) return;
  if (reduce) { if (boundary) goTo(dest, dir < 0); else show(target); return; }
  busy = true;
  const parts = [];
  try {
    const L = spread * 2, R = L + 1;
    const under = document.createElement('div'); under.className = 'under ' + (dir > 0 ? 'under-left' : 'under-right');
    under.appendChild(face(dir > 0 ? L : R));
    const leaf = document.createElement('div'); leaf.className = 'leaf ' + (dir > 0 ? 'leaf-right' : 'leaf-left');
    const front = document.createElement('div'); front.className = 'leaf-face front'; front.appendChild(face(dir > 0 ? R : L));
    const back = document.createElement('div'); back.className = 'leaf-face back'; back.appendChild(face(dir > 0 ? R + 1 : L - 1));
    front.insertAdjacentHTML('beforeend', '<i class="shade"></i>'); back.insertAdjacentHTML('beforeend', '<i class="shade"></i>');
    leaf.append(front, back);
    const cast = document.createElement('i'); cast.className = 'cast ' + (dir > 0 ? 'cast-right' : 'cast-left');
    parts.push(under, cast, leaf);
    if (boundary) { const blank = document.createElement('div'); blank.className = 'under ' + (dir > 0 ? 'under-right' : 'under-left'); blank.appendChild(face(-1)); parts.unshift(blank); }
    spreadEl.append(...parts);
    if (!boundary) show(target, {});                  // the book beneath already shows the new spread
    const end = dir > 0 ? -180 : 180, opt = {duration: 1000, easing: 'cubic-bezier(.45,.05,.25,1)', fill: 'forwards'};
    front.querySelector('.shade').animate([{opacity: 0}, {opacity: .55, offset: .5}, {opacity: .55}], opt);
    back.querySelector('.shade').animate([{opacity: .55}, {opacity: .55, offset: .5}, {opacity: 0}], opt);
    cast.animate([{opacity: 0}, {opacity: .5, offset: .45}, {opacity: 0}], opt);
    await leaf.animate([{transform: 'rotateY(0deg)'}, {transform: `rotateY(${end}deg)`}], opt).finished;
  } catch (e) {
    if (!boundary) show(target, {});                  // the animation failed: still turn the page
  } finally {
    if (!boundary) { parts.forEach(p => p.remove()); busy = false; }
  }
  if (boundary) goTo(dest, dir < 0);
}

/* ---------- reflow: text size, window size, folded answers ---------- */
function repaginate(anchor) {
  const atEnd = spread >= spreads() - 1 && spreads() > 1;   // a reader at the end stays at the end
  layout();
  if (atEnd) show(spreads() - 1, {silent: true});
  else if (anchor && flow.contains(anchor)) goToElement(anchor, {silent: true}); else show(spread, {silent: true});
}
const visibleAnchor = () => {
  for (const el of flow.querySelectorAll('h2,h3,p,li,figure,pre,table,details')) { if (colOf(el) >= spread * 2) return el; }
  return null;
};
document.addEventListener('click', e => { if (e.target.closest && e.target.closest('[data-text]')) pendingAnchor = visibleAnchor(); }, true);
new MutationObserver(() => { const a = pendingAnchor; pendingAnchor = null; requestAnimationFrame(() => repaginate(a || visibleAnchor())); }).observe(html, {attributes: true, attributeFilter: ['data-text']});
flow.addEventListener('toggle', e => {               // a folded answer opened or closed: re-flow, keep it in view
  if (busy || printing || e.target.matches('.answer-reveal')) return; const d = e.target;   // answers are printed open in the book requestAnimationFrame(() => { layout(); goToElement(d, {silent: true}); });
}, true);
flow.addEventListener('focusin', e => {              // keyboard focus on a link in another page turns to it
  if (busy) return; lockWindow(); const c = Math.floor(colOf(e.target) / 2); if (c !== spread) show(c, {silent: true});
});
win.addEventListener('scroll', lockWindow);           // the window never scrolls: pages turn instead
addEventListener('hashchange', () => { if (goToHash()) { lockWindow(); scrollTo(0, 0); } });
addEventListener('beforeprint', () => { printing = true; });
addEventListener('afterprint', () => { printing = false; requestAnimationFrame(() => repaginate(visibleAnchor())); });
addEventListener('keydown', e => {
  if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || document.querySelector('dialog[open]')) return;
  const t = e.target; if (t && t.closest && t.closest('input,textarea,select,[contenteditable]')) return;
  if (e.key === 'ArrowRight') turn(1); else if (e.key === 'ArrowLeft') turn(-1);
});
prevBtn.addEventListener('click', () => turn(-1));
nextBtn.addEventListener('click', () => turn(1));
let touch = null;
spreadEl.addEventListener('touchstart', e => { touch = e.touches.length === 1 ? {x: e.touches[0].clientX, y: e.touches[0].clientY} : null; }, {passive: true});
spreadEl.addEventListener('touchend', e => {
  if (!touch || e.changedTouches.length !== 1) return;
  const dx = e.changedTouches[0].clientX - touch.x, dy = e.changedTouches[0].clientY - touch.y; touch = null;
  if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.3) turn(dx < 0 ? 1 : -1);
}, {passive: true});
let rz = null;
addEventListener('resize', () => {
  clearTimeout(rz);
  rz = setTimeout(() => { if (!wideQuery.matches) { location.reload(); return; } repaginate(visibleAnchor()); }, 150);
});

/* ---------- start ---------- */
function start() {
  layout();
  if (!goToHash()) {
    if (location.hash === '#last') show(spreads() - 1, {silent: true}); else show(0, {silent: true});
    const banner = main.querySelector('.resume-banner');
    if (banner && key && saved.position > 0.05 && saved.position < 0.98 && location.hash !== '#last') {
      banner.querySelector('.resume-text').textContent = `You read ${Math.round(saved.position * 100)}% of this page last time${saved.section ? ` (${saved.section})` : ''}.`;
      banner.hidden = false;
      banner.querySelector('[data-resume]').addEventListener('click', () => { banner.hidden = true; show(Math.floor(saved.position * cols / 2), {silent: true}); });
      banner.querySelector('[data-restart]').addEventListener('click', () => { banner.hidden = true; });
    }
  }
  layout(); show(spread, {silent: true});            // the foot may have grown (resume offer): fit the book to what is left
  lockWindow(); html.dataset.reader = 'ready'; done();
  // While this page is read, fetch the pages the arrows lead to, so the next turn across a section opens at once.
  const warm = href => {
    if (!href || !/^https?:$/.test(location.protocol)) return;
    const l = document.createElement('link'); l.rel = 'prefetch'; l.href = new URL(href, location.href).href; document.head.append(l);
  };
  (window.requestIdleCallback || (f => setTimeout(f, 800)))(() => { warm(sectionNext); warm(sectionPrev); });
  const imgs = [...flow.querySelectorAll('img')].filter(img => !img.complete);
  imgs.forEach(img => img.addEventListener('load', () => { if (!busy) { layout(); show(spread, {silent: true}); } }, {once: true}));
  Promise.all([fontsReady, ...imgs.map(img => new Promise(r => { img.addEventListener('load', r, {once: true}); img.addEventListener('error', r, {once: true}); }))])
    .then(() => { html.dataset.pages = cols; }, () => { html.dataset.pages = cols; });
}
// Start at once (the web fonts can take seconds on a slow connection): wait for them only briefly,
// then pages are measured again, keeping the reader's place, when they arrive.
// document.fonts.ready can resolve before the fonts are even requested, so ask for the faces the book uses.
const faces = ['400 16px Inter', '500 16px Inter', '500 24px Caveat', '600 24px Caveat', '400 12px "DM Mono"', '500 12px "DM Mono"'];
const fontsReady = document.fonts && document.fonts.load
  ? Promise.all(faces.map(f => document.fonts.load(f).catch(() => []))).then(() => document.fonts.ready)
  : Promise.resolve();
if (document.fonts && document.fonts.addEventListener) document.fonts.addEventListener('loadingdone', () => { if (started && !busy && !printing) repaginate(visibleAnchor()); });
let started = false;
const begin = () => { if (started) return; started = true; start(); };
Promise.race([fontsReady, new Promise(r => setTimeout(r, 250))]).then(begin, begin);
fontsReady.then(() => { if (started) repaginate(visibleAnchor()); else begin(); }, () => {});
})();
