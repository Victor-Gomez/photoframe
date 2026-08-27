# Photo Frame

A fullscreen slideshow for a wall-mounted device. One Flask app, and a SQLite database
that lives **with the library** rather than here — `D:\Fotos\zTools\metadata\photos.db`,
filled by the tools in that folder. This project only shows photos: the one thing it writes
is the `rule` table, the blacklist and favourites you set from the frame.

**The photo library is never modified.** Every tool opens photos read-only — no sidecars,
no renames, no EXIF edits, nothing written beside them. The frame re-encodes to screen size
on the fly and keeps nothing on disk.

## The pieces

| file | what it is |
| --- | --- |
| `app.py` | the entry point. Reads the environment, builds the pieces below, serves |
| `photoframe/settings.py` | config.json, with every scalar overridable by environment variable |
| `photoframe/database.py` | the connection to `photos.db`, and lending the file out to a tool |
| `photoframe/rules.py` | the blacklist and the favourites, and the matching they drive |
| `photoframe/preferences.py` | the settings someone sets from a screen, kept in `photos.db` too |
| `photoframe/i18n.py` | what the server says, in both languages |
| `photoframe/library.py` | which photos exist, their shape, their tags, and the shuffled passes |
| `photoframe/imaging.py` | reading headers, rendering to screen size, the in-memory cache |
| `photoframe/frame.py` | wires the above together — the only module that knows the whole graph |
| `photoframe/web/` | the HTTP surface, one blueprint per group of endpoints |
| `web/` | the page — `frame.html`, `frame.css`, `frame.js` — and the two pages that are not the frame, `status.html` and `settings.html`, over `admin.css`. All re-read from disk on every request |
| `config.json` | settings only — ports, timings, paths |
| `tests/` | the suite. `python -m pytest` |

Each piece is handed the collaborators it needs and owns its own state, so the dependencies
run one way: `Database <- Rules <- Library`, with `Renderer` over `RenderCache` beside them.
The one place that would otherwise be a cycle is reopening the database, which has to
rebuild the rules and the index above it — `Database` calls back instead of importing them,
and `frame.py` registers the callbacks.

Everything about the *library* lives in the library's own metadata folder and is not part
of this repository: `store.py` (schema and migrations), `scan.py` (EXIF/XMP), `faces.py`,
`faces_ui.py`, `geocode.py`, `photos.db`, the `.npy` face vectors and `thumbs/`. `app.py`
finds them through `LIBRARY_TOOLS`, and refuses to start if `store.py` is not there rather
than quietly creating an empty database.

There used to be a second copy of `photos.db` in this folder. The two drifted apart for a
week before anyone noticed — one at schema v3, the other at v4, with 287 rules in only one
of them. Hence one database, and no copy here.

## Running it

```bash
pip install -r requirements.txt
python app.py                 # the frame, http://<host>:8080
```

The frame needs only Flask, Pillow and waitress. The library tools — `scan.py`, `faces.py`,
`faces_ui.py`, `geocode.py` — live in the library's metadata folder with their own
requirements, and are run from there.

## Where things live, and why

**`photos.db` holds everything about the library** — the photo list, dimensions, aspect
ratios, capture dates, camera and exposure, GPS, XMP tags, faces, people, and the frame's
own blacklist and favourites. One file, one truth, readable by anything else you write.

**`config.json` holds settings and nothing else** — things about the *program* rather than
the *library*, worth editing by hand. The frame never writes to it, so a hand-edited
setting can't be lost to a tap on the device.

**The database lives with the library, not with the frame.** Both are on `D:`, both are
synced between machines together, and the thing the frame writes — your favourites and
blacklist — belongs to the library rather than to this program. `LIBRARY_TOOLS` and
`DB_FILE` are the two paths to set when deploying elsewhere.

### Settings

| Key | Notes |
| --- | --- |
| `photoDir` | The library. Read-only; originals are never modified. |
| `dbFile` | `photos.db`, in the library's metadata folder. The photo list, ratios, tags, blacklist and favourites. |
| `LIBRARY_TOOLS` | Environment only. Where `store.py` lives. Both this and `DB_FILE` must be set when deploying somewhere the library sits elsewhere. |
| `frameToken` | If set, every request needs `?k=<token>` once; then it rides on a cookie. |
| `logLevel` | The level the frame starts at, before `photos.db` is read. `error` (the default) writes failures only, which on a healthy frame means an empty file. `info` adds the running commentary; `off` writes nothing at all, tracebacks included. `/settings` changes it live. |
| `slideSeconds` | Seconds per photo. The starting point: `/settings` overrides it in `photos.db`. |
| `favoriteWeight` | How many times more often a favourite comes round. `1` disables it. Also overridable from `/settings`. |
| `jpegQuality` | Quality of the JPEG sent to the frame. |
| `encodeThreads` | How many photos may be rendered at once. Each holds a decoded photo, so it stays well below the request thread pool. |
| `avifdec` | Path to libavif's `avifdec`. Its dav1d decoder is multithreaded, which Pillow's is not — measured 849ms vs 1160ms at the median on this library. Falls back to Pillow if it fails. |
| `avifdecShare` | Fraction of renders `avifdec` handles, so both can be measured on real traffic. `GET /api/render-stats` reports medians for each. |
| `avifdecTimeout` | Seconds before a decode is killed. See the warning below — this one is not optional. |
| `renderCacheMB` | Rendered JPEGs kept in memory, so re-viewing a photo costs nothing. `0` turns it off. Memory only; nothing is written to disk. |

Every scalar key can be overridden by the matching environment variable — `PHOTO_DIR`,
`PORT`, `SLIDE_SECONDS` — which is how you run a second instance off one config.
`CONFIG_FILE` chooses the file itself.

### Blacklist and favourites: rules, not flags

They live in the `rule` table:

| kind | meaning |
| --- | --- |
| `blacklist_folder` | never show anything under this folder |
| `blacklist_file` | never show this photo (a path or a glob) |
| `favorite` | show far more often — a path, folder, glob, or `tag:name` |
| `unfavorite` | an exception that overrides a `favorite` rule |

One row can cover a folder, a glob or an XMP tag, which is why several hundred favourites
fit in a few dozen rows. Paths are relative to `photoDir`, case-insensitive, and take
either slash. A bare name with no slash (`Screenshots`) matches at any depth.

- A **folder** rule hides everything under it, and the walk never descends into it.
- **Favourites are not a filter.** A favourite is dealt into the shuffled pass
  `favoriteWeight` times, so it comes round ten times as often as anything else. The pass
  is cut into that many segments with one copy per segment, so it recurs at roughly even
  spacing rather than twice in a row.
- **`tag:<keyword>`** favours every photo carrying that XMP keyword (`dc:subject`), so one
  line replaces hundreds of paths. Globs work: `tag:album_*` covers `album_japon_1`,
  `album_japon_2` and `album_suiza` at once.
- **`unfavorite`** overrides `favorite`, so one photo can be lifted out of a sweeping rule
  without unpicking the rule. Un-favouriting a photo that only a tag or folder favours
  records the exception; favouriting it again removes it. Nothing is left behind either way.

The ⋮ menu on the frame writes these for you.

### Settings someone sets, and settings the machine has

`config.json` is what this *box* is: ports, paths, threads, where `avifdec` lives. It is
edited by hand and the frame never writes to it, so a hand-edited setting cannot be lost to
a tap on a screen.

Everything a person actually chooses lives in `photos.db` instead, in the `meta` table
under `frame.*`, beside the rules — it belongs to the library rather than to the machine
serving it, and follows the library between them. `/settings` writes it, and answers **503**
while the database is on loan rather than reporting a success it did not record. There is
no Save button: every control writes itself the moment it changes, and the toast is the
only acknowledgement — so there is nothing to fill in and forget to press. Unset
means "whatever `config.json` says", so a deployment keeps its own starting point without
anything having to be written first.

| Setting | |
| --- | --- |
| `slideSeconds` | Seconds per photo. |
| `favoriteWeight` | How many times more often a favourite comes round. |
| `quietFrom`, `quietTo` | The quiet hours. Empty means never. |
| `language` | `es` or `en`. Everything a person reads follows it, unless a device says otherwise. |
| `logLevel` | `off`, `error` or `info` — and it takes effect at once, without a restart. |

**Quiet hours: the wall goes dark and the frame stops.** Between the two times the page
fades to black over three seconds and stops advancing — the same hold a hidden tab takes,
so it does not gate the reveal. It is not only about light: a frame in a dark room was
asking the server for a full render every `slideSeconds` all night, for pixels nobody could
see. A tap, click or key wakes it for five minutes. The window usually wraps past midnight,
and is meant to: `23:00`–`07:00` is two ranges, not one. The page re-reads the setting once
a minute, so changing it reaches the wall without anyone walking over.

**Two languages, and two catalogues.** Spanish and English, chosen from `/settings`.
`photoframe/i18n.py` holds what the *server* writes — the two admin pages and what an
endpoint refuses with, translated where it reaches a person rather than where it is raised.
The frame page carries its own copy in `web/frame.js`, because it changes language from the
settings poll without reloading, and has to be able to say "reconnecting" when the server
is precisely what it cannot reach.

**A device may speak something else.** The frame's own language is the default; any one
screen can override it for itself from *Este dispositivo*, and that choice wins wherever it
was made — the frame, both admin pages, and the errors an endpoint answers with. It is kept
in a cookie rather than in `localStorage`, unlike the other per-device setting: `/status`
and `/settings` are rendered by the server, and only a cookie reaches it in time to render
them right rather than after a flash of the wrong language. "Como el marco" clears it. The two overlap barely: one is a status table, the other
is a slideshow. A key missing from one language falls back to Spanish and then to the key
itself, so a half-translated string shows as its name rather than as nothing.

The third kind is neither: **which device wants originals** is a property of the screen in
front of you, so it lives in that browser's own storage and never reaches the server.
`/settings` has it under *Este dispositivo*, which is also the only place it was ever
visible — before, it was `?full=1` and a guess from `hardwareConcurrency`.

## How the frame works

- **Re-encoding is for the device, not for everyone.** `/img/<id>?w=1920&h=1280` returns a
  JPEG cropped to fill exactly that; `/img/<id>` on its own returns the original file, byte
  for byte. The wall device is a low-powered 4-core machine with 4 GB, where a 24 MP
  original is ~96 MB of decoded bitmap and two are alive at once mid-crossfade; a phone or
  a PC decodes one without noticing, and handing over the file costs the server no encode,
  no
  temp file and no SSD write. The page decides from `hardwareConcurrency` and
  `deviceMemory`, biased towards re-encoding, and **drops to re-encoding for good on this
  device the first time an original fails to load**. That fallback is not decoration: the
  guess was wrong once, big files silently failed to decode, the frame skipped them without
  a word, and an entire camera vanished from the rotation for a day. `?full=1` / `?full=0`
  force it either way and are remembered.
- **Rendered JPEGs are cached in memory** (`renderCacheMB`), keyed by path, size *and* the
  file's own timestamp, so a photo replaced by the sync is never served stale. Stepping back
  and forth, or reopening the gallery, costs nothing. Nothing reaches the disk.
- **Startup reads `photos.db` and serves immediately** — no directory walk, no decoding.
  That matters more than it sounds: the walk used to run *before* the server bound its port,
  and on a morning when the filesystem was crawling it took over 25 minutes, during which
  the device couldn't even fetch the stylesheet. If the database is missing or empty the
  frame falls back to walking the library in the background, while already serving.
- **The photo list is read once, at startup.** Nothing re-walks the library on a timer:
  `photos.db` is written by the library's own tools, not by the frame, so there is nothing
  to discover on a schedule. New photos arrive when `/api/db/resume` hands the database
  back after a sync, on `POST /api/rescan`, or on the next start. Walking the disk is only
  ever the fallback for a database that gave nothing — it re-reads every header and leaves
  the aspect index empty while it runs.
- A photo listed in the database but missing from disk is dropped the first time something
  asks for it, so a deletion shows as the next photo rather than an error.
- **Orientation matching, and nothing finer.** A landscape screen gets landscape photos, a
  portrait one portrait, and anything within 5% of square belongs to both. It used to match
  a band around the screen's exact ratio, which turned out to sort the library by the shape
  of the camera that took each photo — 3:2 from the camera, 16:9 from the phone — a
  distinction nobody wanted. `object-fit: cover` crops the difference.
- `/api/playlist` returns the first 300 ids of a shuffled pass plus a `token`; later pages
  come with `?token=…&offset=…`. Sending every id up front cost two seconds before the
  first photo could appear.
- The page crossfades between two fixed `<img>` elements, preloading **and fully decoding**
  the next photo into the hidden layer via `img.decode()`. For AVIF the decode is the
  expensive step, so warming only the HTTP cache would leave it to land exactly at the swap.
- It reuses the same DOM nodes forever and reloads every 6 hours, which is what keeps it
  alive for weeks on a device.
- A hidden page stops advancing. Otherwise a device with its screen off asks for a full
  render every `slideSeconds`, all night. (It also means the slideshow looks frozen when you
  debug it in a background tab — that is the guard working, not a bug.)
- **A step never cancels the photo already being prepared.** "Next" is satisfied by whatever
  is on its way; throwing it away to start another biased the whole frame towards small
  files, because a 24 MP original takes about a second to be ready and a phone photo a
  third of that. Flicking through the library showed only the small ones. Going *back*,
  though, names a particular photo and is honoured even though it cancels work — the
  abandoned playlist id goes back on the list.
- **The gallery grid** (two-finger swipe up, or the menu) shows the whole folder in filename
  order, for dealing with a burst. Tiles are built in batches as you scroll — the largest
  folder here holds 6,282 photos, and building them all up front is ~50,000 DOM elements —
  and each tile's image is only fetched when it scrolls into view, sized to the tile.
- **The info panel** (two-finger swipe down, or the menu) reads `/api/info/<id>`: capture
  date, camera, lens, exposure, the reverse-geocoded place, who is in it, and a link back to
  Google Photos. Separate from `/api/photo/<id>`, which runs on every single slide.
- Controls are sized from the **screen's** short edge, not the viewport. `vmin` follows the
  viewport, and on Android the viewport changes whenever Chrome's toolbar slides in or out —
  so every button silently resized when you tapped one.

## Things worth knowing

**Handing the database to another tool: `POST /api/db/release`, then `/api/db/resume`.**
A tool that rewrites `photos.db` wholesale — `sync_frame_rules.py` does — cannot do it
while the frame holds the file open. Release closes the connection and lets go of the file
(the `-wal` and `-shm` disappear, which is the real proof it is free); resume reopens it and
reloads the index and the rules, picking up new photos without a restart or a reindex. The
frame keeps showing photos throughout: the photo list, ratios, tags and rules are all
already in memory. Only writes and the info panel need the file, and those say so —
favouriting answers **503** rather than reporting a success it did not record. If whatever
released it dies, the frame takes the database back on its own after 15 minutes.

**`/status` is the frame's own health page.** Uptime, how many photos and of which shape,
whether the database is held or on loan, how much goes out re-encoded against how much is
handed over untouched, the two decoders' medians, the render cache's hit rate, the rules in
force, the settings of both kinds and the tail of the log — everything the JSON
endpoints report, on one page. The frame runs headless on a machine across the house, and
"is it still up, and did anything go wrong?" used to mean an ssh session.

**Don't blacklist or favourite from the device while `scan.py` or `faces.py` is running.**
Both write `photos.db`. WAL mode means readers never block, but two writers racing on the
same rows can lose one of the two edits.

**Only the device gets re-encoded photos.** `/img/<id>` sends the original file byte for
byte unless `?w=&h=` are given, and the frame asks for a resize only where it is needed.
Re-encoding exists for the wall device — a low-powered 4-core machine with 4 GB, where a
24 MP AVIF is about 96 MB of decoded bitmap and two are alive at once during a crossfade.
Phones and PCs decode one without noticing, so they get the file as it sits: no decode, no
JPEG encode, no
temp file, no SSD write, and full quality on screen. The choice is made in the browser from
`hardwareConcurrency` and `deviceMemory` (the device reports 4 and 4; everything else here
reports 8 or more) and it is deliberately biased towards re-encoding — guessing wrong on a
PC just means a smaller image, guessing wrong on the device is the frame falling over.
Append `?full=1` or `?full=0` to force it either way; the choice is remembered per device.
The gallery grid always asks for thumbnails regardless, since a screenful of 24 MP
originals is exactly what nobody wants.

**`avifdec` needs its timeout.** A hung decoder once held one of the two encode slots
forever; every image request queued behind it until all eight server threads were parked
and the frame stopped serving anything at all, stylesheet included. `avifdecTimeout` turns
that into a slow render instead of an outage.

**The tools skip `zTools`, and the frame blacklists it.** Otherwise the face thumbnails
inside the library get indexed as photos — the library briefly grew from 35,299 to 43,551
"photos" that way.

**Photo ids are a hash of the relative path.** Move a photo and it becomes a different photo
to the frame, and any rule naming it stops matching. `scan.py` stores a content hash so a
move *can* be recognised, but nothing uses it yet.

**Face detection has a size floor** (`--min-face`, a fraction of image height). Below about
6% the crop is too coarse for ArcFace to embed meaningfully, so small faces cost accuracy as
well as looking blurry — they form junk clusters rather than being merely useless.

## Deploying

The frame runs on a Windows box as a scheduled task at `C:\Projects\photoframe`.

```bash
scp app.py server@frame-host:C:/Projects/photoframe/
scp -r photoframe server@frame-host:C:/Projects/photoframe/
scp web/* server@frame-host:C:/Projects/photoframe/web/
```

`store.py` and `photos.db` are not deployed with it: they live with the library, and the
frame reaches them through `LIBRARY_TOOLS` and `dbFile`.

Leave the server's `config.json` alone — it holds that machine's own paths. `web/` is
re-read per request, so the running frame picks it up within about five seconds and the
device reloads itself. `app.py` needs a restart.

## On the device

Android Chrome, with the system bars removed once via adb:

```bash
adb shell settings put global policy_control immersive.full=*
```

Works on Android 4.4–8 and survives reboots (`policy_control null` reverts it). Worth doing
for more than tidiness: on a 1920×1280 screen the nav bar turned a pixel-perfect 3:2 match
into a 5.6% crop on almost every photo. Without it, 86% of what the frame shows is framed
exactly as it was shot.

Tap or swipe the right half for the next photo, the left half to go back through the ones
already shown (up to 200); swipe up to favourite, down to hide. The four arrow keys do the
same, and space advances. The bottom right shows the clock and the photo's path — tap it to
copy the full path. The bottom left has fullscreen, a heart, and the ⋮ menu.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q      # the server
npm install && npm test        # the page
```

**The server suite** builds a throwaway library of generated images and a fresh database per
test, so nothing touches the real library. It covers the part with no visible failure mode:
which photos a rule matches, how `unfavorite` overrides the generic rules, orientation
filtering, favourite weighting and spacing, playlist paging, that a hide invalidates passes
still being paged through, that releasing the database keeps the rules in force and makes
writes fail loudly, and that rendering never touches an original.

**The page suite** loads the real `web/frame.js` into jsdom against a fake server, because
every slideshow fault so far has lived there while the Python suite passed throughout:
photos silently skipped, a step that showed an unrelated photo, going fullscreen jumping to
the next one. The stub that earns its keep is the image loader — it can make one photo take
a second and another a tenth of that, which is the difference the frame kept getting wrong.

Each test names the bug it came from, and all but one were checked by reintroducing that bug
and confirming the test fails. The exception says so in a comment: a test that has never
been seen to fail is a claim, not a guarantee.

## Credits

- Icons from [Lucide](https://lucide.dev) (ISC).
- Loading animation by alexruix, from [Uiverse](https://uiverse.io/alexruix/neat-tiger-82) (MIT).
- Face detection and recognition by [InsightFace](https://github.com/deepinsight/insightface) (MIT).
