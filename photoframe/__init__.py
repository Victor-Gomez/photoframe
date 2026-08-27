"""The photo frame, in pieces.

  settings  config.json
  database  the connection to photos.db, and lending the file out
  rules     the blacklist and the favourites
  prefs     the settings someone set from a screen, kept in photos.db too
  library   which photos exist, their shape and their tags
  imaging   reading headers, rendering, the render cache
  frame     wires the above together
  web/      the HTTP surface, one blueprint per group of endpoints
"""
