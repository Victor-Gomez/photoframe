"""The words the server puts on a screen, in the two languages it speaks.

The frame page keeps its own copy in web/frame.js: it changes language without a reload
and cannot wait for the server to tell it how to say "reconnecting". This catalogue is for
what the server writes itself — the two admin pages, and what an endpoint refuses with.
"""

DEFAULT = "es"
LANGUAGES = ("es", "en")
# A cookie rather than localStorage, unlike the other per-device setting: these two pages
# are rendered by the server, and only a cookie reaches it in time to render them right.
COOKIE = "frame_lang"
NAMES = {"es": "Español", "en": "English"}


class Invalid(ValueError):
    """A refusal with something to say.

    The key is translated where it reaches a person, so a validator never has to know
    which language asked.
    """

    def __init__(self, key: str, **fields):
        self.key = key
        self.fields = fields
        super().__init__(f"{key} {fields}" if fields else key)


TEXT = {
    "es": {
        "nav.settings": "Ajustes",
        "nav.status": "Estado",
        "nav.frame": "Marco",

        # -- estado ----------------------------------------------------------
        "status.title": "Marco de fotos · estado",
        "tile.uptime": "encendido",
        "tile.photos": "fotos",
        "tile.indexing": "indexando",
        "tile.database": "base de datos",
        "tile.cache": "aciertos de caché",
        "tile.untouched": "sin recodificar",
        "db.open": "abierta",
        "db.released": "cedida",
        "db.releasedFor": "cedida hace {seconds} s · se recupera sola a los {timeout} s",

        "h.library": "Biblioteca",
        "row.folder": "Carpeta",
        "row.landscape": "Horizontales",
        "row.portrait": "Verticales",
        "row.shapes": "Índice de formas",
        "shapes.building": "construyéndose",
        "shapes.ready": "listo",

        "h.preferences": "Preferencias",
        "row.slideSeconds": "Segundos por foto",
        "row.favoriteWeight": "Peso de favoritas",
        "row.quiet": "Horas de silencio",
        "row.language": "Idioma",
        "row.deviceLanguage": "Idioma de este aparato",
        "language.asFrame": "Como el marco",
        "row.logLevel": "Registro",
        "log.off": "Nada",
        "log.error": "Sólo fallos",
        "log.info": "Todo",
        "quiet.window": "de {start} a {end}",
        "quiet.now": "en silencio ahora",
        "quiet.later": "ahora no",
        "quiet.unset": "sin definir",

        "h.database": "Base de datos",
        "row.file": "Archivo",
        "row.state": "Estado",

        "h.served": "Fotos servidas",
        "row.untouched": "Sin recodificar",
        "row.reencoded": "Recodificadas",
        "row.cache": "Caché",
        "served.line": "{requests} peticiones · {mb} MB",
        "cache.line": "{entries} en memoria · {mb} de {budget} MB · "
                      "{hits} aciertos, {misses} fallos",

        "h.decoders": "Decodificadores",
        "decoders.note": "Sólo de lo recodificado.",
        "row.verdict": "Veredicto",
        "decoder.line": "{renders} renders · mediana {median} ms · p90 {p90} ms · "
                        "de {fastest} a {slowest} ms",
        "decoder.none": "sin renders todavía",
        "decoder.share": "cuota",
        "verdict.faster": "avifdec es un {percent} % más rápido en la mediana",
        "verdict.slower": "avifdec es un {percent} % más lento en la mediana",
        "verdict.waiting": "aún no hay renders suficientes (20 de cada uno)",

        "h.rules": "Reglas",
        "rules.folders": "Carpetas ocultas",
        "rules.files": "Fotos ocultas",
        "rules.favorites": "Favoritas",
        "rules.unfavorites": "Excepciones",

        "h.config": "config.json",
        "config.note": "Lo de esta máquina: puertos, rutas, hilos. Se edita a mano.",

        "h.log": "Registro · últimas {lines} líneas",
        "log.empty": "Vacío — con el registro en «sólo fallos», lo normal.",

        # -- ajustes ---------------------------------------------------------
        "settings.title": "Marco de fotos · ajustes",
        "h.global": "Generales",
        "global.note": "Guardados en photos.db, junto a las reglas: valen para todos los marcos.",
        "hint.favoriteWeight": "1 lo desactiva.",
        "hint.quiet": "Se funde a negro y deja de avanzar. Un toque lo despierta cinco minutos.",
        "hint.logLevel": "«Todo» sólo mientras se diagnostica algo.",
        "quiet.from": "de",
        "quiet.to": "a",
        "saved": "Guardado",
        "device.nostorage": "Este navegador no deja guardar nada.",
        "db.busy": "La base de datos está cedida; ahora mismo no se puede guardar.",

        "h.device": "Este dispositivo",
        "device.note": "Guardados sólo en este navegador, no en el servidor.",
        "row.images": "Imágenes",
        "images.auto": "Automático",
        "images.originals": "Originales, sin tocar",
        "images.reencoded": "Recodificadas al tamaño de la pantalla",
        "device.guess": "Aquí, en automático: {choice} ({cores} núcleos, {memory} GB).",

        # -- errores ---------------------------------------------------------
        "error.dbBusy": "la base de datos está en mantenimiento; inténtalo en un momento",
        "error.unknownSetting": "ajuste desconocido: {names}",
        "error.time": "{name}: se espera HH:MM",
        "error.number": "{name}: se espera un número",
        "error.choice": "{name}: {value} no es una opción",
        "error.quietEnds": "las horas de silencio necesitan principio y fin",
        "error.folderMismatch": "esa carpeta no contiene esta foto",
        "error.scope": "el ámbito ha de ser 'photo' o 'folder'",
        "error.nothingToUndo": "no hay nada que deshacer",
        "error.photoGone": "esa foto ya no está",
        "error.stillHidden": "otra regla la sigue ocultando",
    },
    "en": {
        "nav.settings": "Settings",
        "nav.status": "Status",
        "nav.frame": "Frame",

        "status.title": "Photo frame · status",
        "tile.uptime": "up",
        "tile.photos": "photos",
        "tile.indexing": "indexing",
        "tile.database": "database",
        "tile.cache": "cache hits",
        "tile.untouched": "untouched",
        "db.open": "open",
        "db.released": "on loan",
        "db.releasedFor": "on loan for {seconds} s · taken back after {timeout} s",

        "h.library": "Library",
        "row.folder": "Folder",
        "row.landscape": "Landscape",
        "row.portrait": "Portrait",
        "row.shapes": "Shape index",
        "shapes.building": "building",
        "shapes.ready": "ready",

        "h.preferences": "Preferences",
        "row.slideSeconds": "Seconds per photo",
        "row.favoriteWeight": "Favourite weight",
        "row.quiet": "Quiet hours",
        "row.language": "Language",
        "row.deviceLanguage": "This device's language",
        "language.asFrame": "As the frame",
        "row.logLevel": "Log",
        "log.off": "Nothing",
        "log.error": "Failures only",
        "log.info": "Everything",
        "quiet.window": "{start} to {end}",
        "quiet.now": "quiet now",
        "quiet.later": "not now",
        "quiet.unset": "not set",

        "h.database": "Database",
        "row.file": "File",
        "row.state": "State",

        "h.served": "Photos served",
        "row.untouched": "Untouched",
        "row.reencoded": "Re-encoded",
        "row.cache": "Cache",
        "served.line": "{requests} requests · {mb} MB",
        "cache.line": "{entries} in memory · {mb} of {budget} MB · "
                      "{hits} hits, {misses} misses",

        "h.decoders": "Decoders",
        "decoders.note": "Re-encoded photos only.",
        "row.verdict": "Verdict",
        "decoder.line": "{renders} renders · median {median} ms · p90 {p90} ms · "
                        "{fastest} to {slowest} ms",
        "decoder.none": "no renders yet",
        "decoder.share": "share",
        "verdict.faster": "avifdec is {percent}% faster at the median",
        "verdict.slower": "avifdec is {percent}% slower at the median",
        "verdict.waiting": "not enough renders yet (20 each)",

        "h.rules": "Rules",
        "rules.folders": "Hidden folders",
        "rules.files": "Hidden photos",
        "rules.favorites": "Favourites",
        "rules.unfavorites": "Exceptions",

        "h.config": "config.json",
        "config.note": "This machine's own: ports, paths, threads. Edited by hand.",

        "h.log": "Log · last {lines} lines",
        "log.empty": "Empty — normal with the log at “failures only”.",

        "settings.title": "Photo frame · settings",
        "h.global": "General",
        "global.note": "Saved in photos.db beside the rules: every frame gets them.",
        "hint.favoriteWeight": "1 turns it off.",
        "hint.quiet": "Fades to black and stops advancing. A touch wakes it for five minutes.",
        "hint.logLevel": "“Everything” only while diagnosing something.",
        "quiet.from": "from",
        "quiet.to": "to",
        "saved": "Saved",
        "device.nostorage": "This browser will not store anything.",
        "db.busy": "The database is on loan; nothing can be saved right now.",

        "h.device": "This device",
        "device.note": "Saved in this browser only, never on the server.",
        "row.images": "Images",
        "images.auto": "Automatic",
        "images.originals": "Originals, untouched",
        "images.reencoded": "Re-encoded to the size of the screen",
        "device.guess": "Automatic here: {choice} ({cores} cores, {memory} GB).",

        "error.dbBusy": "the database is being worked on; try again in a moment",
        "error.unknownSetting": "unknown setting: {names}",
        "error.time": "{name}: expected HH:MM",
        "error.number": "{name}: expected a number",
        "error.choice": "{name}: {value} is not one of the choices",
        "error.quietEnds": "quiet hours need both a start and an end",
        "error.folderMismatch": "that folder does not contain this photo",
        "error.scope": "scope must be 'photo' or 'folder'",
        "error.nothingToUndo": "nothing to undo",
        "error.photoGone": "that photo is no longer there",
        "error.stillHidden": "another entry still hides it",
    },
}

# Every language says everything, or a page comes out half in the other one.
assert set(TEXT["es"]) == set(TEXT["en"]), sorted(set(TEXT["es"]) ^ set(TEXT["en"]))


def chosen(cookie_value, fallback: str) -> str:
    """The language this device asked for, or the one every frame is set to."""
    return cookie_value if cookie_value in LANGUAGES else fallback


def translator(language: str):
    """The `t` a template is handed.

    Falls back to Spanish and then to the key itself, so a string added in one language
    shows as its key rather than as nothing at all.
    """
    words = TEXT.get(language, TEXT[DEFAULT])

    def t(key: str, **fields) -> str:
        text = words.get(key) or TEXT[DEFAULT].get(key) or key
        return text.format(**fields) if fields else text

    return t


def say(language: str, error: Invalid) -> str:
    return translator(language)(error.key, **error.fields)
