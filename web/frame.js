(() => {
  // The screen's short edge, which a browser toolbar or a fullscreen toggle cannot change.
  // Everything sized "per vmin" hangs off this instead, so controls keep one size for the
  // life of the page. Only a genuine rotation moves it.
  function pinControlScale() {
    const short = Math.min(screen.width || 0, screen.height || 0)
      || Math.min(innerWidth, innerHeight);
    document.documentElement.style.setProperty('--stable-vmin', short + 'px');
  }
  pinControlScale();
  addEventListener('orientationchange', () => setTimeout(pinControlScale, 200));

  const layers = [...document.querySelectorAll('.layer')];
  const status = document.getElementById('status');
  const statusText = document.getElementById('status-text');
  const clock = document.getElementById('clock');
  const pathLabel = document.getElementById('path');

  /* ---- words --------------------------------------------------------------
   *
   *  The frame keeps its own catalogue rather than being sent one. It changes language
   *  from the settings poll, with no reload, and must be able to say "reconnecting" while
   *  the server is exactly what it cannot reach. The server's own two pages are
   *  translated in photoframe/i18n.py; the two catalogues barely overlap.
   */
  const TEXT = {
    es: {
      months: ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
               'jul', 'ago', 'sep', 'oct', 'nov', 'dic'],
      smaller: 'mostrando versiones reducidas',
      reconnecting: 'reconectando…',
      preparing: 'preparando la biblioteca…',
      noPhotos: 'no hay fotos',
      nothingToShow: 'no hay fotos que mostrar',
      undo: 'Deshacer',
      unreadable: 'no se ha podido leer esta foto',
      hideFolder: folder => `Ocultar ${folder}`,
      hidden: (entry, count) => `Oculta ${entry} · ${count} foto${count === 1 ? '' : 's'}`,
      hideFailed: 'no se ha podido ocultar',
      restored: entry => `Restaurada ${entry}`,
      offline: 'no se ha podido contactar con el servidor',
      exitFullscreen: 'Pulsa F11 para salir de pantalla completa',
      fullscreenDenied: 'pantalla completa denegada',
      pathCopied: 'Ruta copiada',
      pathNotCopied: 'No se ha podido copiar la ruta',
      favorited: 'Añadida a favoritas',
      unfavorited: 'Quitada de favoritas',
      libraryRoot: 'raíz de la biblioteca',
      folderCount: (folder, total) => `${folder} · ${total} foto${total === 1 ? '' : 's'}`,
      folderFailed: 'no se ha podido cargar la carpeta',
      detailsFailed: 'no se han podido leer los detalles',
      noDetails: 'esta foto no tiene datos registrados',
      'row.date': 'Fecha',
      'row.size': 'Tamaño',
      'row.weight': 'Peso',
      'row.camera': 'Cámara',
      'row.lens': 'Objetivo',
      'row.exposure': 'Parámetros',
      'row.place': 'Ubicación',
      'row.altitude': 'Altitud',
      'row.people': 'Personas',
      'row.tags': 'Etiquetas',
      'row.path': 'Ruta',
      'ui.fullscreen': 'Pantalla completa',
      'ui.fullscreenAria': 'Alternar pantalla completa',
      'ui.favorite': 'Favorita',
      'ui.favoriteAdd': 'Añadir a favoritas',
      'ui.favoriteRemove': 'Quitar de favoritas',
      'ui.more': 'Más',
      'ui.moreAria': 'Más opciones',
      'ui.close': 'Cerrar',
      'ui.rowUp': 'Fila anterior',
      'ui.rowDown': 'Fila siguiente',
      'ui.hide': 'Ocultar',
      'menu.hidePhoto': 'Ocultar esta foto',
      'menu.gallery': 'Fotos cercanas',
      'menu.info': 'Información',
      'menu.settings': 'Ajustes',
      'menu.cancel': 'Cancelar',
      'edge.prev': 'Anterior',
      'edge.unfavorite': 'Quitar',
      'ui.title': 'Marco de fotos',
      'edge.next': 'Siguiente',
      'info.aria': 'Información de la foto',
      'gphotos': 'Google Fotos',
    },
    en: {
      months: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
      smaller: 'showing smaller versions',
      reconnecting: 'reconnecting…',
      preparing: 'preparing the library…',
      noPhotos: 'no photos',
      nothingToShow: 'nothing to show',
      undo: 'Undo',
      unreadable: 'could not read this photo',
      hideFolder: folder => `Hide ${folder}`,
      hidden: (entry, count) => `Hidden ${entry} · ${count} photo${count === 1 ? '' : 's'}`,
      hideFailed: 'could not hide that',
      restored: entry => `Restored ${entry}`,
      offline: 'could not reach the server',
      exitFullscreen: 'Press F11 to leave fullscreen',
      fullscreenDenied: 'fullscreen refused',
      pathCopied: 'Path copied',
      pathNotCopied: 'Could not copy the path',
      favorited: 'Added to favourites',
      unfavorited: 'Removed from favourites',
      libraryRoot: 'the library root',
      folderCount: (folder, total) => `${folder} · ${total} photo${total === 1 ? '' : 's'}`,
      folderFailed: 'could not load the folder',
      detailsFailed: 'could not read the details',
      noDetails: 'nothing was recorded about this photo',
      'row.date': 'Date',
      'row.size': 'Size',
      'row.weight': 'Weight',
      'row.camera': 'Camera',
      'row.lens': 'Lens',
      'row.exposure': 'Exposure',
      'row.place': 'Place',
      'row.altitude': 'Altitude',
      'row.people': 'People',
      'row.tags': 'Tags',
      'row.path': 'Path',
      'ui.fullscreen': 'Fullscreen',
      'ui.fullscreenAria': 'Toggle fullscreen',
      'ui.favorite': 'Favourite',
      'ui.favoriteAdd': 'Add to favourites',
      'ui.favoriteRemove': 'Remove from favourites',
      'ui.more': 'More',
      'ui.moreAria': 'More options',
      'ui.close': 'Close',
      'ui.rowUp': 'Previous row',
      'ui.rowDown': 'Next row',
      'ui.hide': 'Hide',
      'menu.hidePhoto': 'Hide this photo',
      'menu.gallery': 'Nearby photos',
      'menu.info': 'Information',
      'menu.settings': 'Settings',
      'menu.cancel': 'Cancel',
      'edge.prev': 'Previous',
      'edge.unfavorite': 'Remove',
      'ui.title': 'Photo frame',
      'edge.next': 'Next',
      'info.aria': 'Photo information',
      'gphotos': 'Google Photos',
    },
  };

  // This device may speak something other than the frame does. The server renders the
  // page in it, so the markup already says which — but read the cookie too, because the
  // settings poll must not undo a choice made on this screen.
  const deviceLang = () => (document.cookie.match(/(?:^|;\s*)frame_lang=([a-z]{2})/) || [])[1] || '';

  let lang = deviceLang() || (document.documentElement.lang === 'en' ? 'en' : 'es');

  /** One string. Missing keys fall back to Spanish, then to the key, so a half-translated
   *  catalogue shows the key rather than `undefined` on the wall. */
  function t(key, ...values) {
    const word = TEXT[lang][key] ?? TEXT.es[key] ?? key;
    return typeof word === 'function' ? word(...values) : word;
  }

  /** Write the catalogue into the page. `data-t` sets the text, `data-t-title` the
   *  tooltip, `data-t-aria` the label. Templates are walked too: their contents are
   *  cloned long after this runs. */
  function applyTo(root) {
    for (const node of root.querySelectorAll('[data-t]')) node.textContent = t(node.dataset.t);
    for (const node of root.querySelectorAll('[data-t-title]')) node.title = t(node.dataset.tTitle);
    for (const node of root.querySelectorAll('[data-t-aria]')) {
      node.setAttribute('aria-label', t(node.dataset.tAria));
    }
  }

  function applyLanguage() {
    document.documentElement.lang = lang;
    applyTo(document);
    for (const template of document.querySelectorAll('template')) applyTo(template.content);
    if (currentId) showHeart(isFavorite);   // its label is one of the translated ones
  }

  // Ask for exactly the pixels this screen paints, and no more. A 24 MP original costs
  // roughly 96 MB of decoded bitmap; the same photo at panel size costs about 8 MB, and
  // two of those are alive at once during a crossfade. The server crops and encodes per
  // request and keeps nothing on disk.
  const panel = () => {
    const scale = Math.min(devicePixelRatio || 1, 2);  // beyond 2x is invisible here
    const w = Math.round((innerWidth || screen.width || 1920) * scale);
    const h = Math.round((innerHeight || screen.height || 1080) * scale);
    return { w: Math.max(64, w), h: Math.max(64, h) };
  };
  /** Whether this device can just be handed the original AVIF.
   *
   *  Re-encoding exists for the wall device: a low-powered 4-core machine with 4 GB,
   *  where a 24 MP
   *  original is ~96 MB of decoded bitmap and two are alive at once mid-crossfade. Every
   *  other device here — the phones, the PC — decodes one without noticing, and handing
   *  over the file as it sits costs the server no decode, no JPEG encode, no temp file
   *  and no SSD write. It also shows the photo at full quality instead of a re-encode.
   *
   *  Biased towards re-encoding: getting this wrong on a capable device only means a
   *  smaller image, while getting it wrong on the device is the frame falling over. So
   *  originals need positive evidence of a capable machine, not merely the absence of
   *  evidence against one. `?full=1` and `?full=0` force it either way and are
   *  remembered, for when the guess is wrong.
   */
  function wantsOriginals() {
    let stored = null;
    try {
      const forced = new URLSearchParams(location.search).get('full');
      if (forced !== null) localStorage.setItem('frameFull', forced === '1' ? '1' : '0');
      stored = localStorage.getItem('frameFull');
    } catch { /* private mode, or storage disabled: fall through to the guess */ }
    if (stored !== null) return stored === '1';
    // The device reports 4 and 4. The phone and the PC report 8 or more.
    return (navigator.hardwareConcurrency || 0) >= 6 || (navigator.deviceMemory || 0) >= 6;
  }

  let originals = wantsOriginals();

  /** Give up on originals for good on this device.
   *
   *  The capability guess is only a guess, and getting it wrong on the device is not a
   *  slightly worse picture -- it is a 24 MP decode the device cannot do, a photo that
   *  never loads, and a frame that skips silently to the next one. Whole cameras vanish
   *  that way: the big files all fail and only phone photos ever reach the screen.
   *  So the first failure that a smaller render could explain settles it, permanently.
   */
  function demoteFromOriginals() {
    if (!originals) return false;
    originals = false;
    try { localStorage.setItem('frameFull', '0'); } catch { /* storage disabled */ }
    return true;
  }

  // Measured per request, not cached: entering or leaving fullscreen changes the
  // viewport without any reload, and the very next photo must arrive at the new size.
  const src = id => {
    if (originals) return `/img/${id}`;
    const { w, h } = panel();
    return `/img/${id}?w=${w}&h=${h}`;
  };

  // The shape of this screen, as a number. The server sends back only photos shaped
  // close enough to it that `cover` crops a sliver instead of half the picture.
  // A hidden or not-yet-laid-out page reports zero, which would otherwise travel to the
  // server as NaN and quietly turn the filtering off; fall back to the screen itself.
  function screenRatio() {
    for (const [w, h] of [[innerWidth, innerHeight], [screen.width, screen.height]]) {
      const ratio = w / h;
      if (isFinite(ratio) && ratio > 0) return ratio;
    }
    return 16 / 9;
  }

  // Read both fade lengths from the stylesheet so they cannot drift from the CSS.
  const seconds = name =>
    parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) || 0;
  const FADE = (seconds('--fade') || 1.6) * 1000;
  const QUICK_FADE = (seconds('--fade-quick') || 0.6) * 1000;
  // Set when the change was asked for by hand, and consumed by the next reveal.
  let quickFade = false;

  let ids = [], cursor = 0, front = 0, slide = 20000, misses = 0, fadeEndsAt = 0;
  let listRatio = null, currentId = null;
  let token = null, fetched = 0, total = 0, extending = false, indexing = false;
  // Photos already shown, so tapping the left half can walk back through them. Tapping
  // right again replays them forward before drawing anything new from the playlist.
  const history = [];
  const HISTORY_MAX = 200;
  let histPos = -1, jump = null;
  // A specific photo asked for by name — picked out of the gallery grid rather than
  // reached by stepping. Consumed by the next nextSlide().
  let pendingJumpId = null;
  // Ids blacklisted during this session. The next photo is already preloaded when the
  // menu acts, so it may be one that was just hidden — this catches it at the swap.
  const blocked = new Set();

  let cutShort = null;
  const wait = ms => new Promise(resolve => {
    const timer = setTimeout(resolve, ms);
    cutShort = () => { clearTimeout(timer); cutShort = null; resolve(); };
  });

  const capped = (promise, ms) => Promise.race([promise, new Promise(r => setTimeout(r, ms))]);

  function loaded(img) {
    if (img.complete) {
      return img.naturalWidth ? Promise.resolve() : Promise.reject(new Error('unreadable'));
    }
    return new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = () => reject(new Error('unreadable'));
    });
  }

  /** Start a fresh shuffled pass. Only the first page comes down now: the whole list
   *  is tens of thousands of ids and seconds of a slow server's time, while the frame
   *  needs two of them to put something on screen. */
  async function loadPlaylist() {
    const want = screenRatio();
    const res = await fetch(`/api/playlist?ratio=${want.toFixed(4)}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    ids = data.ids;
    cursor = 0;
    listRatio = want;
    token = data.token;
    fetched = data.ids.length;
    total = data.total;
    indexing = !!data.indexing;
    if (data.slideSeconds) slide = data.slideSeconds * 1000;
  }

  /** Pull the next page of the same pass, so nothing repeats until all have shown. */
  async function extendPlaylist() {
    if (!token || fetched >= total || extending) return false;
    extending = true;
    try {
      const res = await fetch(`/api/playlist?token=${token}&offset=${fetched}`, { cache: 'no-store' });
      if (!res.ok) return false;
      const data = await res.json();
      if (data.token !== token || !data.ids.length) return false;
      fetched += data.ids.length;
      ids.push(...data.ids.filter(id => !blocked.has(id)));
      return true;
    } catch {
      return false;
    } finally {
      extending = false;
    }
  }

  /** Load and fully decode a photo into the hidden layer, so revealing it costs nothing.
   *
   *  Only the newest call may touch the layer. A tap or swipe abandons the photo being
   *  preloaded, but that call is still running — without this guard it wakes up after
   *  the fade wait and writes its own src into the layer the new one just claimed, and
   *  the frame ends up showing one photo while believing it shows another.
   */
  let prepareSeq = 0;
  async function prepare(id) {
    const mine = ++prepareSeq;
    // The hidden layer may still be fading out; changing its src now would visibly
    // swap the outgoing photo mid-crossfade.
    const remaining = fadeEndsAt - performance.now();
    if (remaining > 0) await new Promise(r => setTimeout(r, remaining + 50));
    if (mine !== prepareSeq) throw new Error('superseded');

    const back = layers[1 - front];
    const photo = back.querySelector('img');
    photo.src = src(id);
    // Swallowed rather than thrown: a failure here may be the device choking on a
    // full-size file, which the retry below can fix.
    await capped(loaded(photo).catch(() => { }), 20000);
    if (mine !== prepareSeq) throw new Error('superseded');

    if (!photo.naturalWidth && demoteFromOriginals()) {
      // Ask the server to do the decoding from now on, and give this photo a second go.
      photo.src = src(id);
      await capped(loaded(photo).catch(() => { }), 20000);
      if (mine !== prepareSeq) throw new Error('superseded');
      if (photo.naturalWidth) say(t('smaller'));
    }
    if (!photo.naturalWidth) throw new Error('unreadable');
    // The expensive part for AVIF. Done here, well ahead of the swap, but still
    // capped: decode() never resolves while the tab is hidden.
    await capped(photo.decode().catch(() => { }), 5000);
    return back;
  }

  /** Pull the photos after the next one into the browser cache, ahead of being asked for.
   *
   *  `prepare` only ever readies one photo, because there are only two layers to put one
   *  in. That is enough for the ambient slideshow, where a minute passes between slides,
   *  but skipping outruns it immediately: each render costs the server several seconds on
   *  a 24 MP AVIF, so the second tap and every tap after it waits for one.
   *
   *  These fetches go nowhere near the layers — they exist only to make the server render
   *  each photo before it is wanted, so the real request is answered from the browser
   *  cache (`Cache-Control: private, max-age=3600`).
   *
   *  Strictly one at a time. The server renders under a small semaphore, and prefetching
   *  in parallel would fill it with photos nobody is looking at yet while the one on its
   *  way to the screen queues behind them — which is the very problem this is here to fix.
   */
  const PREFETCH_AHEAD = 3;
  const WARMED_MAX = 60;
  const warmed = new Set();
  let warming = false;

  async function warmAhead() {
    if (warming) return;
    warming = true;
    try {
      for (let i = 0; i < PREFETCH_AHEAD; i++) {
        // Re-read `cursor` every time: a burst of skips moves it while this loop runs,
        // and the useful photos to warm are the ones ahead of wherever it is *now*.
        const id = ids[cursor + i];
        if (!id || warmed.has(id) || blocked.has(id)) continue;
        // A hidden page is not going to show anything; spending the server's render
        // slots on it is pure waste.
        if (document.hidden) return;
        warmed.add(id);
        if (warmed.size > WARMED_MAX) warmed.delete(warmed.values().next().value);
        const image = new Image();
        image.src = src(id);
        await capped(loaded(image), 20000).catch(() => { });
      }
    } finally {
      warming = false;
    }
  }

  /** Never rejects — the caller distinguishes outcomes by the returned key.
   *
   *  `back`/`forward` walk the history; anything else takes the next photo from the
   *  playlist. The history position is only *returned*, never applied here: this runs
   *  ahead of time as a preload, and the photo it prepares may never be shown.
   */
  async function nextSlide(mode) {
    let id, position = null;
    if (pendingJumpId) {
      id = pendingJumpId;
      pendingJumpId = null;
    } else if (mode === 'back' && histPos > 0) {
      position = histPos - 1;
      id = history[position];
    } else if (mode === 'forward' && histPos >= 0 && histPos < history.length - 1) {
      position = histPos + 1;
      id = history[position];
    } else {
      if (cursor >= ids.length) {
        try {
          // The pass is not finished, only the part fetched so far — take the next
          // page before giving up on it and reshuffling.
          if (!(await extendPlaylist())) await loadPlaylist();
        } catch {
          return { offline: true };
        }
      }
      if (!ids.length) return { empty: true };
      id = ids[cursor++];
    }
    try {
      return { layer: await prepare(id), id, position };
    } catch (err) {
      // A step that lands mid-preparation cancels it. Without putting the id back, that
      // photo is dropped and the next one taken instead — and since a 24 MP original
      // takes about a second to be ready while a phone photo takes a third of that, going
      // quickly through the library skipped every big photo and showed only the small
      // ones. Whole cameras appeared to be missing. Retrying costs nothing: the file is
      // already in the browser cache, so the second attempt finishes immediately.
      if (err && err.message === 'superseded' && position === null && cursor > 0) {
        cursor -= 1;
      }
      return { failed: true };
    }
  }

  /** Start preparing the next photo, unless one is already on its way. */
  let preparing = false;
  function queue(mode) {
    preparing = true;
    const promise = nextSlide(mode).finally(() => { preparing = false; });
    // Only once that photo is in hand: warming shares the server's render slots, and the
    // one about to be shown must have first claim on them.
    promise.then(warmAhead);
    return promise;
  }

  function remember(id, position) {
    if (position !== null) { histPos = position; return; }
    history.splice(histPos + 1);  // a new photo abandons any forward history
    history.push(id);
    if (history.length > HISTORY_MAX) history.shift();
    histPos = history.length - 1;
  }

  function reveal(back) {
    // A hand-driven change still crossfades — cutting straight to the next photo reads as
    // a glitch — but briskly, because someone is waiting for it. The ambient slideshow
    // keeps the slow dissolve, which is the whole character of the thing.
    const fast = quickFade;
    quickFade = false;
    document.body.classList.toggle('quick', fast);
    back.style.opacity = 1;
    layers[front].style.opacity = 0;
    front = 1 - front;
    fadeEndsAt = performance.now() + (fast ? QUICK_FADE : FADE);
    status.hidden = true;
  }

  function stall(message, ms) {
    status.hidden = false;
    statusText.textContent = message;
    return wait(ms);
  }

  async function run() {
    let ready = queue();
    for (; ;) {
      const result = await ready;

      if (result.offline) {
        ready = queue();
        await stall(t('reconnecting'), 5000);
        continue;
      }
      if (result.empty) {
        ready = queue();
        // A server that is still building its index has nothing to offer yet, which is
        // not the same as a library with no photos in it — and it is worth asking again
        // in seconds rather than half a minute.
        if (indexing) await stall(t('preparing'), 3000);
        else await stall(t('noPhotos'), 30000);
        continue;
      }
      if (result.failed) {
        // Corrupt or unreadable file: skip on quickly. A long run of these would
        // otherwise leave a silent black screen, so say something after a while.
        ready = queue();
        if (++misses >= 10) await stall(t('nothingToShow'), 5000);
        else await wait(200);
        continue;
      }
      if (blocked.has(result.id)) {  // hidden from the menu while it sat preloaded
        ready = queue();
        continue;
      }

      // The photo is ready, but nothing changes under a finger that is mid-swipe.
      await waitWhile(interacting);

      reveal(result.layer);
      currentId = result.id;
      remember(result.id, result.position);
      describeCurrent();
      misses = 0;
      // Start fetching and decoding the next photo now, while this one is on screen,
      // so the next crossfade begins with a bitmap already in memory.
      ready = queue();
      // Top the list up well before it runs dry, so paging never blocks a slide.
      if (ids.length - cursor < 40) extendPlaylist();
      // A tap or swipe that lands while the next photo is still being prepared arrives
      // here with `jump` already set; waiting out the full interval first would make the
      // frame feel dead to the touch.
      if (!jump) {
        await wait(slide);
        // An open menu, a finger mid-swipe, or a screen nobody is looking at.
        await waitWhile(holding);
      }
      if (jump) {
        // Going forward from the end of the history *is* the photo already sitting
        // preloaded and decoded, so reuse it — re-preparing would throw away the decode
        // and cost several seconds on a full-size AVIF. Only going back, or forward into
        // history, needs a different photo.
        const atEnd = histPos >= history.length - 1;
        // Two different requests, and they must not be treated alike.
        //
        // "Next", with nothing ahead in the history, means *any* new photo — and one is
        // already being fetched and decoded. Starting another instead threw that work
        // away, and since a 24 MP original takes about a second while a phone photo takes
        // a third of that, going quickly through the library showed only the small ones:
        // whole cameras seemed to be missing. So let the one on its way arrive.
        //
        // Back, or forward into the history, names a *particular* photo. That has to be
        // honoured even though it cancels the preparation in flight — otherwise pressing
        // left simply shows the next unrelated photo, which is not going back at all.
        // Cancelling costs nothing here: nextSlide puts the abandoned playlist id back.
        if (!(jump === 'forward' && atEnd)) ready = queue(jump);
        jump = null;

      }
    }
  }

  /* ---- menu, blacklisting and fullscreen ---------------------------------- */

  const menu = document.getElementById('menu');
  const caption = document.getElementById('menu-caption');
  const hidePhoto = document.getElementById('hide-photo');
  const hideFolders = document.getElementById('hide-folders');
  const toast = document.getElementById('toast');

  let menuOpen = false, menuId = null, isFavorite = false;
  // True from touchdown to lift. The slideshow holds while a finger is down: advancing
  // mid-swipe swaps the photo out from under the gesture.
  let touching = false;

  // Two different reasons to hold, and they must not be conflated.
  //
  // A menu or a finger holds the photo *on screen*: swapping it out mid-gesture would act
  // on something the user was not looking at.
  //
  // A hidden page holds only the *advancing*: every slide costs the server a full render
  // for pixels nobody sees, and decode never resolves while hidden anyway. It deliberately
  // does not gate the reveal — a browser that mis-reports visibility would otherwise leave
  // the frame showing its loader forever.
  const interacting = () => menuOpen || touching || galleryOpen || infoOpen;
  const holding = () => interacting() || document.hidden || asleep();

  /* ---- quiet hours -------------------------------------------------------- */

  // A dark room does not need a lit wall, and a screen nobody is looking at still costs a
  // full render every slide, all night. Between these two times the frame fades to black
  // and stops advancing — the same hold a hidden page takes, so it does not gate the
  // reveal either. Set from the settings page and polled, so changing them reaches the
  // wall without anyone walking over.
  const WAKE = 5 * 60 * 1000;
  let quietFrom = '', quietTo = '', wakeUntil = 0;

  const asMinutes = clock => {
    const [hours, mins] = String(clock).split(':');
    return (+hours) * 60 + (+mins);
  };

  function quietNow() {
    if (!quietFrom || !quietTo) return false;
    const now = new Date();
    const here = now.getHours() * 60 + now.getMinutes();
    const from = asMinutes(quietFrom), to = asMinutes(quietTo);
    // The window nearly always wraps past midnight, so it is two ranges, not one.
    return from <= to ? (here >= from && here < to) : (here >= from || here < to);
  }

  const asleep = () => quietNow() && Date.now() > wakeUntil;

  function paintNight() {
    document.body.classList.toggle('asleep', asleep());
    releaseHold();   // the window may have just ended, or a tap may have just ended it
  }

  // Someone standing in front of it at three in the morning wants to see a photo, not a
  // black rectangle that ignores them.
  function wake() {
    if (!quietNow()) return;
    wakeUntil = Date.now() + WAKE;
    paintNight();
  }

  addEventListener('touchstart', wake, { passive: true, capture: true });
  addEventListener('mousedown', wake, { capture: true });
  addEventListener('keydown', wake, { capture: true });

  async function readSettings() {
    try {
      const data = await (await fetch('/api/settings', { cache: 'no-store' })).json();
      quietFrom = data.quietFrom || '';
      quietTo = data.quietTo || '';
      if (data.slideSeconds) slide = data.slideSeconds * 1000;
      if (!deviceLang() && data.language && data.language !== lang && TEXT[data.language]) {
        lang = data.language;
        applyLanguage();
      }
    } catch { /* the server will be back; what was read last still stands */ }
    paintNight();
  }

  let waiters = [];

  function waitWhile(predicate) {
    return predicate()
      ? new Promise(resolve => waiters.push({ predicate, resolve }))
      : Promise.resolve();
  }

  function releaseHold() {
    waiters = waiters.filter(({ predicate, resolve }) => predicate() || (resolve(), false));
  }

  const SVG_NS = 'http://www.w3.org/2000/svg';

  /** One of the sprite's glyphs, ready to put in a menu row. Built in the SVG namespace:
   *  createElement would make an unknown HTML element that draws nothing at all. */
  function glyph(name) {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('class', 'ico');
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS(SVG_NS, 'use');
    use.setAttribute('href', `#i-${name}`);
    svg.append(use);
    return svg;
  }

  /** The label beside it, in its own element so the icon survives a change of language
   *  and the text is what ellipsises when a folder name is longer than the menu. */
  function rowLabel(text) {
    const span = document.createElement('span');
    span.textContent = text;
    return span;
  }

  /** A copy of one of the heart icons already in the page, for use inside a toast. */
  function heartIcon(filled) {
    const icon = document.getElementById(filled ? 'heart-on' : 'heart-off').cloneNode(true);
    icon.removeAttribute('id');
    icon.removeAttribute('hidden');
    return icon;
  }

  let toastTimer;
  /** `undo`, when given, makes the toast tappable for as long as it is on screen. */
  function say(message, undo, icon) {
    toast.replaceChildren(...(icon ? [icon] : []), document.createTextNode(message));
    toast.classList.toggle('action', !!undo);
    toast.onclick = null;
    if (undo) {
      const button = document.createElement('button');
      button.textContent = t('undo');
      // A swipe down finishes with the finger at the bottom of the screen — exactly where
      // this appears. Without a moment's delay the follow-through, or the next tap to move
      // on, lands on Undo and quietly puts back what was just hidden.
      const armedAt = Date.now() + 700;
      button.addEventListener('click', event => {
        event.stopPropagation();
        if (Date.now() < armedAt) return;
        toast.classList.remove('show');
        undo();
      });
      toast.append(button);
    }
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), undo ? 6000 : 2600);
  }

  async function openMenu() {
    if (!currentId) return;
    menuOpen = true;
    menuId = currentId;  // pin it: the menu acts on the photo that was on screen
    menu.hidden = false;
    document.body.classList.add('menu-open');
    document.getElementById('more').setAttribute('aria-expanded', 'true');

    caption.textContent = '…';
    hidePhoto.disabled = true;
    hideFolders.replaceChildren();
    try {
      const res = await fetch(`/api/photo/${menuId}`, { cache: 'no-store' });
      const info = await res.json();
      if (!menuOpen || menuId !== currentId) return;
      caption.textContent = info.folder ? `${info.folder}/${info.file}` : info.file;
      hidePhoto.disabled = false;
      // One entry per folder level, outermost first, so you can hide just the shoot or
      // the whole year it sits in. A photo in the library root gets no folder entries.
      for (const folder of info.folders) {
        const item = document.createElement('button');
        item.role = 'menuitem';
        item.append(glyph('folder'), rowLabel(t('hideFolder', folder)));
        item.title = folder;
        item.addEventListener('click', () => blacklist('folder', folder));
        hideFolders.append(item);
      }
    } catch {
      caption.textContent = t('unreadable');
    }
  }

  function closeMenu() {
    menuOpen = false;
    menu.hidden = true;
    document.body.classList.remove('menu-open');
    document.getElementById('more').setAttribute('aria-expanded', 'false');
    releaseHold();
  }

  async function blacklist(scope, folder, photoId) {
    const id = photoId || menuId;
    closeMenu();
    try {
      const res = await fetch('/api/blacklist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, scope, folder }),
      });
      const data = await res.json();
      if (!res.ok) { say(data.error || t('hideFailed')); return; }

      // Drop the hidden photos from the playlist in place, so the shuffle keeps its
      // position instead of restarting from a fresh one.
      const gone = new Set(data.removed);
      gone.forEach(pid => blocked.add(pid));
      const keep = pid => !gone.has(pid);
      cursor = ids.slice(0, cursor).filter(keep).length;
      ids = ids.filter(keep);
      // Also out of the history, or tapping left would walk back into a hidden photo.
      histPos = history.slice(0, histPos + 1).filter(keep).length - 1;
      history.splice(0, history.length, ...history.filter(keep));

      const count = data.removed.length;
      say(t('hidden', data.entry, count),
        () => undoBlacklist(data.entry, scope));
      // Move on only if what was hidden is what is on screen. Hiding a neighbour from the
      // gallery grid should leave the frame where it is.
      if (gone.has(currentId)) {
        // Standing part-way back through the history, the photo to move to is the one
        // that was already next *in the history* — not a fresh one off the playlist.
        // Revealing a fresh one calls remember() with no position, and that truncates
        // everything ahead of the cursor: go back, hide, go forward, and the photo you
        // came from has been thrown away and replaced by an unrelated one.
        if (histPos < history.length - 1) jump = 'forward';
        if (cutShort) cutShort();
      }
    } catch {
      say('no se ha podido contactar con el servidor');
    }
  }

  /** Put a hidden photo (or folder) back, for the few seconds the toast offers it. */
  async function undoBlacklist(entry, scope) {
    try {
      const res = await fetch('/api/blacklist/undo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entry, scope }),
      });
      const data = await res.json();
      if (data.error) { say(data.error); return; }
      if (data.id) {
        blocked.delete(data.id);
        ids.splice(cursor, 0, data.id);
        // Hiding took it out of the history too, so stepping back would have skipped
        // straight past it. Put it back immediately behind the photo now on screen,
        // which is where it was when it was hidden.
        if (!history.includes(data.id)) {
          history.splice(histPos, 0, data.id);
          histPos += 1;
        }
      }
      say(t('restored', entry));
    } catch {
      say('no se ha podido contactar con el servidor');
    }
  }

  const fsEnter = document.getElementById('fs-enter');
  const fsExit = document.getElementById('fs-exit');

  // F11 is the browser's own fullscreen, not the Fullscreen API: it leaves
  // document.fullscreenElement null and fires no fullscreenchange. Without this the button
  // still offers "enter", and pressing it hands the already-fullscreen page to the API,
  // which flips the icon while nothing on screen moves.
  const displayFullscreen = matchMedia('(display-mode: fullscreen)');

  // Chrome reports this for F11, which is the only browser this frame runs on. Measuring
  // the viewport against the screen instead was worse than useless: screen.width/height
  // are already CSS pixels, so on a 2x display any such comparison reads as fullscreen the
  // whole time and the button refuses to enter it.
  const nativelyFullscreen = () => displayFullscreen.matches;

  function syncFullscreenIcons() {
    const on = !!document.fullscreenElement || nativelyFullscreen();
    fsEnter.toggleAttribute('hidden', on);
    fsExit.toggleAttribute('hidden', !on);
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => { });
    } else if (nativelyFullscreen()) {
      // Nothing can leave F11 from script — it is a browser mode with no web API. Taking
      // it over with requestFullscreen would only desync the icon again, so say so instead
      // of pretending the click did something.
      say(t('exitFullscreen'));
    } else {
      // Must be called straight from the click, or the browser refuses the request.
      document.documentElement.requestFullscreen().catch(() => say(t('fullscreenDenied')));
    }
  }

  document.addEventListener('fullscreenchange', syncFullscreenIcons);
  // F11 announces itself only as a resize, and on some browsers only as a display-mode
  // change, so the button is reconciled from both.
  addEventListener('resize', syncFullscreenIcons);
  displayFullscreen.addEventListener('change', syncFullscreenIcons);
  syncFullscreenIcons();  // the page may well have been loaded already in fullscreen

  document.getElementById('fullscreen').addEventListener('click', e => {
    e.stopPropagation();  // a tap on a control must not also advance the slide
    toggleFullscreen();
  });
  document.getElementById('more').addEventListener('click', e => {
    e.stopPropagation();
    menuOpen ? closeMenu() : openMenu();
  });
  menu.addEventListener('click', e => e.stopPropagation());
  hidePhoto.addEventListener('click', () => blacklist('photo'));

  const heart = document.getElementById('heart');
  const heartOff = document.getElementById('heart-off');
  const heartOn = document.getElementById('heart-on');

  /** Restarting an animation needs the class off, a reflow, then the class on again. */
  function pulseHeart() {
    heart.classList.remove('pulsing');
    void heart.offsetWidth;
    heart.classList.add('pulsing');
  }

  function showHeart(on) {
    isFavorite = on;
    heart.setAttribute('aria-pressed', on ? 'true' : 'false');
    heart.setAttribute('aria-label', t(on ? 'ui.favoriteRemove' : 'ui.favoriteAdd'));
    heart.title = on ? 'Remove from favorites' : 'Add to favorites';
    // toggleAttribute, not .hidden: SVG elements have no such IDL property, so assigning
    // to it silently does nothing at all.
    heartOn.toggleAttribute('hidden', !on);
    heartOff.toggleAttribute('hidden', on);
  }

  /** Path and heart both follow the slideshow, from the one request per photo. */
  async function describeCurrent() {
    const id = currentId;
    showHeart(false);
    try {
      const info = await (await fetch(`/api/photo/${id}`, { cache: 'no-store' })).json();
      if (id !== currentId) return;  // the slide moved on while this was in flight
      showHeart(!!info.favorite);
      // Inside a span, so the ltr rule above governs the order of the segments.
      const label = document.createElement('span');
      label.textContent = info.folder ? `${info.folder}/${info.file}` : info.file;
      pathLabel.replaceChildren(label);
      pathLabel.dataset.fullPath = info.fullPath || '';
      pathLabel.title = info.fullPath || '';
    } catch {
      pathLabel.replaceChildren();  // leave it blank; the next slide asks again
      delete pathLabel.dataset.fullPath;
    }
  }

  /** navigator.clipboard exists only in a secure context, and the frame is plain HTTP on
   *  the LAN — so fall back to the old selection trick, which still works there. */
  async function copyText(text) {
    try {
      if (navigator.clipboard && isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch { /* fall through to the fallback */ }
    const scratch = document.createElement('textarea');
    scratch.value = text;
    scratch.setAttribute('readonly', '');
    scratch.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
    document.body.append(scratch);
    scratch.select();
    let copied = false;
    try {
      copied = document.execCommand('copy');
    } catch { /* nothing else to try */ }
    scratch.remove();
    return copied;
  }

  // Tapping the path copies it rather than moving the slideshow on — it is the one bit of
  // the photo layer that is a control.
  pathLabel.addEventListener('click', async event => {
    event.stopPropagation();
    const path = pathLabel.dataset.fullPath || pathLabel.textContent;
    if (!path) return;
    say(t(await copyText(path) ? 'pathCopied' : 'pathNotCopied'));
  });

  async function setFavorite(id, wanted) {
    if (id === currentId) showHeart(wanted);  // respond to the tap immediately
    if (wanted) pulseHeart();
    try {
      const res = await fetch('/api/favorite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, favorite: wanted }),
      });
      const data = await res.json();
      if (data.error) { say(data.error); if (id === currentId) showHeart(!!data.favorite); return; }
      // `coveredBy: "rule"` means a tag, folder or glob decided it, rather than a
      // line naming this photo — worth saying, since editing the rule affects others.
      // The weighting is baked into the playlist when it is built, so it takes effect
      // on the next pass rather than right now.
      // The same heart the button and the swipe pill use, filled or outline to match
      // which way the toggle went.
      say(t(wanted ? 'favorited' : 'unfavorited'), null, heartIcon(wanted));
    } catch {
      say('no se ha podido contactar con el servidor');
      if (id === currentId) showHeart(!wanted);
    }
  }

  heart.addEventListener('click', e => {
    e.stopPropagation();
    if (currentId) setFavorite(currentId, !isFavorite);
  });
  document.getElementById('menu-close').addEventListener('click', closeMenu);

  /* ---- gallery: the rest of the folder, for dealing with a burst ------------ */

  const gallery = document.getElementById('gallery');
  const galleryGrid = document.getElementById('gallery-grid');
  const galleryFolder = document.getElementById('gallery-folder');
  const tileTemplate = document.getElementById('gallery-tile');

  let galleryOpen = false;
  let galleryWatcher = null;
  // The whole folder's metadata, and the slice of it that currently exists as tiles.
  let galleryPhotos = [], galleryDir = '', builtLo = 0, builtHi = 0;
  let tileW = 320, tileH = 213;
  // The folder outside the built window, as two blocks of empty rows -- see paintSpacers.
  const leadSpacer = spacerElement(), tailSpacer = spacerElement();
  // Rows built at a time, and the most kept in the document. The largest folder here holds
  // over six thousand photos: built whole, that is a hundred thousand elements and every
  // thumbnail ever scrolled past still decoded in memory.
  const BATCH_ROWS = 8, WINDOW_ROWS = 24;

  function spacerElement() {
    const spacer = document.createElement('div');
    spacer.className = 'gallery-spacer';
    spacer.hidden = true;
    return spacer;
  }

  function columnCount() {
    return getComputedStyle(galleryGrid).gridTemplateColumns.split(' ').length;
  }

  /** The size to actually ask the server for, from the width a tile ended up.
   *
   *  A tile is a fraction of the screen, so a phone wants a genuinely smaller image than
   *  the device — asking for one fixed size means sending several times the pixels the
   *  small screen can show. Rounded up to a step, though, and not to the exact pixel:
   *  every distinct size is its own entry in the server's render cache, and unbucketed
   *  widths would fill it with near-duplicates of the same photo.
   *
   *  Only the transfer and the bitmap shrink. The server still decodes the full-size AVIF
   *  behind every tile, which is why they load a screenful at a time.
   */
  const TILE_STEP = 64, TILE_MIN = 128, TILE_MAX = 512;

  function tileSize() {
    const first = galleryGrid.querySelector('.tile');
    const measured = first ? first.clientWidth : 0;
    const wanted = Math.ceil((measured || 320) / TILE_STEP) * TILE_STEP;
    const width = Math.max(TILE_MIN, Math.min(wanted, TILE_MAX));
    return { w: width, h: Math.round(width * 2 / 3) };  // the tiles are 3:2
  }

  /** Size the tiles so a whole number of rows fills the grid's height exactly. With the
   *  scroll already row-aligned, that is what keeps every visible photo complete — half a
   *  row at the bottom edge costs a full render per tile for a strip nobody can see.
   *
   *  Tiles only ever shrink to make the fit: growing them to reach the row above would push
   *  the columns wider than the screen.
   */
  function fitGrid() {
    galleryGrid.style.gridTemplateColumns = '';   // back to auto-fill, to be asked again
    const style = getComputedStyle(galleryGrid);
    const rowGap = parseFloat(style.rowGap) || 0;
    const colGap = parseFloat(style.columnGap) || 0;
    const width = galleryGrid.clientWidth
      - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const height = galleryGrid.clientHeight;
    const cols = style.gridTemplateColumns.split(' ').length;
    if (!(width > 0) || !(height > 0) || !cols) return;
    const colW = (width - (cols - 1) * colGap) / cols;
    const rows = Math.max(1, Math.ceil((height + rowGap) / (colW * 2 / 3 + rowGap)));
    const rowH = (height - (rows - 1) * rowGap) / rows;
    galleryGrid.style.gridTemplateColumns = `repeat(${cols}, ${rowH * 3 / 2}px)`;
  }

  /** One row of scrolling: a tile plus the gap under it. */
  function rowPitch() {
    const first = galleryGrid.querySelector('.tile');
    if (!first) return 0;
    const gap = parseFloat(getComputedStyle(galleryGrid).rowGap) || 0;
    return first.getBoundingClientRect().height + gap;
  }

  /** Snap a scroll position to a row boundary, so no row is ever part-visible: a sliver of
   *  a row still costs the server a full render for every tile in it. */
  function alignRow(top) {
    const pitch = rowPitch();
    if (!pitch) return top;
    const max = Math.max(0, galleryGrid.scrollHeight - galleryGrid.clientHeight);
    return Math.max(0, Math.min(max, Math.round(top / pitch) * pitch));
  }

  /** Give the folder outside the window its height back, in whole rows, so the scroll bar
   *  still spans the folder and nothing moves when tiles are dropped. A spacer stands for
   *  the rows it replaces exactly: rows * pitch, less the gap the grid adds under it. */
  function paintSpacers() {
    const cols = columnCount();
    const pitch = rowPitch();
    const gap = parseFloat(getComputedStyle(galleryGrid).rowGap) || 0;
    if (!cols || !pitch) return;
    const rows = [builtLo / cols, Math.ceil((galleryPhotos.length - builtHi) / cols)];
    [leadSpacer, tailSpacer].forEach((spacer, i) => {
      spacer.hidden = !rows[i];
      spacer.style.height = rows[i] ? `${rows[i] * pitch - gap}px` : '';
    });
  }

  /** The window has to start on a row boundary and, unless it reaches the end of the
   *  folder, finish on one: a spacer spans the full width, so a part-built row either side
   *  of it would leave a hole and put the tiles after it in the wrong columns.
   *
   *  Only ever grows the window -- dropping the odd photos instead would shift the grid.
   */
  function snapWindow() {
    const cols = columnCount();
    if (!cols) return;
    const from = builtLo - builtLo % cols;
    if (from < builtLo) {
      const batch = document.createDocumentFragment();
      for (let i = from; i < builtLo; i++) batch.append(buildTile(galleryPhotos[i]));
      leadSpacer.after(batch);
      builtLo = from;
    }
    const short = builtHi % cols;
    if (short && builtHi < galleryPhotos.length) {
      const upto = Math.min(galleryPhotos.length, builtHi + cols - short);
      const batch = document.createDocumentFragment();
      for (let i = builtHi; i < upto; i++) batch.append(buildTile(galleryPhotos[i]));
      tailSpacer.before(batch);
      builtHi = upto;
    }
    observeNew();
  }

  /** Drop tiles off one end of the window. The spacer grows by exactly what they occupied,
   *  so the scroll stays on the same photo. */
  function dropTiles(count, fromTop) {
    for (let n = 0; n < count; n++) {
      const tile = fromTop ? leadSpacer.nextElementSibling
        : tailSpacer.previousElementSibling;
      if (!tile || !tile.classList.contains('tile')) break;
      const img = tile.querySelector('img');
      if (galleryWatcher) galleryWatcher.unobserve(img);
      img.removeAttribute('src');   // let the decoded thumbnail go with the tile
      tile.remove();
    }
    if (fromTop) builtLo += count;
    else builtHi -= count;
  }

  /** Hand back whole rows from whichever end is further from the screen, never a row the
   *  window is being asked to cover. */
  function trimWindow(cols, lo, hi) {
    const excess = builtHi - builtLo - cols * WINDOW_ROWS;
    if (excess <= 0) return;
    const fromTop = lo - builtLo >= builtHi - hi;
    const room = fromTop ? lo - builtLo : builtHi - hi;
    const drop = Math.floor(Math.min(excess, room) / cols) * cols;
    if (drop > 0) dropTiles(drop, fromTop);
  }

  async function openGallery(id) {
    const subject = id || currentId;
    if (!subject || galleryOpen) return;
    galleryOpen = true;
    closeMenu();
    gallery.hidden = false;
    // Lets the grid scroll: see body.gallery-open in the stylesheet.
    document.body.classList.add('gallery-open');
    galleryFolder.textContent = '…';
    galleryGrid.replaceChildren();

    let data;
    try {
      // The whole folder, so it can be scrolled end to end. Only the tiles scrolled to are
      // ever fetched, so the cost is in the markup, not in renders.
      const res = await fetch(`/api/neighbors/${subject}`, { cache: 'no-store' });
      if (!res.ok) throw new Error('no neighbours');
      data = await res.json();
    } catch {
      galleryFolder.textContent = '';
      const empty = document.createElement('div');
      empty.id = 'gallery-empty';
      empty.textContent = t('folderFailed');
      galleryGrid.append(empty);
      return;
    }
    if (!galleryOpen) return;  // closed again while the request was in flight

    galleryFolder.textContent =
      t('folderCount', data.folder || t('libraryRoot'), data.total);

    galleryPhotos = data.photos;
    galleryDir = data.folder;
    const here = Math.max(0, data.photos.findIndex(photo => photo.current));

    // Tiles exist only around the photo you were on; the rest of the folder is the two
    // spacers, and the window follows the scroll from there.
    const half = BATCH_ROWS * 6;
    builtLo = Math.max(0, here - half);
    builtHi = Math.min(galleryPhotos.length, here + half);
    galleryGrid.replaceChildren(leadSpacer, tailSpacer);
    const opening = document.createDocumentFragment();
    for (let i = builtLo; i < builtHi; i++) opening.append(buildTile(galleryPhotos[i]));
    tailSpacer.before(opening);
    fitGrid();

    // Measured only now: a tile has to be in the grid before it has a width.
    const { w, h } = tileSize();
    tileW = w;
    tileH = h;

    // Only what is scrolled to is ever fetched. Rendering a tile costs the server a full
    // AVIF decode, so loading a screenful you never look at is the expensive mistake.
    galleryWatcher = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const img = entry.target;
        galleryWatcher.unobserve(img);
        // Marked as the request goes out, so only tiles actually waiting on a render show
        // the loader — see .tile.loading in the stylesheet.
        const tile = img.closest('.tile');
        if (tile) tile.classList.add('loading');
        img.src = `/img/${img.dataset.id}?w=${tileW}&h=${tileH}`;
      }
    }, { root: galleryGrid, rootMargin: '300px' });
    snapWindow();
    paintSpacers();
    observeNew();

    // Open centred on the photo you were looking at, not at the top of the folder.
    const currentTile = galleryGrid.querySelector('.tile.current');
    if (currentTile) currentTile.scrollIntoView({ block: 'center' });
    galleryGrid.scrollTop = alignRow(galleryGrid.scrollTop);
  }

  function buildTile(photo) {
    const tile = tileTemplate.content.firstElementChild.cloneNode(true);
    tile.dataset.id = photo.id;
    tile.classList.toggle('current', !!photo.current);
    tile.querySelector('figcaption').textContent = photo.file;

    const img = tile.querySelector('img');
    img.dataset.id = photo.id;
    img.alt = photo.file;
    img.addEventListener('load', () => {
      img.classList.add('ready');
      tile.classList.add('loaded');
    });
    // A photo the server cannot render would otherwise spin for ever.
    img.addEventListener('error', () => tile.classList.add('loaded'));

    const fav = tile.querySelector('.tile-fav');
    paintTileFavorite(fav, photo.favorite);
    fav.addEventListener('click', event => {
      event.stopPropagation();
      const wanted = fav.getAttribute('aria-pressed') !== 'true';
      paintTileFavorite(fav, wanted);        // answer the tap at once
      setFavorite(photo.id, wanted);
    });

    tile.querySelector('.tile-hide').addEventListener('click', event => {
      event.stopPropagation();
      toggleTileHidden(tile, photo);
    });

    // Tapping the tile itself jumps the frame to that photo and closes the grid.
    tile.addEventListener('click', () => {
      if (tile.classList.contains('hidden-photo')) return;  // not in the library
      showFromGallery(photo.id);
    });
    return tile;
  }

  /** Build the next batch at whichever end is being approached. */
  function extendGallery() {
    if (!galleryOpen || !galleryPhotos.length) return;
    const cols = columnCount();
    const pitch = rowPitch();
    if (!cols || !pitch) return;
    // What is on screen, plus a batch of rows either side to scroll into. The spacers give
    // the grid the whole folder's scroll length, so this is where the window has to be —
    // not, as it once was, wherever the built tiles happen to have reached.
    const firstRow = Math.floor(galleryGrid.scrollTop / pitch);
    const lastRow = Math.ceil((galleryGrid.scrollTop + galleryGrid.clientHeight) / pitch);
    const lo = Math.max(0, (firstRow - BATCH_ROWS) * cols);
    const hi = Math.min(galleryPhotos.length, (lastRow + BATCH_ROWS) * cols);
    if (lo === builtLo && hi === builtHi) return;

    if (lo >= builtHi || hi <= builtLo) {   // the scroll bar dragged clean past the window
      dropTiles(builtHi - builtLo, true);
      builtLo = builtHi = lo;
    }
    if (hi > builtHi) {
      const batch = document.createDocumentFragment();
      for (let i = builtHi; i < hi; i++) batch.append(buildTile(galleryPhotos[i]));
      tailSpacer.before(batch);
      builtHi = hi;
    }
    if (lo < builtLo) {
      const batch = document.createDocumentFragment();
      for (let i = lo; i < builtLo; i++) batch.append(buildTile(galleryPhotos[i]));
      leadSpacer.after(batch);
      builtLo = lo;
    }
    trimWindow(cols, lo, hi);
    observeNew();
    // The spacers take back exactly what the dropped tiles held, so nothing moves.
    paintSpacers();
  }

  function observeNew() {
    if (!galleryWatcher) return;
    for (const img of galleryGrid.querySelectorAll('img:not([src])')) {
      galleryWatcher.observe(img);
    }
  }

  function paintTileFavorite(button, on) {
    button.setAttribute('aria-pressed', on ? 'true' : 'false');
    button.querySelector('.fav-on').toggleAttribute('hidden', !on);
    button.querySelector('.fav-off').toggleAttribute('hidden', !!on);
  }

  function paintTileHidden(tile, on) {
    const button = tile.querySelector('.tile-hide');
    tile.classList.toggle('hidden-photo', on);
    button.setAttribute('aria-pressed', on ? 'true' : 'false');
    button.setAttribute('aria-label', on ? 'Mostrar' : 'Ocultar');
    button.querySelector('.hide-on').toggleAttribute('hidden', !on);
    button.querySelector('.hide-off').toggleAttribute('hidden', !!on);
  }

  /** Hide or restore, answering the tap at once and letting the request follow.
   *
   *  The tile stays put either way: working through a burst means seeing at a glance which
   *  ones have already been dealt with, and a tile that vanished would take that with it —
   *  along with any chance of changing your mind without hunting for the toast.
   */
  function toggleTileHidden(tile, photo) {
    const hiding = !tile.classList.contains('hidden-photo');
    paintTileHidden(tile, hiding);
    const entry = galleryDir ? `${galleryDir}/${photo.file}` : photo.file;
    if (hiding) blacklist('photo', null, photo.id);
    else undoBlacklist(entry, 'photo');
  }

  /** Jump the slideshow to a photo picked out of the grid. */
  function showFromGallery(id) {
    closeGallery();
    if (id === currentId) return;
    pendingJumpId = id;
    quickFade = true;
    // 'pick' is not a direction, which is the point: it makes the loop re-prepare rather
    // than reveal the photo already sitting preloaded.
    jump = 'pick';
    if (cutShort) cutShort();
  }

  function closeGallery() {
    if (!galleryOpen) return;
    galleryOpen = false;
    gallery.hidden = true;
    document.body.classList.remove('gallery-open');
    if (galleryWatcher) { galleryWatcher.disconnect(); galleryWatcher = null; }
    clearTimeout(settleTimer);
    touchingGrid = false;
    galleryGrid.replaceChildren();  // drop the decoded thumbnails
    galleryPhotos = [];
    galleryDir = '';
    builtLo = builtHi = 0;
    releaseHold();
  }

  /* ---- info: what the camera recorded -------------------------------------- */

  const infoPanel = document.getElementById('info');
  const infoRows = document.getElementById('info-rows');
  const infoTitle = document.getElementById('info-title');
  let infoOpen = false;

  /* What EXIF holds is an order code, not the name anyone knows the device by: Sony
     writes "ILCE-7M3" for the α7 III, Xiaomi "M2012K11AG" for the POCO F3. Only devices
     actually in this library are mapped, plus a rule for the rest of the Sony line — a
     wrong expansion is worse than the raw code, because nothing on screen would hint
     that it was wrong. */
  const CAMERA_NAMES = {
    'ILCE-7M3': 'α7 III',
    'ILCE-7M4': 'α7 IV',
    'ILCE-6700': 'α6700',
    'ILCA-68': 'α68',
    '2107113SG': '11T Pro',
    'M2012K11AG': 'POCO F3',
  };
  /* EXIF names the lens as the mount reports it, which is neither the name on the barrel
     nor the maker's. Only the ones actually in this library are renamed; anything else is
     shown exactly as the file says, because a lens nobody recognises is still better than
     a wrong one. */
  const LENS_NAMES = {
    'FE 28-70mm F3.5-5.6 OSS': 'Sony 28-70mm',
    'E 70-300mm F4.5-6.3 A047': 'Tamron 70-300mm',
    'DT 18-55mm F3.5-5.6 SAM': 'Sony 18-55mm',
    'FE 50mm F1.8': 'Sony 50mm',
    '75-300mm F4.5-5.6': 'Tamron 75-300mm',
    'FE 24-105mm F4 G OSS': 'Sony 24-105mm',
    // Phone modules. The Cámara field already names the phone, so repeating it here says
    // nothing; which of its lenses took the shot does. Apple calls both rear modules
    // "back dual wide camera" and only the focal length tells them apart, which is why
    // these are keyed on the whole string.
    'Pixel 10 Pro back camera 2.02mm f/1.7': 'Gran angular',
    'Pixel 10 Pro back camera 6.9mm f/1.68': 'Principal',
    'Pixel 10 Pro back camera 17.906mm f/2.8': 'Teleobjetivo',
    'Pixel 10 Pro front camera 2.713mm f/2.2': 'Frontal',
    'iPhone 12 back dual wide camera 1.55mm f/2.4': 'Gran angular',
    'iPhone 12 back dual wide camera 4.2mm f/1.6': 'Principal',
    'iPhone 12 front camera 2.71mm f/2.2': 'Frontal',
  };

  const lensName = (lens) => LENS_NAMES[lens] || lens;

  const SONY_CODE = /^ILC[EA]-(\d+)([A-Z]*)(?:M(\d+))?$/;
  const MARKS = { 2: 'II', 3: 'III', 4: 'IV', 5: 'V', 6: 'VI', 7: 'VII' };
  // Makers shout, or whisper, or append "CORPORATION". None of it belongs on screen.
  const MAKER_NAMES = {
    'SONY': 'Sony', 'NIKON CORPORATION': 'Nikon', 'samsung': 'Samsung',
    'CANON': 'Canon', 'OLYMPUS CORPORATION': 'Olympus', 'OLYMPUS IMAGING CORP.': 'Olympus',
  };

  function modelName(model) {
    if (CAMERA_NAMES[model]) return CAMERA_NAMES[model];
    const sony = SONY_CODE.exec(model);
    if (sony) {
      const [, digits, letters, mark] = sony;
      return `α${digits}${letters}${mark ? ' ' + (MARKS[mark] || mark) : ''}`;
    }
    return model;
  }

  /** "Sony α7 III", "Canon EOS R6m2" — never "Canon Canon EOS R6m2". */
  function cameraName(make, model) {
    if (!model) return make ? (MAKER_NAMES[make] || make) : '';
    const maker = MAKER_NAMES[make] || make || '';
    const named = modelName(model);
    if (!maker) return named;
    // Canon and Nikon both repeat the brand inside the model field. Swap that copy for
    // the tidied one rather than keeping it, or "NIKON CORPORATION" merely becomes
    // "NIKON D7000" instead of "Nikon D7000".
    if (named.toLowerCase().startsWith(maker.toLowerCase())) {
      return maker + named.slice(maker.length);
    }
    return `${maker} ${named}`;
  }

  /* The shapes a camera actually produces. A photo is matched to the nearest of these
     rather than reduced arithmetically: 5687x3791 reduces to 5687:3791, which is true and
     useless, while "3:2" is what the number is for. */
  const ASPECTS = [
    [1, 1], [5, 4], [4, 3], [3, 2], [16, 10], [16, 9], [2, 1], [20, 9], [21, 9], [3, 1],
  ];

  function aspectText(width, height) {
    const portrait = height > width;
    const ratio = portrait ? height / width : width / height;
    let best = null, closest = Infinity;
    for (const [a, b] of ASPECTS) {
      const off = Math.abs(Math.log(ratio / (a / b)));
      if (off < closest) { closest = off; best = [a, b]; }
    }
    if (closest > 0.02) return null;          // nothing standard: say nothing
    const [a, b] = best;
    return portrait ? `${b}:${a}` : `${a}:${b}`;
  }

  /** 1/250 rather than 0.004, which is how a shutter speed is read. */
  function shutterText(seconds) {
    if (seconds >= 1) return `${(+seconds.toFixed(1))}s`;
    return `1/${Math.round(1 / seconds)}s`;
  }

  function coordinates(lat, lon) {
    const ns = lat >= 0 ? 'N' : 'S', ew = lon >= 0 ? 'E' : 'W';
    return `${Math.abs(lat).toFixed(5)}° ${ns}, ${Math.abs(lon).toFixed(5)}° ${ew}`;
  }

  const TAKEN = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/;

  /** "12 Oct 2025 · 13:45".
   *
   *  Pulled apart with a regex rather than handed to Date: what the camera wrote carries
   *  no zone, so constructing a Date from it makes the browser assume one and shift the
   *  time — a photo taken at 00:30 would show as the previous day. These are the digits
   *  the camera recorded, shown as they were recorded.
   */
  function takenText(taken) {
    const parts = TAKEN.exec(String(taken));
    if (!parts) return String(taken);
    const [, year, month, day, hours, minutes] = parts;
    return `${+day} ${t('months')[+month - 1]} ${year} · ${hours}:${minutes}`;
  }

  /** Label above value, each pair a block in the grid. The dt/dd stay wrapped in a div so
   *  a pair travels together — loose dt and dd would each become their own grid cell and
   *  the labels would drift away from their values. */
  function addRow(label, value, mono, wide, into, icon) {
    const field = document.createElement('div');
    field.className = 'field' + (wide ? ' wide' : '');
    const dt = document.createElement('dt');
    if (icon) dt.append(glyph(icon));
    dt.append(document.createTextNode(label));
    const dd = document.createElement('dd');
    if (mono) dd.classList.add('mono');
    if (value instanceof Node) dd.append(value);
    else dd.textContent = value;
    field.append(dt, dd);
    (into || infoRows).append(field);
  }

  /** A field with no label, for something that says what it is on its own. */
  function addBlock(node) {
    const field = document.createElement('div');
    field.className = 'field wide';
    field.append(node);
    infoRows.append(field);
  }

  async function openInfo(id) {
    const subject = id || currentId;
    if (!subject || infoOpen) return;
    infoOpen = true;
    closeMenu();
    infoPanel.hidden = false;
    document.body.classList.add('gallery-open');  // same touch-action exception
    infoTitle.textContent = '…';
    infoRows.replaceChildren();

    let info;
    try {
      info = await (await fetch(`/api/info/${subject}`, { cache: 'no-store' })).json();
    } catch {
      infoTitle.textContent = '';
      const empty = document.createElement('div');
      empty.id = 'info-empty';
      empty.textContent = t('detailsFailed');
      infoRows.append(empty);
      return;
    }
    if (!infoOpen) return;

    infoTitle.textContent = info.file || '';

    // Explicit lines, grouped by what a person is actually asking when they open this:
    // when and how big, then what took it, then where, then who, then where it lives.
    // Empty lines never reach the panel, so a photo with no EXIF does not leave gaps.
    const line = (tight) => {
      const el = document.createElement('div');
      el.className = 'info-line' + (tight ? ' tight' : '');
      return el;
    };
    const commit = (el) => { if (el.children.length) infoRows.append(el); };

    // 1 — when, and how much of it there is.
    const when = line();
    if (info.taken) addRow(t('row.date'), takenText(info.taken), false, false, when, 'calendar');
    if (info.width && info.height) {
      const megapixels = (info.width * info.height / 1e6).toFixed(1);
      const shape = aspectText(info.width, info.height);
      const parts = [`${info.width} × ${info.height}`, shape, `${megapixels} MP`].filter(Boolean);
      addRow(t('row.size'), parts.join(' · '), false, false, when, 'ruler');
    }
    if (info.size) addRow(t('row.weight'), `${(info.size / 1048576).toFixed(1)} MB`, false, false, when, 'weight');
    commit(when);

    // 2 — what took it, and how it was set.
    const gear = line();
    const camera = cameraName(info.make, info.model);
    if (camera) addRow(t('row.camera'), camera, false, false, gear, 'camera');
    if (info.lens) addRow(t('row.lens'), lensName(info.lens), false, false, gear, 'lens');

    // Focal length, aperture, shutter and ISO in one field: they are the settings of a
    // single shot and are read together, the way any camera displays them. Whichever
    // parts the camera did not record are simply absent.
    const shot = [];
    if (info.aperture) shot.push(`f/${+info.aperture.toFixed(1)}`);
    if (info.shutter) shot.push(shutterText(info.shutter));
    if (info.iso) shot.push(`ISO ${info.iso}`);
    if (info.focal_length) {
      const equivalent = info.focal_length_35 && Math.round(info.focal_length_35) !== Math.round(info.focal_length)
        ? ` (equiv. ${Math.round(info.focal_length_35)} mm)` : '';
      shot.push(`${Math.round(info.focal_length)} mm${equivalent}`);
    }
    // Compensation last, and only when it is not zero: it is a correction to the exposure
    // above rather than a separate fact, and on most shots there is none to report.
    if (info.compensation) shot.push(`${info.compensation > 0 ? '+' : ''}${info.compensation} EV`);
    if (shot.length) addRow(t('row.exposure'), shot.join(' · '), false, false, gear, 'aperture');
    else if (info.exposure_display) addRow(t('row.exposure'), info.exposure_display, false, false, gear, 'aperture');
    commit(gear);

    // 3 — where. One field, not two: the place name is the map link when geocoding
    // resolved it, and the coordinates appear only when it did not, because on their own
    // they are the one thing here nobody reads. `tight` keeps altitude beside it.
    const located = info.gps_lat != null && info.gps_lon != null;
    if (info.location || located) {
      const where = line(true);
      const label = info.location || coordinates(info.gps_lat, info.gps_lon);
      let value = label;
      if (located) {
        value = document.createElement('a');
        value.href = `https://www.google.com/maps/search/?api=1&query=${info.gps_lat},${info.gps_lon}`;
        value.target = '_blank';
        value.rel = 'noopener noreferrer';
        value.textContent = label;
      }
      addRow(t('row.place'), value, !info.location, false, where, 'pin');
      if (located && info.altitude) {
        addRow(t('row.altitude'), `${Math.round(info.altitude)} m`, false, false, where, 'altitude');
      }
      commit(where);
    }

    // 4 — who is in it, and the way out to the original.
    const who = line();
    if (info.people && info.people.length) addRow(t('row.people'), info.people.join(', '), false, false, who, 'user');
    if (info.tags && info.tags.length) addRow(t('row.tags'), info.tags.join(', '), false, false, who, 'tag');
    commit(who);

    // 5 — where it lives on disk.
    const path = line();
    addRow(t('row.path'), info.fullPath || '', true, false, path, 'folder');
    commit(path);

    // 6 — the way out to the original, last: it is an action, not another fact, and it
    // reads as the panel's conclusion rather than one more field among the metadata.
    if (info.google_url) {
      const button = document.getElementById('gphotos-button')
        .content.firstElementChild.cloneNode(true);
      button.href = info.google_url;
      const field = document.createElement('div');
      field.className = 'field';
      field.append(button);
      const action = line();
      action.append(field);
      commit(action);
    }

    if (!infoRows.children.length) {
      const empty = document.createElement('div');
      empty.id = 'info-empty';
      empty.textContent = t('noDetails');
      infoRows.append(empty);
    }
  }

  function closeInfo() {
    if (!infoOpen) return;
    infoOpen = false;
    infoPanel.hidden = true;
    if (!galleryOpen) document.body.classList.remove('gallery-open');
    infoRows.replaceChildren();
    releaseHold();
  }

  document.getElementById('info-close').addEventListener('click', event => {
    event.stopPropagation();
    closeInfo();
  });
  document.getElementById('open-info').addEventListener('click', event => {
    event.stopPropagation();
    openInfo(menuId);
  });
  // Leaves the slideshow, which is the only way to reach the settings of *this* device:
  // half of them live in its own browser. The page links back.
  document.getElementById('open-settings').addEventListener('click', event => {
    event.stopPropagation();
    location.href = '/settings';
  });
  // Tapping the dimmed area around the card closes it.
  //
  // stopPropagation matters as much as the close: without it the click carries on to the
  // document handler, which by then sees infoOpen already false and steps the photo — so
  // dismissing the panel would also skip the picture it was describing.
  infoPanel.addEventListener('click', event => {
    event.stopPropagation();
    if (event.target.closest('#info-card')) return;
    closeInfo();
  });

  // Coalesced onto a frame: a touch scroll fires this continuously, and building tiles
  // inside the scroll handler itself is what makes a grid stutter.
  let extendQueued = false;
  galleryGrid.addEventListener('scroll', () => {
    settleRow();
    if (extendQueued) return;
    extendQueued = true;
    requestAnimationFrame(() => { extendQueued = false; extendGallery(); });
  }, { passive: true });

  // A drag or a fling has no notches to count, so touch lands wherever it lands: pulled
  // onto the row boundary once it has come to rest. Waiting for the scroll to stop rather
  // than snapping as it moves — the browser owns the momentum, and fighting it mid-fling
  // reads as the grid sticking. Not while the finger is still down, either: the grid would
  // slide out from under it.
  let settleTimer = null, touchingGrid = false;
  function settleRow() {
    clearTimeout(settleTimer);
    if (touchingGrid) return;
    settleTimer = setTimeout(() => {
      const top = alignRow(galleryGrid.scrollTop);
      if (Math.abs(top - galleryGrid.scrollTop) > 1) galleryGrid.scrollTop = top;
    }, 140);
  }
  galleryGrid.addEventListener('touchstart', () => {
    touchingGrid = true;
    clearTimeout(settleTimer);
  }, { passive: true });
  galleryGrid.addEventListener('touchend', () => {
    touchingGrid = false;
    settleRow();
  }, { passive: true });
  galleryGrid.addEventListener('touchcancel', () => {
    touchingGrid = false;
    settleRow();
  }, { passive: true });

  /** Move the grid one row. Jumped rather than animated: smooth scrolling is off on some
   *  of the devices that open this, and a half-applied animation is what leaves a row
   *  part-visible — and every tile in a part-visible row costs a full render. */
  function stepRow(dir) {
    const pitch = rowPitch();
    if (!pitch || !dir) return;
    const at = galleryGrid.scrollTop / pitch;
    const row = dir > 0 ? Math.floor(at + 0.02) : Math.ceil(at - 0.02);
    galleryGrid.scrollTop = alignRow((row + dir) * pitch);
  }

  // A wheel click moves exactly one row, rather than parking one a sliver into view.
  galleryGrid.addEventListener('wheel', event => {
    if (!Math.sign(event.deltaY)) return;
    event.preventDefault();
    stepRow(Math.sign(event.deltaY));
  }, { passive: false });

  for (const [id, dir] of [['gallery-up', -1], ['gallery-down', 1]]) {
    document.getElementById(id).addEventListener('click', event => {
      event.stopPropagation();
      stepRow(dir);
    });
  }

  // A rotation or a resized window changes how many rows fit, and the old sizes would put
  // a part-row back at the bottom.
  addEventListener('resize', () => {
    const pitch = rowPitch();
    if (!galleryOpen || !pitch) return;
    // Held by photo, not by pixel: a different column count puts it on a different row.
    const top = Math.round(galleryGrid.scrollTop / pitch) * columnCount();
    fitGrid();
    snapWindow();
    paintSpacers();
    galleryGrid.scrollTop = alignRow(Math.floor(top / columnCount()) * rowPitch());
  });

  document.getElementById('gallery-close').addEventListener('click', event => {
    event.stopPropagation();
    closeGallery();
  });
  // Anywhere that is not a tile or a control — the bar, the padding, the gaps between
  // tiles — dismisses. Same stopPropagation reasoning as the info panel above.
  gallery.addEventListener('click', event => {
    event.stopPropagation();
    if (event.target.closest('.tile, button')) return;
    closeGallery();
  });
  document.getElementById('open-gallery').addEventListener('click', event => {
    event.stopPropagation();
    openGallery(menuId);
  });

  addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (infoOpen) closeInfo();
    else if (galleryOpen) closeGallery();
    else if (menuOpen) closeMenu();
  });

  function drawClock() {
    // hour12: false rather than a locale guess -- the device's locale is whatever Android
    // decided, and this frame should read the same however it is configured.
    clock.textContent = new Date().toLocaleTimeString([], {
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  }

  async function keepAwake() {
    try {
      const lock = await navigator.wakeLock.request('screen');
      lock.addEventListener('release', () => setTimeout(keepAwake, 1000));
    } catch { /* unsupported or not allowed: the kiosk browser handles it */ }
  }

  drawClock();
  setInterval(drawClock, 10000);
  keepAwake();
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    keepAwake();
    releaseHold();  // back on screen: carry on where the slideshow left off
  });
  const jumpMark = document.getElementById('jump');
  const jumpArrow = document.getElementById('jump-arrow');
  // Lucide chevrons. Only navigation gets one — favouriting and hiding announce
  // themselves with the heart pulse and the toast.
  const CHEVRONS = { next: 'm9 18 6-6-6-6', prev: 'm15 18-6-6 6-6' };

  /** Flash a chevron for a hand-driven step, pointing the way the frame is going. */
  function flashJump(which) {
    jumpArrow.setAttribute('d', CHEVRONS[which]);
    jumpMark.classList.remove('next', 'prev');
    void jumpMark.offsetWidth;  // restart the animation rather than let it continue
    jumpMark.classList.add(which);
  }

  /** Left half goes back through what has already been shown, right half goes on. */
  function step(direction) {
    quickFade = true;
    flashJump(direction === 'back' ? 'prev' : 'next');
    // 'forward' only means anything while standing inside the history; past its end
    // nextSlide falls through to the playlist, which is what tapping right should do.
    jump = direction === 'back' ? 'back' : 'forward';
    if (cutShort) cutShort();
  }

  // A clicked button keeps focus, and with it whatever focus styling the browser or the
  // stylesheet gives it — so the last control pressed sits there looking still engaged.
  // Capture phase, because several handlers below stop propagation.
  document.addEventListener('click', event => {
    const button = event.target.closest('button, a');
    if (button && typeof button.blur === 'function') button.blur();
  }, true);

  // Tap to move — except while the menu is open, where a tap outside it just dismisses
  // it and leaves the photo alone.
  let swipedAt = 0;
  document.addEventListener('click', event => {
    // These handle their own taps; a stray one must not step the photo underneath.
    if (galleryOpen || infoOpen) return;
    if (menuOpen) { closeMenu(); return; }
    // A swipe is followed by a synthetic click; without this the frame would step twice.
    if (Date.now() - swipedAt < 700) return;
    step(event.clientX < innerWidth / 2 ? 'back' : 'forward');
  });

  // Swipe left for the next photo, right for the previous one — the direction the photo
  // itself would travel. Passive listeners: nothing here needs to block scrolling.
  // Nothing happens inside the dead zone; past ARM the swipe will fire on release; and
  // pulling back RETREAT from the furthest point calls it off — measured from the peak
  // rather than the origin, so a long swipe is as easy to cancel as a short one.
  //
  // As fractions of the screen's short edge, not fixed pixels: the same 70px that is a
  // decisive flick on a phone is a twitch on a ten-inch screen. Re-measured per gesture,
  // so rotating or going fullscreen is picked up immediately.
  let DEAD_ZONE = 26, SWIPE_ARM = 70, SWIPE_RETREAT = 35;

  function measureSwipe() {
    const short = Math.min(innerWidth || 0, innerHeight || 0)
      || Math.min(screen.width || 0, screen.height || 0) || 800;
    DEAD_ZONE = Math.max(26, Math.round(short * 0.05));
    SWIPE_ARM = Math.max(70, Math.round(short * 0.16));
    SWIPE_RETREAT = Math.max(35, Math.round(short * 0.07));
  }
  measureSwipe();
  let swipeX = null, swipeY = null;
  // The direction currently committed to, or null. Re-evaluated on every move, so a
  // finger can pull one way, come back to cancel, and set off again — in the same
  // direction or another — without ever lifting. What the pill shows is what happens.
  let armedDir = null, swipeDir = null, swipePeak = 0, swipeLow = 0;
  // The photo the gesture began on, and whether it was a favourite then. The slideshow
  // does not stop for a swipe, so by the time the finger lifts the screen may already
  // be showing the next photo — acting on that one would favourite or hide something
  // the gesture was never about.
  let swipePhoto = null, swipePhotoFavorite = false;
  const edges = {
    up: document.querySelector('.edge.up'),
    down: document.querySelector('.edge.down'),
    prev: document.querySelector('.edge.prev'),
    next: document.querySelector('.edge.next'),
  };

  /** Which action a drag of (dx, dy) is heading towards, or null while it is still
   *  ambiguous. Swiping left advances, and its pill sits on the right — the side the
   *  next photo comes from. */
  function swipeTarget(dx, dy) {
    if (Math.max(Math.abs(dx), Math.abs(dy)) < DEAD_ZONE) return null;
    if (Math.abs(dx) > Math.abs(dy)) return dx < 0 ? 'next' : 'prev';
    return dy < 0 ? 'up' : 'down';
  }

  const edgeHeartOn = document.getElementById('edge-heart-on');
  const edgeHeartOff = document.getElementById('edge-heart-off');
  const edgeFavoriteLabel = document.getElementById('edge-favorite-label');

  /** The up-swipe toggles, so the pill has to promise the right half of the toggle —
   *  for the photo the swipe started on, which is the one it will act on. */
  function describeFavoriteEdge() {
    const removing = swipePhoto ? swipePhotoFavorite : isFavorite;
    edges.up.classList.toggle('removing', removing);
    edgeFavoriteLabel.textContent = t(removing ? 'edge.unfavorite' : 'ui.favorite');
    edgeHeartOn.toggleAttribute('hidden', removing);   // filled promises a favorite
    edgeHeartOff.toggleAttribute('hidden', !removing); // outline promises its removal
  }

  function showEdge(which, travelled, isArmed) {
    for (const [name, pill] of Object.entries(edges)) {
      if (name !== which) { pill.classList.remove('showing', 'armed'); pill.style.opacity = ''; }
    }
    if (!which) return;
    if (which === 'up') describeFavoriteEdge();
    const pill = edges[which];
    const progress = Math.min(1, travelled / SWIPE_ARM);
    pill.classList.add('showing');
    // Armed comes from the gesture state, not from the distance: after a retreat the
    // finger is still far from the origin, but the swipe has been called off and the
    // pill must say so.
    pill.classList.toggle('armed', !!isArmed);
    pill.style.opacity = (0.35 + 0.65 * progress).toFixed(2);
  }

  function clearEdges() {
    for (const pill of Object.values(edges)) {
      pill.classList.remove('showing', 'armed');
      pill.style.opacity = '';
    }
  }

  // Two fingers up opens the gallery. Kept entirely separate from the one-finger gestures:
  // a second finger landing cancels whatever the first was arming, so a two-finger swipe
  // can never also favourite or hide the photo underneath.
  let twoFingerY = null;

  const midpointY = touches =>
    Array.from(touches).reduce((sum, t) => sum + t.clientY, 0) / touches.length;

  addEventListener('touchstart', event => {
    if (event.touches.length >= 2) {
      twoFingerY = midpointY(event.touches);
      swipeX = swipeY = null;      // abandon any one-finger gesture in progress
      armedDir = swipeDir = null;
      swipePeak = swipeLow = 0;
      clearEdges();
      touching = true;
      return;
    }
    measureSwipe();
    const touch = event.changedTouches[0];
    swipeX = touch.clientX;
    swipeY = touch.clientY;
    swipePhoto = currentId;
    swipePhotoFavorite = isFavorite;
    touching = true;
    armedDir = null;
    swipeDir = null;
    swipePeak = swipeLow = 0;
  }, { passive: true });

  addEventListener('touchmove', event => {
    if (twoFingerY !== null) {
      if (event.touches.length < 2) return;
      // Committed on the way rather than on release: the panel should already be there by
      // the time the fingers lift. Up opens the grid, down opens the details.
      const travelled = midpointY(event.touches) - twoFingerY;
      if (Math.abs(travelled) < SWIPE_ARM || galleryOpen || infoOpen) return;
      twoFingerY = null;
      swipedAt = Date.now();     // swallow the synthetic click that follows
      if (travelled < 0) openGallery(currentId);
      else openInfo(currentId);
      return;
    }
    if (swipeX === null || menuOpen || galleryOpen || infoOpen) return;
    const touch = event.changedTouches[0];
    const dx = touch.clientX - swipeX, dy = touch.clientY - swipeY;
    const which = swipeTarget(dx, dy);
    const travelled = which === 'up' || which === 'down' ? Math.abs(dy) : Math.abs(dx);

    if (which !== swipeDir) {     // turned towards a different edge: start again there
      swipeDir = which;
      swipePeak = travelled;
      swipeLow = 0;               // the first arm is a plain SWIPE_ARM from the origin
      armedDir = null;
    }

    if (armedDir) {
      swipePeak = Math.max(swipePeak, travelled);
      if (swipePeak - travelled >= SWIPE_RETREAT) {
        armedDir = null;          // drawn back from the furthest point: called off
        swipeLow = travelled;     // and this is where pushing out again starts from
      }
    } else {
      // Arming is measured from the lowest point since the last cancel, not from where
      // the finger first touched down — otherwise continuing to pull back re-arms it.
      swipeLow = Math.min(swipeLow, travelled);
      if (which && travelled - swipeLow >= SWIPE_ARM) {
        armedDir = which;
        swipePeak = travelled;
      }
    }
    showEdge(which, travelled, armedDir === which);
  }, { passive: true });

  addEventListener('touchcancel', () => {
    touching = false;
    twoFingerY = null;
    releaseHold();
    swipeX = null;
    armedDir = null;
    swipeDir = null;
    swipePeak = swipeLow = 0;
    swipePhoto = null;
    clearEdges();
  }, { passive: true });
  addEventListener('touchend', event => {
    // Still fingers down: a two-finger gesture releasing one finger is not the end of it.
    if (event.touches.length) return;
    touching = false;
    const wasMultiTouch = twoFingerY !== null;
    twoFingerY = null;
    releaseHold();
    clearEdges();
    const direction = wasMultiTouch ? null : armedDir;
    swipeX = null;
    armedDir = null;
    swipeDir = null;
    swipePeak = 0;
    if (!direction || menuOpen) return;
    // Acting on the direction the pill was showing, not on where the finger happens to
    // have ended up, so what was promised is what happens.
    swipedAt = Date.now();

    if (direction === 'next') return step('forward');
    if (direction === 'prev') return step('back');
    const photo = swipePhoto;
    swipePhoto = null;
    if (!photo) return;
    // Up promotes, down discards, both on the photo the gesture began on. Hiding is
    // the one that is hard to take back, so it leaves an Undo behind and the frame
    // moves on rather than lingering on a photo no longer in the library.
    if (direction === 'up') setFavorite(photo, !swipePhotoFavorite);
    else blacklist('photo', null, photo);
  }, { passive: true });

  // The four arrow keys mirror the four swipes: left and right move, up favourites,
  // down hides. Handy with a keyboard or a remote, and the same actions either way.
  addEventListener('keydown', event => {
    if (menuOpen || galleryOpen || infoOpen) return;
    if (!event.key.startsWith('Arrow') && event.key !== ' ') return;
    switch (event.key) {
      case 'ArrowLeft': return step('back');
      case 'ArrowRight':
      case ' ': return step('forward');
      case 'ArrowUp': return currentId && setFavorite(currentId, !isFavorite);
      case 'ArrowDown': return currentId && blacklist('photo', null, currentId);
    }
  });

  // Rotating or resizing changes which photos fit: past a few percent, ask for a fresh,
  // correctly filtered playlist. The photo already preloaded still shows once — one
  // frame is not worth the machinery to cancel it.
  let flipTimer;
  addEventListener('resize', () => {
    clearTimeout(flipTimer);
    flipTimer = setTimeout(() => {
      const now = screenRatio();
      if (listRatio && Math.abs(Math.log(now / listRatio)) > 0.05) {
        // Only marks the list stale, so the next slide fetches one filtered for the new
        // shape. Deliberately does not cut the current slide short: going fullscreen
        // crosses this threshold, and ending the wait there threw the photo you were
        // looking at off the screen the instant you tried to see it bigger.
        cursor = ids.length;
      }
    }, 400);
  });

  // Reload when the page, its stylesheet or this script changes on disk, so editing the
  // frame does not mean walking over to the device. The response is a few bytes and
  // only ever differs while someone is actually editing.
  let assetStamp = null;
  setInterval(async () => {
    try {
      const now = await (await fetch('/api/assets', { cache: 'no-store' })).json();
      const stamp = `${now.html}/${now.css}/${now.js}`;
      if (assetStamp === null) assetStamp = stamp;
      else if (assetStamp !== stamp) location.reload();
    } catch { /* server restarting, most likely; try again next tick */ }
  }, 5000);

  // The quiet hours themselves change rarely; whether they are in force changes every
  // day, so the clock is checked far more often than the setting is re-read.
  applyLanguage();
  readSettings();
  setInterval(readSettings, 60000);
  setInterval(paintNight, 20000);

  // A long-lived tab still accumulates; six hours is a cheap reset. It was two while
  // the frame held full-resolution bitmaps, which is no longer the case.
  setTimeout(() => location.reload(), 6 * 3600 * 1000);

  run();
})();
