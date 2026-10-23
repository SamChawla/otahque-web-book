// Progressive enhancement: the complete book and navigation work without JavaScript.

// Chapters were once single pages; forward old links (chapter03.html#section-3-2 or a topic
// anchor) to the section page that now holds that place.
const moved = location.hash && document.querySelector('[data-moved-anchors]');
if (moved) {
  const id = decodeURIComponent(location.hash.slice(1));
  const entry = [...moved.querySelectorAll('[data-anchors]')].find(li => li.dataset.anchors.split(' ').includes(id));
  if (entry) location.replace(entry.querySelector('a').href + (id.startsWith('section-') ? '' : '#' + id));
}

// Contents filter: match titles or a chapter number; hide stage headings with no matches.
const search = document.querySelector('#chapter-search');
if (search) {
  document.querySelector('.filter').hidden = false;
  const items = [...document.querySelectorAll('.book-toc > li')];
  const status = document.querySelector('#search-status');
  search.addEventListener('input', () => {
    const query = search.value.trim().toLocaleLowerCase();
    let count = 0;
    let stage = null;
    let stageHasMatch = false;
    const closeStage = () => { if (stage) stage.hidden = !stageHasMatch; };
    for (const item of items) {
      if (item.hasAttribute('data-stage')) {
        closeStage();
        stage = item;
        stageHasMatch = !query;
        continue;
      }
      const matches = !query || (/^\d+$/.test(query)
        ? Number(item.dataset.chapter) === Number(query)
        : item.textContent.toLocaleLowerCase().includes(query));
      item.hidden = !matches;
      if (matches) { count++; stageHasMatch = true; }
    }
    closeStage();
    status.hidden = !query;
    status.textContent = count ? `${count} matching chapter${count === 1 ? '' : 's'}.` : 'No matching chapters. Try another title or number.';
  });
}

document.querySelectorAll('[data-print]').forEach(button => {
  button.hidden = false;
  button.addEventListener('click', () => window.print());
});

// Printing shows every answer; folded answers are closed again afterwards.
let foldedAnswers = [];
addEventListener('beforeprint', () => {
  foldedAnswers = [...document.querySelectorAll('details.answer-reveal:not([open])')];
  foldedAnswers.forEach(d => { d.open = true; });
});
addEventListener('afterprint', () => { foldedAnswers.forEach(d => { d.open = false; }); foldedAnswers = []; });

// Reading text size: three steps, remembered per browser when storage is available.
const sizes = ['small', 'normal', 'large'];
document.querySelectorAll('.text-size').forEach(group => {
  group.hidden = false;
  group.addEventListener('click', event => {
    const button = event.target.closest('[data-text]');
    if (!button) return;
    const root = document.documentElement;
    const current = sizes.indexOf(root.dataset.text || 'normal');
    const next = sizes[Math.max(0, Math.min(sizes.length - 1, current + (button.dataset.text === 'larger' ? 1 : -1)))];
    root.dataset.text = next;
    try { localStorage.setItem('otahque-text', next); } catch (e) { /* storage unavailable */ }
  });
});

// Sidebar: open on wide screens, mark the section being read, and show only its topics.
const menu = document.querySelector('.chapter-menu');
if (menu) {
  const compact = window.matchMedia('(max-width: 960px)');
  const syncMenu = () => { menu.open = !compact.matches; };
  syncMenu();
  compact.addEventListener('change', syncMenu);
  const sectionLinks = [...menu.querySelectorAll('nav > ol > li > a')];
  const headings = sectionLinks.map(link => document.getElementById(link.hash.slice(1))).filter(Boolean);
  const mark = id => {
    sectionLinks.forEach(link => {
      const current = link.hash.slice(1) === id;
      link.parentElement.classList.toggle('is-current', current);
      if (current) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  };
  const update = () => {
    let current = headings[0];
    for (const heading of headings) {
      if (heading.getBoundingClientRect().top < window.innerHeight * 0.3) current = heading;
    }
    if (current) mark(current.id);
  };
  let pending = false;
  window.addEventListener('scroll', () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; update(); });
  }, { passive: true });
  window.addEventListener('hashchange', update);
  update();
}

// Reading progress: a bar at the top of each reading page, saved in this browser only.
// Storage holds { key: { max, position, section, updated } }; every access tolerates
// private browsing or blocked storage, in which case the bar still works for this visit.
const PROGRESS_KEY = 'otahque-progress';
const loadProgress = () => {
  try { return JSON.parse(localStorage.getItem(PROGRESS_KEY)) || {}; } catch (e) { return {}; }
};
const saveProgress = all => {
  try { localStorage.setItem(PROGRESS_KEY, JSON.stringify(all)); } catch (e) { /* storage unavailable */ }
};

const reading = document.querySelector('[data-progress-key]');
if (reading) {
  const key = reading.dataset.progressKey;
  const article = reading.querySelector('article');
  const bar = reading.querySelector('.reading-progress');
  const track = bar.querySelector('[role="progressbar"]');
  const fill = bar.querySelector('.reading-progress-fill');
  const label = bar.querySelector('.reading-progress-label');
  const sections = [...article.querySelectorAll('h2[id]')];
  bar.hidden = false;
  const all = loadProgress();
  const saved = all[key] || { max: 0, position: 0 };

  // 0% with the article's start at the top of the screen; 100% when its end comes into view.
  const scrollable = box => Math.max(1, box.height - window.innerHeight);
  const measure = () => {
    const box = article.getBoundingClientRect();
    return Math.max(0, Math.min(1, -box.top / scrollable(box)));
  };
  const currentSection = () => {
    let current = sections[0];
    for (const heading of sections) if (heading.getBoundingClientRect().top < window.innerHeight * 0.3) current = heading;
    return current ? current.textContent : '';
  };
  const render = fraction => {
    const percent = Math.round(fraction * 100);
    fill.style.width = percent + '%';
    label.textContent = percent + '%';
    track.setAttribute('aria-valuenow', String(percent));
    bar.classList.toggle('is-complete', percent >= 98);
  };
  let timer = null;
  const update = () => {
    const fraction = measure();
    render(fraction);
    saved.max = Math.max(saved.max || 0, fraction);
    saved.position = fraction;
    saved.section = currentSection();
    saved.updated = Date.now();
    clearTimeout(timer);
    timer = setTimeout(() => { const latest = loadProgress(); latest[key] = saved; saveProgress(latest); }, 400);
  };

  // Offer to resume when returning part-way through, unless a link already chose a place.
  const banner = reading.querySelector('.resume-banner');
  const returning = saved.position > 0.05 && saved.position < 0.98 && !window.location.hash;
  if (returning) {
    banner.querySelector('.resume-text').textContent = `You read ${Math.round(saved.position * 100)}% of this page last time${saved.section ? ` (${saved.section})` : ''}.`;
    banner.hidden = false;
    const close = () => { banner.hidden = true; };
    banner.querySelector('[data-resume]').addEventListener('click', () => {
      const box = article.getBoundingClientRect();
      const target = window.scrollY + box.top + saved.position * scrollable(box);
      window.scrollTo({ top: Math.max(0, target) });
      close();
    });
    banner.querySelector('[data-restart]').addEventListener('click', close);
  }

  let pending = false;
  window.addEventListener('scroll', () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; update(); });
  }, { passive: true });
  window.addEventListener('resize', update);
  // Render without saving on load, so merely opening a page does not overwrite a saved position.
  render(measure());
}

// Contents and chapter pages: show saved progress. A chapter's progress is the average of
// its section pages (data-progress-parts); a section shows its own.
const tiles = document.querySelectorAll('[data-progress-for]');
if (tiles.length) {
  const all = loadProgress();
  let any = false;
  tiles.forEach(tile => {
    const parts = tile.dataset.progressParts ? tile.dataset.progressParts.split(' ') : null;
    const entry = parts
      ? { max: parts.reduce((sum, part) => sum + ((all[part] || {}).max || 0), 0) / parts.length }
      : all[tile.dataset.progressFor];
    if (!entry || !(entry.max > 0.02)) return;
    any = true;
    const percent = Math.round(entry.max * 100);
    tile.hidden = false;
    tile.querySelector('.tile-progress-fill').style.width = percent + '%';
    tile.querySelector('.tile-progress-label').textContent = percent >= 98 ? 'Read ✓' : `${percent}% read`;
    tile.classList.toggle('is-complete', percent >= 98);
  });
  const note = document.querySelector('.progress-note');
  if (note && any) {
    note.hidden = false;
    note.querySelector('[data-reset-progress]').addEventListener('click', () => {
      try { localStorage.removeItem(PROGRESS_KEY); } catch (e) { /* storage unavailable */ }
      tiles.forEach(tile => { tile.hidden = true; });
      note.hidden = true;
    });
  }
}

// Figure viewer: open figures over the page instead of leaving it. The link to the image
// file remains the no-JavaScript fallback. Esc, the close button, or the backdrop closes it;
// arrow keys move between figures; focus returns to the figure that opened it.
const figureLinks = [...document.querySelectorAll('.reading figure > a[href]')];
if (figureLinks.length && typeof HTMLDialogElement === 'function') {
  const viewer = document.createElement('dialog');
  viewer.className = 'figure-viewer';
  viewer.setAttribute('aria-label', 'Figure viewer');
  viewer.innerHTML = '<div class="viewer-bar"><span class="viewer-count"></span><span class="viewer-buttons">'
    + '<button type="button" data-step="-1" aria-label="Previous figure">‹</button>'
    + '<button type="button" data-step="1" aria-label="Next figure">›</button>'
    + '<button type="button" data-close aria-label="Close figure">×</button></span></div>'
    + '<div class="viewer-image"><img alt=""></div><p class="viewer-hint">Swipe sideways to see the whole figure.</p><p class="viewer-caption"></p>';
  document.body.append(viewer);
  const image = viewer.querySelector('img');
  const caption = viewer.querySelector('.viewer-caption');
  const count = viewer.querySelector('.viewer-count');
  let index = 0;
  let opener = null;
  let savedScroll = 0;
  const show = i => {
    index = (i + figureLinks.length) % figureLinks.length;
    const link = figureLinks[index];
    const source = link.querySelector('img');
    image.src = link.href;
    image.alt = source ? source.alt : '';
    const figcaption = link.closest('figure').querySelector('figcaption');
    caption.textContent = figcaption ? figcaption.textContent : '';
    count.textContent = `Figure ${index + 1} of ${figureLinks.length} on this page`;
    viewer.querySelectorAll('[data-step]').forEach(b => { b.hidden = figureLinks.length < 2; });
    viewer.querySelector('.viewer-image').scrollLeft = 0;
  };
  figureLinks.forEach((link, i) => link.addEventListener('click', event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return; // keep "open in new tab"
    event.preventDefault();
    opener = link;
    savedScroll = window.scrollY;
    show(i);
    viewer.showModal();
  }));
  viewer.addEventListener('click', event => {
    if (event.target === viewer || event.target.closest('[data-close]')) viewer.close();
    const step = event.target.closest('[data-step]');
    if (step) show(index + Number(step.dataset.step));
  });
  viewer.addEventListener('keydown', event => {
    if (event.key === 'ArrowRight') show(index + 1);
    if (event.key === 'ArrowLeft') show(index - 1);
  });
  viewer.addEventListener('close', () => {
    image.removeAttribute('src');
    if (opener) opener.focus({ preventScroll: true });
    window.scrollTo({ top: savedScroll, behavior: 'instant' });
  });
}
