/**
 * The slideshow loop. Every test here is a bug that actually reached the wall.
 *
 * These run in jsdom rather than against the server, because that is where the faults were:
 * the Python suite passed throughout all of them.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { boot, makeLibrary } from './harness.mjs';

// The ambient crossfade is 1.6s and a hand-driven one 0.6s, and `prepare` waits out the
// fade before it even asks for the next photo. Anything shorter than this measures the
// fade rather than the logic.
const SETTLE = 2500;

test('going back works even while the next photo is still being prepared', async () => {
  // The timing is the whole test. After each reveal the frame starts preparing the next
  // photo, and the bug this catches was a guard that made a direction key do nothing while
  // that was in flight — so pressing left showed the next unrelated photo instead of going
  // back. With instant loads the window is too small to press inside, which is why these
  // photos take 1.5s and the key lands 700ms in.
  const frame = await boot({ photoDelay: () => 1500 });
  try {
    const a = frame.shown();
    frame.key('ArrowRight');
    const b = await frame.waitForChange(a);
    assert.notEqual(b, a, 'right should have moved on');

    await frame.tick(700);          // the preparation of the photo after b is now running
    frame.key('ArrowLeft');
    const back = await frame.waitForChange(b);
    assert.equal(back, a, 'left should go back to the previous photo, not on to a new one');
  } finally { frame.close(); }
});

test('left and right walk back and forth over the same two photos', async () => {
  const frame = await boot({ photoDelay: () => 1500 });
  try {
    const a = frame.shown();
    frame.key('ArrowRight');
    const b = await frame.waitForChange(a);

    const seen = [];
    for (const key of ['ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight']) {
      const from = frame.shown();
      await frame.tick(700);
      frame.key(key);
      seen.push(await frame.waitForChange(from));
    }
    assert.deepEqual(seen, [a, b, a, b]);
  } finally { frame.close(); }
});

// NOTE: this one is weaker than it looks. It states the behaviour, but it passes with and
// without the fix it was written for, so it has never been shown to catch the fault — the
// original (whole cameras missing from the rotation for a day) could not be reproduced in
// jsdom, and was confirmed fixed by stepping through the real frame in a real browser
// instead: 0/12 camera photos before, 12/14 after, at the same rate. Treat a pass here as
// "the behaviour is still stated", not "the regression is guarded".
test('stepping quickly still shows the photos that are slow to load', async () => {
  // The real shape of the library: the camera's files take about a second to be ready,
  // the phone's a third of that.
  const frame = await boot({ photoDelay: (photo) => (photo.camera ? 900 : 120) });
  try {
    const seen = new Set();
    for (let i = 0; i < 10; i++) {
      frame.key('ArrowRight');
      await frame.tick(1200);          // faster than a camera photo can be prepared
      seen.add(frame.shown());
    }
    const cameras = [...seen].filter(name => name.includes('DSC'));
    // Before the fix this was zero: each press threw away the preparation in flight and
    // took another photo, so only the quick ones ever finished. Whole cameras vanished.
    assert.ok(cameras.length > 0,
      `no camera photos survived fast stepping; saw ${[...seen].join(', ')}`);
  } finally { frame.close(); }
});

test('a change of viewport shape does not jump to the next photo', async () => {
  // Marking the playlist stale is right; cutting the current slide short is not. Anything
  // that reshapes the viewport — going fullscreen, a browser toolbar, a rotation — would
  // otherwise throw the photo you were looking at off the screen.
  //
  // 1.778 -> 1.600 crosses the 5% threshold with room to spare. Note that going fullscreen
  // from a maximised 2048x1096 does *not*: that is a 4.98% change and slips under it.
  const frame = await boot({ width: 1920, height: 1080 });
  try {
    const before = frame.shown();
    frame.window.innerHeight = 1200;
    frame.window.dispatchEvent(new frame.window.Event('resize'));
    // 400ms of debounce, then the loop would have to wake, reveal and relabel. Measured at
    // about 2.5s with the fault present, so this waits well past it.
    await frame.tick(4000);
    assert.equal(frame.shown(), before,
      'the photo on screen should have stayed put');
  } finally { frame.close(); }
});

test('an unreadable photo is skipped rather than stalling the frame', async () => {
  // A corrupt file: the server answers 415 and the image errors. (A photo that hangs for
  // ever is handled too, but by the 20s cap in prepare(), which is too slow to assert on.)
  const photos = makeLibrary(12);
  const broken = new Set([photos[1].id, photos[2].id]);
  const frame = await boot({ photos, photoFails: (photo) => broken.has(photo.id) });
  try {
    const first = frame.shown();
    frame.key('ArrowRight');
    await frame.tick(SETTLE);
    const now = frame.shown();
    assert.notEqual(now, first, 'the frame should have moved past the broken photos');
    assert.ok(now.length > 0, 'and landed on a real one rather than going blank');
  } finally { frame.close(); }
});

test('the info panel formats what the camera recorded', async () => {
  const frame = await boot();
  try {
    const { document } = frame.window;
    document.getElementById('more').dispatchEvent(
      new frame.window.MouseEvent('click', { bubbles: true }));
    await frame.tick(150);
    document.getElementById('open-info').dispatchEvent(
      new frame.window.MouseEvent('click', { bubbles: true }));
    await frame.tick(300);

    const fields = {};
    for (const field of document.querySelectorAll('#info-rows .field')) {
      const label = field.querySelector('dt')?.textContent?.trim();
      if (label) fields[label] = field.querySelector('dd')?.textContent?.trim();
    }

    assert.equal(fields['Fecha'], '12 oct 2025 · 13:45');
    // EXIF says ILCE-7M3 and "FE 28-70mm F3.5-5.6 OSS"; neither is what anyone calls them.
    assert.equal(fields['Cámara'], 'Sony α7 III');
    assert.equal(fields['Objetivo'], 'Sony 28-70mm');
    // Aperture, shutter, ISO, focal length, then the compensation.
    assert.equal(fields['Parámetros'], 'f/7.1 · 1/125s · ISO 800 · 29 mm · -1 EV');
  } finally { frame.close(); }
});

/* ---- quiet hours ---------------------------------------------------------- */

const clock = (minutesFromNow) => {
  const when = new Date(Date.now() + minutesFromNow * 60000);
  return `${String(when.getHours()).padStart(2, '0')}:${String(when.getMinutes()).padStart(2, '0')}`;
};

test('the frame goes dark and stops advancing inside the quiet hours', async () => {
  // Not decoration: a wall in a dark bedroom asked the server for a full render every
  // slideSeconds all night, for pixels nobody could see.
  const frame = await boot({ slideSeconds: 0.2, quiet: { from: clock(-60), to: clock(60) } });
  try {
    const first = frame.shown();
    assert.ok(first, 'the photo already prepared still shows: quiet hours gate advancing, not the reveal');

    // Past the crossfade, which `prepare` waits out before it even asks for the next
    // photo: anything shorter measures the fade rather than the hold.
    await frame.tick(SETTLE);
    assert.equal(frame.shown(), first, 'nothing should advance while the frame is asleep');
    assert.ok(frame.window.document.body.classList.contains('asleep'));
  } finally { frame.close(); }
});

test('a key at three in the morning wakes it', async () => {
  const frame = await boot({ slideSeconds: 0.2, quiet: { from: clock(-60), to: clock(60) } });
  try {
    const first = frame.shown();
    await frame.tick(600);

    frame.key('ArrowRight');
    assert.notEqual(await frame.waitForChange(first), first, 'a tap should be answered, not ignored');
    assert.ok(!frame.window.document.body.classList.contains('asleep'));
  } finally { frame.close(); }
});

// A control, not a guard: it states that the feature is inert outside its window, and
// it passes with and without the quiet hours implemented at all.
test('quiet hours outside the window change nothing', async () => {
  const frame = await boot({ slideSeconds: 0.2, quiet: { from: clock(60), to: clock(120) } });
  try {
    const first = frame.shown();
    assert.notEqual(await frame.waitForChange(first), first, 'the slideshow should carry on');
    assert.ok(!frame.window.document.body.classList.contains('asleep'));
  } finally { frame.close(); }
});

/* ---- language ------------------------------------------------------------- */

test('the frame changes language from the setting, without a reload', async () => {
  const frame = await boot({ language: 'en' });
  try {
    const { document } = frame.window;
    assert.equal(document.documentElement.lang, 'en');
    assert.equal(document.getElementById('hide-photo').textContent, 'Hide this photo');
    assert.equal(document.getElementById('open-settings').textContent, 'Settings');
    // Attributes too, not only text: the buttons are icons and say nothing else.
    assert.equal(document.getElementById('more').getAttribute('aria-label'), 'More options');
    // And inside a template, whose tiles are cloned long after the language was applied.
    assert.equal(
      document.getElementById('gallery-tile').content.querySelector('.tile-hide')
        .getAttribute('aria-label'), 'Hide');
  } finally { frame.close(); }
});

test('an unknown language leaves the frame in Spanish', async () => {
  const frame = await boot({ language: 'de' });
  try {
    assert.equal(frame.window.document.getElementById('hide-photo').textContent, 'Ocultar esta foto');
  } finally { frame.close(); }
});

test('a device that asked for its own language keeps it', async () => {
  // The frame is set to Spanish and says so on every poll; this screen was told English.
  const frame = await boot({ language: 'es', deviceLanguage: 'en' });
  try {
    assert.equal(frame.window.document.getElementById('hide-photo').textContent, 'Hide this photo');
    await frame.tick(300);   // long enough for the settings poll to have answered
    assert.equal(frame.window.document.getElementById('hide-photo').textContent, 'Hide this photo');
  } finally { frame.close(); }
});
