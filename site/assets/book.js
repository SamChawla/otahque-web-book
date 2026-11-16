// Progressive enhancement: the complete book and navigation work without JavaScript.

const bookDrawer = document.querySelector('#book-drawer');
if (bookDrawer) {
  const narrow = matchMedia('(max-width: 960px)');
  const syncDrawer = () => {
    try {
      const saved = localStorage.getItem('otahque-sidebar-v3');
      bookDrawer.open = saved === 'open';
    } catch (e) { bookDrawer.open = false; }
  };
  syncDrawer();
  narrow.addEventListener('change', syncDrawer);
  bookDrawer.addEventListener('toggle', () => {
    if (!narrow.matches) {
      try { localStorage.setItem('otahque-sidebar-v3', bookDrawer.open ? 'open' : 'closed'); } catch (e) {}
    }
  });
  bookDrawer.addEventListener('keydown', event => {
    if (event.key === 'Escape' && bookDrawer.open) {
      bookDrawer.open = false;
      bookDrawer.querySelector(':scope > summary').focus();
    }
  });
}

const fullContents = document.querySelector('details#contents');
if (fullContents && location.hash === '#contents') fullContents.open = true;
addEventListener('hashchange', () => {
  if (fullContents && location.hash === '#contents') fullContents.open = true;
});

// Chapters were once single pages; forward old links (chapter03.html#section-3-2 or a topic
// anchor) to the section page that now holds that place.
const moved = location.hash && document.querySelector('[data-moved-anchors]');
if (moved) {
  const id = decodeURIComponent(location.hash.slice(1));
  const entry = [...moved.querySelectorAll('[data-anchors]')].find(li => li.dataset.anchors.split(' ').includes(id));
  if (entry) location.replace(entry.querySelector('a').href + (id.startsWith('section-') ? '' : '#' + id));
}

// Notebook page turns use links as the fallback, with a short slide for pointer,
// touch, and keyboard navigation when JavaScript is available.
const readerPage = document.querySelector('.reading[data-reader-prev]');
if (readerPage) {
  const previous = readerPage.querySelector('.page-thumb-prev');
  const next = readerPage.querySelector('.page-thumb-next');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  let navigating = false;
  const turnPage = direction => {
    if (navigating) return;
    const target = direction < 0 ? previous : next;
    if (!target || !target.href) return;
    navigating = true;
    if (reducedMotion.matches) {
      location.assign(target.href);
      return;
    }
    readerPage.classList.add(direction < 0
      ? 'reader-page-shift-prev' : 'reader-page-shift-next');
    setTimeout(() => location.assign(target.href), 170);
  };
  [previous, next].filter(Boolean).forEach(link => {
    link.addEventListener('click', event => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey ||
          event.shiftKey || event.altKey) return;
      event.preventDefault();
      turnPage(link === previous ? -1 : 1);
    });
  });
  document.addEventListener('keydown', event => {
    const tag = event.target?.tagName;
    if (event.defaultPrevented || event.altKey || event.ctrlKey ||
        event.metaKey || event.shiftKey ||
        ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(tag) ||
        event.target?.isContentEditable ||
        document.querySelector('dialog[open]')) return;
    if (event.key === 'ArrowLeft') turnPage(-1);
    if (event.key === 'ArrowRight') turnPage(1);
  });
  let touchStart = null;
  readerPage.addEventListener('touchstart', event => {
    if (event.touches.length === 1) {
      touchStart = {x: event.touches[0].clientX,
        y: event.touches[0].clientY};
    }
  }, {passive: true});
  readerPage.addEventListener('touchend', event => {
    if (!touchStart || event.changedTouches.length !== 1) return;
    const dx = event.changedTouches[0].clientX - touchStart.x;
    const dy = event.changedTouches[0].clientY - touchStart.y;
    touchStart = null;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.3) {
      turnPage(dx < 0 ? 1 : -1);
    }
  }, {passive: true});
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

// Copy buttons on code listings, so long commands need not be selected by hand on a phone.
if (navigator.clipboard) {
  document.querySelectorAll('.reading pre.code-listing').forEach(pre => {
    const wrap = document.createElement('div');
    wrap.className = 'code-block';
    pre.before(wrap);
    wrap.append(pre);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'copy-code';
    button.textContent = 'Copy';
    button.setAttribute('aria-label', 'Copy this listing');
    let reset = null;
    button.addEventListener('click', () => {
      navigator.clipboard.writeText(pre.textContent).then(() => {
        button.textContent = 'Copied';
      }, () => {
        button.textContent = 'Select and copy';
      }).finally(() => {
        clearTimeout(reset);
        reset = setTimeout(() => { button.textContent = 'Copy'; }, 2000);
      });
    });
    wrap.append(button);
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
// Keep earlier section progress intact, but do not apply it to different content.
const PROGRESS_EDITION = 'six-part-v1';
const loadProgress = () => {
  try { return (JSON.parse(localStorage.getItem(PROGRESS_KEY)) || {})[PROGRESS_EDITION] || {}; } catch (e) { return {}; }
};
const saveProgress = all => {
  try {
    const saved = JSON.parse(localStorage.getItem(PROGRESS_KEY)) || {};
    saved[PROGRESS_EDITION] = all;
    localStorage.setItem(PROGRESS_KEY, JSON.stringify(saved));
  } catch (e) { /* storage unavailable */ }
};

const bookResume = document.querySelector('[data-book-resume]');
if (bookResume) {
  const recent = Object.entries(loadProgress())
    .filter(([key, value]) => /^chapter\d+:\d+\.\d+$/.test(key) && value.updated)
    .sort((a, b) => b[1].updated - a[1].updated)[0];
  if (recent) {
    const [chapter, section] = recent[0].split(':');
    bookResume.href = `${bookResume.dataset.prefix}chapters/${chapter}/section-${section.replace('.', '-')}.html`;
    bookResume.textContent = 'Resume reading →';
  }
}

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
  const measure = () => {
    const box = article.getBoundingClientRect();
    const articleScroll = box.height - window.innerHeight;
    if (articleScroll <= 1) {
      const pageScroll = document.documentElement.scrollHeight - window.innerHeight;
      return pageScroll <= 0 ? 1 : window.scrollY / pageScroll;
    }
    return Math.max(0, Math.min(1, -box.top / articleScroll));
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
      close();
      requestAnimationFrame(() => {
        const box = article.getBoundingClientRect();
        const articleScroll = box.height - window.innerHeight;
        const pageScroll = document.documentElement.scrollHeight - window.innerHeight;
        const target = articleScroll <= 1
          ? saved.position * pageScroll
          : window.scrollY + box.top + saved.position * articleScroll;
        window.scrollTo({ top: Math.max(0, target) });
      });
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
      saveProgress({});
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
