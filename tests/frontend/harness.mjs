/**
 * Boots web/frame.js inside jsdom against a fake server, so the slideshow's own logic can
 * be driven and observed.
 *
 * Everything that broke on the frame this year broke here rather than in app.py: photos
 * silently skipped, a step that showed an unrelated photo, going fullscreen jumping to the
 * next one. All of it lived in the loop that decides which photo to prepare and when — and
 * none of it was reachable from the Python suite, which never loads this file.
 *
 * The one stub that earns its keep is the image loader. Real browsers take longer over a
 * 24 MP original than over a phone photo, and that difference is what made the frame skip
 * whole cameras. `photoDelay` reproduces it, so the bug is expressible as a test.
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'web');

/** The real page, with the two Jinja placeholders stripped. */
function pageHtml() {
  return readFileSync(join(WEB, 'frame.html'), 'utf8')
    .replace(/\{\{[^}]*\}\}/g, '')
    .replace(/<link rel="stylesheet"[^>]*>/, '');
}

export function makeLibrary(count = 40) {
  // Alternating shapes and speeds, mirroring the real library: the camera's files are big
  // and slow, the phone's small and quick.
  return Array.from({ length: count }, (_, i) => {
    const camera = i % 3 !== 2;
    return {
      id: `id${String(i).padStart(3, '0')}`,
      file: camera ? `DSC0${1000 + i}.avif` : `IMG_2024${i}.avif`,
      folder: camera ? 'Japon' : 'Movil',
      camera,
    };
  });
}

/**
 * @param {object} options
 * @param {(photo) => number} options.photoDelay  ms before an image reports itself loaded
 * @param {number} options.slideSeconds
 */
export async function boot({ photos = makeLibrary(), photoDelay = () => 5, slideSeconds = 60,
                             photoFails = () => false, quiet = null, language = 'es',
                             deviceLanguage = '',
                             width = 1920, height = 1080, hardwareConcurrency = 4 } = {}) {
  const dom = new JSDOM(pageHtml(), {
    url: 'http://frame.test/',
    pretendToBeVisual: true,       // gives requestAnimationFrame
    runScripts: 'outside-only',
  });
  const { window } = dom;
  const byId = new Map(photos.map(p => [p.id, p]));
  const requested = [];            // every /img/ URL the page asked for, in order

  Object.defineProperty(window.screen, 'width', { value: width, configurable: true });
  Object.defineProperty(window.screen, 'height', { value: height, configurable: true });
  window.innerWidth = width;
  window.innerHeight = height;

  Object.defineProperty(window.navigator, 'hardwareConcurrency',
    { value: hardwareConcurrency, configurable: true });
  window.navigator.wakeLock = { request: async () => ({ addEventListener() {} }) };
  window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
  window.IntersectionObserver = class {
    observe() {} unobserve() {} disconnect() {}
  };
  // What the server would have done with the cookie before rendering the page.
  if (deviceLanguage) {
    window.document.cookie = `frame_lang=${deviceLanguage}`;
    window.document.documentElement.lang = deviceLanguage;
  }
  window.document.documentElement.requestFullscreen = async () => {};
  window.document.exitFullscreen = async () => {};

  // jsdom never fetches images. Resolving `src` on a timer is what lets a test say "this
  // photo is slow" and assert the frame still waits for it.
  const proto = window.HTMLImageElement.prototype;
  const nativeSrc = Object.getOwnPropertyDescriptor(proto, 'src');
  Object.defineProperty(proto, 'src', {
    configurable: true,
    get() { return nativeSrc.get.call(this); },
    set(value) {
      nativeSrc.set.call(this, value);
      // Read it back: jsdom resolves src to an absolute URL, so comparing the raw value
      // later would never match and every load would look superseded.
      const resolved = nativeSrc.get.call(this);
      requested.push(String(value));
      const id = String(value).split('/img/')[1]?.split('?')[0];
      const photo = byId.get(id);
      const wait = photo ? photoDelay(photo) : 1;
      this._naturalWidth = 0;
      this._complete = false;
      const broken = photo ? photoFails(photo) : false;
      window.setTimeout(() => {
        if (nativeSrc.get.call(this) !== resolved) return;   // superseded before it landed
        if (broken) {
          // What a corrupt file looks like: the server answers 415 and the image errors.
          this._complete = true;
          this.dispatchEvent(new window.Event('error'));
          return;
        }
        this._naturalWidth = 1920;
        this._complete = true;
        this.dispatchEvent(new window.Event('load'));
      }, wait);
    },
  });
  Object.defineProperty(proto, 'naturalWidth', {
    configurable: true,
    get() { return this._naturalWidth || 0; },
  });
  // jsdom reports every image complete the instant src is set, which makes the app's
  // loaded() short-circuit and declare the photo unreadable before the timer above fires.
  Object.defineProperty(proto, 'complete', {
    configurable: true,
    get() { return !!this._complete; },
  });
  proto.decode = function () { return Promise.resolve(); };

  window.fetch = async (url) => {
    const path = String(url);
    const json = (body) => ({ ok: true, status: 200, json: async () => body });
    if (path.startsWith('/api/playlist')) {
      return json({
        ids: photos.map(p => p.id), token: 't', total: photos.length,
        slideSeconds, indexing: false,
      });
    }
    if (path.startsWith('/api/photo/')) {
      const p = byId.get(path.split('/api/photo/')[1]) || {};
      return json({ file: p.file, folder: p.folder, fullPath: `D:\\Fotos\\${p.folder}\\${p.file}` });
    }
    if (path.startsWith('/api/info/')) {
      const p = byId.get(path.split('/api/info/')[1]) || {};
      return json({
        file: p.file, folder: p.folder, fullPath: `D:\\Fotos\\${p.folder}\\${p.file}`,
        taken: '2025-10-12T13:45:09', make: 'SONY', model: 'ILCE-7M3',
        lens: 'FE 28-70mm F3.5-5.6 OSS', aperture: 7.1, shutter: 0.008, iso: 800,
        focal_length: 29, compensation: -1,
      });
    }
    if (path.startsWith('/api/assets')) return json({ css: 1, js: 1, html: 1 });
    if (path.startsWith('/api/settings')) {
      return json({
        slideSeconds, language,
        quietFrom: quiet ? quiet.from : '', quietTo: quiet ? quiet.to : '',
      });
    }
    return json({});
  };

  window.eval(readFileSync(join(WEB, 'frame.js'), 'utf8'));

  const api = {
    window,
    requested,
    /** The photo on screen, by filename. */
    shown: () => (window.document.getElementById('path').textContent || '').split('\\').pop(),
    key: (k) => window.dispatchEvent(new window.KeyboardEvent('keydown', { key: k, bubbles: true })),
    tick: (ms) => new Promise(r => setTimeout(r, ms)),
    /** Wait until something is on screen, or give up. */
    async settle(ms = 400) { await api.tick(ms); return api.shown(); },
    /** Wait for the photo on screen to stop being `from`. Returns what replaced it. */
    async waitForChange(from, timeout = 8000) {
      const deadline = Date.now() + timeout;
      while (Date.now() < deadline) {
        await api.tick(50);
        if (api.shown() && api.shown() !== from) return api.shown();
      }
      return api.shown();
    },
    close: () => dom.window.close(),
  };
  // Wait for the first photo rather than a fixed delay: a test that makes photos slow
  // would otherwise start with an empty screen and compare against it.
  await api.waitForChange('', 10000);
  return api;
}
