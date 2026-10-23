#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# <bitbar.title>Cinemix Now Playing</bitbar.title>
# <bitbar.version>1.0</bitbar.version>
# <bitbar.author>Romain</bitbar.author>
# <bitbar.desc>Affiche le morceau en cours de lecture sur Cinemix (radio de bandes originales de films).</bitbar.desc>
# <bitbar.dependencies>python3</bitbar.dependencies>
# <bitbar.abouturl>https://github.com/Romauge/cinemix-swiftbar</bitbar.abouturl>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>

"""
SwiftBar plugin - Cinemix Now Playing
=====================================
Affiche dans la barre de menus macOS le morceau actuellement diffusé sur Cinemix
(radio de bandes originales de films) : titre, artiste, album, durée, jaquette,
prochain morceau, et raccourcis vers la radio et vers une plateforme d'écoute au choix.

Plugin non officiel, sans lien avec Cinemix : il lit les pages publiques de la radio
(https://cinemix.us/SAM/playing.php et la liste « Coming up » sur vhost.fastserv.com),
dont la structure peut changer sans préavis.

Installation :
  1. Installer SwiftBar : https://swiftbar.app  (ou `brew install --cask swiftbar`)
  2. Lancer SwiftBar et choisir un dossier de plugins
  3. Copier ce fichier dans ce dossier et le rendre exécutable : `chmod +x cinemix.30s.py`
     (le « 30s » du nom = rafraîchissement toutes les 30 secondes)

Prérequis : macOS et Python 3.7+, stdlib uniquement (aucun paquet à installer).
Facultatif : `sips` (inclus dans macOS) et `swiftc` (Xcode ou Command Line Tools) donnent
la jaquette arrondie et l'icône de la barre de menus. Sans `swiftc`, le plugin garde un
affichage plus simple. Au premier lancement, il compile en arrière-plan un petit outil Swift
(son code est dans CARD_SWIFT, plus bas) qui est rangé dans ~/.config/cinemix.

Réglages : menu « Plateforme d'écoute » (Apple Music, Spotify, Deezer, Qobuz, YouTube Music).
"""

from __future__ import annotations  # syntaxe `str | None` sur Python < 3.10

import base64
import functools
import hashlib
import html
import os
import re
import struct
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.parse
import urllib.request

URL = "https://cinemix.us/SAM/playing.php"
# Page SAM de la radio avec la liste « Coming up » (titre, artiste et album des prochains morceaux)
COMING_URL = "https://vhost.fastserv.com/~cinemix/samPHPweb/web/playing.php"
# Station Cinemix sur Apple Music. Schéma `music://` -> ouvre directement
# l'app Music sur macOS (au lieu de passer par le navigateur).
STATION_URL = "music://music.apple.com/fr/station/cinemix/ra.1461058420"
TIMEOUT = 8
USER_AGENT = "Mozilla/5.0 (Macintosh) Cinemix-SwiftBar/1.0"

# Plateformes d'écoute. `listen` ouvre la station Cinemix (None si elle n'y existe pas) ;
# `search` cherche « Artiste - Titre » ({q} est encodé pour une URL).
PLATFORMS = {
    "apple": {
        "name": "Apple Music",
        "listen": STATION_URL,
        "search": "music://music.apple.com/search?term={q}",
    },
    "spotify": {
        "name": "Spotify",
        "listen": None,
        "search": "https://open.spotify.com/search/{q}",
    },
    "deezer": {
        "name": "Deezer",
        "listen": None,
        "search": "https://www.deezer.com/search/{q}",
    },
    "qobuz": {
        "name": "Qobuz",
        "listen": None,
        "search": "https://www.qobuz.com/fr-fr/search?q={q}",
    },
    "youtube": {
        "name": "YouTube Music",
        "listen": None,
        "search": "https://music.youtube.com/search?q={q}",
    },
}
DEFAULT_PLATFORM = "apple"

# Apparence
COVER_SIZE = 192          # définition de la jaquette (pixels, pour les écrans Retina)
COVER_DISPLAY = 80        # taille d'affichage de la jaquette dans le menu (points)
INFO_COLOR_LIGHT = 59     # couleur ANSI 256 du texte d'information, mode clair
INFO_COLOR_DARK = 252     # idem, mode sombre
HEADER_SIZE = 10          # taille du titre de section « À SUIVRE »
UPCOMING_WIDTH = 60       # largeur max (caractères) des lignes de « À suivre » avant retour à la ligne
TITLE_ICON_PT = 12        # taille de l'icône « radio » de la barre de menus (points)
TITLE_ICON_RAISE = 1.5    # décalage vers le haut de cette icône (points), pour l'aligner sur le texte
MENU_ICON_PT = 13         # taille des icônes du menu (points)
MENU_ICON_BOX = (20, 18)  # cadre commun à toutes les icônes du menu (largeur, hauteur, en points)

# Fichiers
SCRIPT = os.path.abspath(__file__)
# Chemin fixe : le terminal n'a pas les variables d'environnement que SwiftBar définit
CONFIG_DIR = os.path.expanduser("~/.config/cinemix")
CONFIG_FILE = os.path.join(CONFIG_DIR, "platform")
CARD_BIN = os.path.join(CONFIG_DIR, "cinemix-card")
CACHE_MAX_AGE = 24 * 3600  # les images en cache plus anciennes sont supprimées

# Outil Swift (AppKit) qui dessine la carte : jaquette arrondie + bordure + textes.
CARD_SWIFT = r'''import AppKit

// usage : cinemix-card <jaquette.png|-> <sortie.png> <1 si mode sombre> <ligne>...
//         cinemix-card --icon <nom SF Symbol> <taille en points> <sortie.png> <largeur> <hauteur>
//         cinemix-card --symbol <nom SF Symbol> <taille en points> <sortie.png> <marge basse en pixels>
let args = CommandLine.arguments

if args[1] == "--icon" {
    // Symbole centré dans un cadre de taille fixe : toutes les icônes du menu ont la même
    // largeur, donc les textes des lignes s'alignent (comme dans les menus macOS).
    let canvas = NSSize(width: CGFloat(Double(args[5])!), height: CGFloat(Double(args[6])!))
    let config = NSImage.SymbolConfiguration(pointSize: CGFloat(Double(args[3])!), weight: .regular)
    guard let base = NSImage(systemSymbolName: args[2], accessibilityDescription: nil),
          let symbol = base.withSymbolConfiguration(config) else { exit(1) }
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(canvas.width * 2), pixelsHigh: Int(canvas.height * 2),
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = canvas
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let box = NSRect(x: (canvas.width - symbol.size.width) / 2, y: (canvas.height - symbol.size.height) / 2,
                     width: symbol.size.width, height: symbol.size.height)
    symbol.draw(in: box)
    NSColor.black.set()
    box.fill(using: .sourceIn)
    NSGraphicsContext.restoreGraphicsState()
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: args[4]))
    exit(0)
}

if args[1] == "--symbol" {
    // Symbole dessiné en noir (image « template », teintée par macOS), à l'échelle x2
    let config = NSImage.SymbolConfiguration(pointSize: CGFloat(Double(args[3])!) * 2, weight: .regular)
    guard let base = NSImage(systemSymbolName: args[2], accessibilityDescription: nil),
          let symbol = base.withSymbolConfiguration(config) else { exit(1) }
    // Marge transparente sous le symbole : macOS centre l'image, le symbole monte d'autant
    let pad = CGFloat(Double(args[5])!)
    let box = NSRect(origin: NSPoint(x: 0, y: pad), size: symbol.size)
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(ceil(box.width)), pixelsHigh: Int(ceil(box.height + pad)),
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    symbol.draw(in: box)
    NSColor.black.set()
    box.fill(using: .sourceIn)
    NSGraphicsContext.restoreGraphicsState()
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: args[4]))
    exit(0)
}

let cover = args[1] == "-" ? nil : NSImage(contentsOfFile: args[1])
let dark = args[3] == "1"
let lines = Array(args[4...])

let scale: CGFloat = 2
let size: CGFloat = 80       // côté de la jaquette (points)
let radius: CGFloat = 12
let gap: CGFloat = 12
let maxText: CGFloat = 340

let textColor = dark ? NSColor(srgbRed: 0.78, green: 0.78, blue: 0.80, alpha: 1)
                     : NSColor(srgbRed: 0.35, green: 0.35, blue: 0.37, alpha: 1)
let borderColor = dark ? NSColor(white: 1, alpha: 0.18) : NSColor(white: 0, alpha: 0.14)

let para = NSMutableParagraphStyle()
para.lineBreakMode = .byTruncatingTail
func attrs(_ i: Int) -> [NSAttributedString.Key: Any] {
    [.font: NSFont.systemFont(ofSize: 13, weight: i == 0 ? .medium : .regular),
     .foregroundColor: textColor, .paragraphStyle: para]
}

let heights = lines.enumerated().map { NSAttributedString(string: $1, attributes: attrs($0)).size().height }
let widths = lines.enumerated().map { NSAttributedString(string: $1, attributes: attrs($0)).size().width }
let textW = min(ceil(widths.max() ?? 0), maxText)
let coverW: CGFloat = cover == nil ? 0 : size + gap
let width = coverW + textW + 2

let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(width * scale), pixelsHigh: Int(size * scale),
                           bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                           colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
rep.size = NSSize(width: width, height: size)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

if let cover = cover {
    let rect = NSRect(x: 0.5, y: 0.5, width: size - 1, height: size - 1)
    let path = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
    NSGraphicsContext.saveGraphicsState()
    path.addClip()
    cover.draw(in: rect)
    NSGraphicsContext.restoreGraphicsState()
    borderColor.setStroke()
    path.lineWidth = 1
    path.stroke()
}

let block = heights.reduce(0, +)
var y = (size + block) / 2
for (i, line) in lines.enumerated() {
    y -= heights[i]
    NSAttributedString(string: line, attributes: attrs(i))
        .draw(in: NSRect(x: coverW, y: y, width: textW + 2, height: heights[i]))
}
NSGraphicsContext.restoreGraphicsState()

let png = rep.representation(using: .png, properties: [:])!
try! png.write(to: URL(fileURLWithPath: args[2]))
'''


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def fetch_page() -> str:
    # La page est encodée en Windows-1252
    return http_get(URL).decode("cp1252", errors="replace")


def parse_playing(page: str) -> dict | None:
    """Extrait le morceau actuellement diffusé depuis la page SAM."""
    # 1. Localiser la section "Currently Playing"
    anchor = page.find("Currently Playing")
    if anchor == -1:
        return None

    # 2. Première ligne <tr bgcolor="#dadada"> après l'ancre = morceau en cours
    tr_start = page.find('<tr bgcolor="#dadada">', anchor)
    if tr_start == -1:
        return None
    tr_end = page.find("</tr>", tr_start)
    row = page[tr_start:tr_end]

    # 3. Jaquette
    img_match = re.search(r'src="(pictures/[^"]+)"', row)
    cover_url = (
        f"https://cinemix.us/SAM/{img_match.group(1).replace(' ', '%20')}"
        if img_match
        else None
    )

    # 4. Tous les <small> du bloc : [titre, album]
    smalls = [html.unescape(s).strip() for s in re.findall(r"<small>([^<]+)</small>", row)]
    track = smalls[0] if smalls else "Inconnu"
    album = smalls[1] if len(smalls) > 1 else ""

    # 5. Durée
    dur_match = re.search(r"<strong>([^<]+)</strong>", row)
    duration = dur_match.group(1).strip() if dur_match else ""

    # 6. Section "NEXT" (juste après la ligne) : seulement des noms d'albums
    after_row = page[tr_end : tr_end + 2000]
    next_match = re.search(r"NEXT:.*?<b>\s*([^<]+?)\s*</b>", after_row, re.DOTALL)
    upcoming = (
        re.sub(r"\s+", " ", html.unescape(next_match.group(1))).strip()
        if next_match
        else ""
    )

    # 7. Artiste / titre (split sur " - ")
    artist, title = track.split(" - ", 1) if " - " in track else ("", track)

    return {
        "track": track,
        "artist": artist,
        "title": title,
        "album": album,
        "duration": duration,
        "cover_url": cover_url,
        "upcoming": upcoming,
    }


def fetch_next() -> dict | None:
    """Prochain morceau (titre, artiste, album), lu dans la liste « Coming up » de la radio."""
    try:
        page = http_get(COMING_URL).decode("utf-8", errors="replace")
        section = page.split("BEGIN:COMING UP", 1)[1].split("END:COMING UP", 1)[0]
        # <a ... title="Artiste - Titre"> Album <br /> Artiste </a> : le premier = prochain morceau
        m = re.search(r'<a [^>]*title="([^"]+)"[^>]*>\s*([^<]*?)\s*<br\s*/?>', section)
        if not m:
            return None
        track = html.unescape(m.group(1)).strip()
        artist, title = track.split(" - ", 1) if " - " in track else ("", track)
        return {"title": title, "artist": artist, "album": html.unescape(m.group(2)).strip()}
    except Exception:  # noqa: BLE001 - facultatif : on retombe sur l'album de la page principale
        return None


def truncate(s: str, n: int = 55) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def load_platform() -> str:
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            key = f.read().strip()
    except OSError:
        return DEFAULT_PLATFORM
    return key if key in PLATFORMS else DEFAULT_PLATFORM


def save_platform(key: str) -> None:
    if key not in PLATFORMS:
        return
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(key)


@functools.lru_cache(maxsize=None)
def is_dark_mode() -> bool:
    try:
        out = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.stdout.strip() == "Dark"


def fetch_cover_path(url: str) -> str | None:
    """Jaquette redimensionnée (via `sips`), mise en cache par URL."""
    cache = os.path.join(
        tempfile.gettempdir(),
        f"cinemix-cover-{COVER_SIZE}-{hashlib.md5(url.encode()).hexdigest()}.png",
    )
    try:
        if not os.path.exists(cache):
            src = cache + ".src"
            with open(src, "wb") as f:
                f.write(http_get(url))
            subprocess.run(
                ["sips", "-s", "format", "png", "-Z", str(COVER_SIZE), src, "--out", cache],
                capture_output=True, timeout=10, check=True,
            )
            os.remove(src)
        return cache
    except Exception:  # noqa: BLE001 - la jaquette est facultative
        return None


def file_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def png_points(path: str, scale: int = 2) -> tuple[int, int]:
    """Taille en points d'un PNG dessiné à l'échelle Retina (lue dans l'en-tête IHDR)."""
    with open(path, "rb") as f:
        header = f.read(24)
    w, h = struct.unpack(">II", header[16:24])
    return w // scale, h // scale


def ensure_card_tool() -> bool:
    """Compile (en tâche de fond) l'outil Swift qui dessine les images, si besoin."""
    src = CARD_BIN + ".swift"
    try:
        with open(src, encoding="utf-8") as f:
            up_to_date = f.read() == CARD_SWIFT
    except OSError:
        up_to_date = False
    if up_to_date:
        if os.path.exists(CARD_BIN):
            return True
        if time.time() - os.path.getmtime(src) < 300:
            return False  # compilation déjà en cours
    elif os.path.exists(CARD_BIN):
        os.remove(CARD_BIN)  # source modifiée : l'ancien binaire est périmé
    os.makedirs(os.path.dirname(CARD_BIN), exist_ok=True)
    with open(src, "w", encoding="utf-8") as f:
        f.write(CARD_SWIFT)
    subprocess.Popen(
        ["swiftc", "-O", src, "-o", CARD_BIN],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    return False


def draw(prefix: str, tool_args: list[str | None]) -> tuple[str, int, int] | None:
    """Fait dessiner une image par l'outil Swift (mise en cache) : (PNG en base64, largeur, hauteur).

    `None` dans `tool_args` marque la place du fichier de sortie. Renvoie `None` si l'outil
    n'est pas prêt ou échoue : l'appelant utilise alors un affichage de secours.
    """
    if not ensure_card_tool():
        return None
    key = hashlib.md5(repr((CARD_SWIFT, tool_args)).encode()).hexdigest()
    out = os.path.join(tempfile.gettempdir(), f"cinemix-{prefix}-{key}.png")
    try:
        if not os.path.exists(out):
            subprocess.run(
                [CARD_BIN, *[out if a is None else a for a in tool_args]],
                capture_output=True, timeout=10, check=True,
            )
        w, h = png_points(out)
        return file_b64(out), w, h
    except Exception:  # noqa: BLE001
        return None


def title_icon() -> str:
    """Paramètres SwiftBar de l'icône « radio » de la barre de menus.

    `sfsize` n'a pas d'effet dans la barre de menus : on dessine le symbole à la taille
    voulue. Secours, tant que l'outil n'est pas prêt : `sfimage`.
    """
    pad = str(round(TITLE_ICON_RAISE * 4))
    img = draw("icon", ["--symbol", "radio", str(TITLE_ICON_PT), None, pad])
    return f"templateImage={img[0]} width={img[1]} height={img[2]}" if img else "sfimage=radio"


def menu_icon(name: str) -> str:
    """Paramètres SwiftBar d'une icône de menu : symbole centré dans un cadre de taille fixe.

    Les SF Symbols n'ont pas tous la même largeur, ce qui décale les textes ; avec un cadre
    commun, ils s'alignent comme dans les menus macOS. Secours : `sfimage`.
    """
    img = draw("menuicon", ["--icon", name, str(MENU_ICON_PT), None, *map(str, MENU_ICON_BOX)])
    return f"templateImage={img[0]} width={img[1]} height={img[2]}" if img else f"sfimage={name}"


_menu_lines: list[str] = []


def emit(line: str) -> None:
    """Ajoute une ligne au menu en cours de construction (voir `build_menu`)."""
    _menu_lines.append(line)


def info_line(text: str, size: int | None = None, image: str | None = None) -> None:
    """Ligne d'information non cliquable (`text` peut avoir plusieurs lignes).

    Sans `href`, `bash` ni `color`, SwiftBar laisse la ligne désactivée (pas de survol),
    mais le système la grise trop : on la colore donc avec une séquence ANSI, qui n'active
    pas l'élément. `image` s'affiche à gauche du bloc.
    """
    color = INFO_COLOR_DARK if is_dark_mode() else INFO_COLOR_LIGHT
    lines = [f"\x1b[38;5;{color}m{t.replace('|', '¦')}\x1b[0m" for t in text.split("\n")]
    params = "ansi=true"
    if size:
        params += f" size={size}"
    if image:
        params += f" image={image} width={COVER_DISPLAY} height={COVER_DISPLAY}"
    emit("\\n".join(lines) + f" | {params}")


def track_lines(title: str, artist: str, album: str) -> list[str]:
    """Titre, « Par : artiste » et « Album : album » (les champs vides sont omis)."""
    lines = [title]
    if artist:
        lines.append(f"Par : {artist}")
    if album:
        lines.append(f"Album : {album}")
    return lines


def emit_current(info: dict) -> None:
    """Morceau en cours : jaquette arrondie à gauche, textes à droite."""
    lines = track_lines(info["title"], info["artist"], info["album"])
    if info["duration"]:
        lines.append(f"Durée : {info['duration']}")
    cover = fetch_cover_path(info["cover_url"]) if info["cover_url"] else None
    card = draw("card", [cover or "-", None, "1" if is_dark_mode() else "0", *lines])
    if card:
        emit(f"| image={card[0]} width={card[1]} height={card[2]}")
    else:
        # Outil de dessin pas encore prêt : affichage texte + jaquette
        info_line("\n".join(lines), image=file_b64(cover) if cover else None)


def emit_next(info: dict) -> None:
    """Prochain morceau ; à défaut, le prochain album annoncé par la page principale."""
    nxt = fetch_next()
    if nxt:
        lines = track_lines(nxt["title"], nxt["artist"], nxt["album"])
    elif info["upcoming"]:
        # La page principale liste des albums séparés par des virgules : on garde le premier
        first_album = re.split(r",\s+", info["upcoming"])[0]
        lines = [f"Album : {first_album}"]
    else:
        return
    emit("---")
    info_line("À SUIVRE", size=HEADER_SIZE)
    info_line("\n".join(textwrap.fill(line, UPCOMING_WIDTH) for line in lines))


def emit_actions(info: dict, platform: dict) -> None:
    emit("---")
    emit(f"Ouvrir Cinemix.radio | href=https://www.cinemix.radio/ {menu_icon('popcorn')}")
    if platform["listen"]:
        emit(f"Écouter dans {platform['name']} | href={platform['listen']} {menu_icon('music.note')}")
    q = urllib.parse.quote(info["track"])
    emit(
        f"Chercher sur {platform['name']} | "
        f"href={platform['search'].format(q=q)} {menu_icon('magnifyingglass')}"
    )
    emit(f"Rafraîchir le plugin | refresh=true {menu_icon('arrow.trianglehead.2.clockwise.rotate.90')}")


def emit_platform_menu(selected: str) -> None:
    """Sous-menu de choix de la plateforme d'écoute (réglage mémorisé)."""
    emit("---")
    emit(f"Plateforme d'écoute | {menu_icon('gearshape')}")
    for key, p in PLATFORMS.items():
        check = " checked=true" if key == selected else ""
        emit(
            f"--{p['name']} | bash=\"{SCRIPT}\" param1=--set-platform param2={key} "
            f"terminal=false refresh=true{check}"
        )


def render(info: dict) -> None:
    emit(f"{truncate(info['track'], 55).replace('|', '¦')} | {title_icon()}")  # barre de menus
    emit("---")
    emit_current(info)
    emit_next(info)
    selected = load_platform()
    emit_actions(info, PLATFORMS[selected])
    emit_platform_menu(selected)


def render_error(msg: str) -> None:
    emit(f"Cinemix ⚠️ | {title_icon()}")
    emit("---")
    emit(f"Erreur : {msg} | color=red")
    emit("Réessayer | refresh=true")


def build_menu() -> tuple[str, str]:
    """(titre de la barre de menus, corps du menu) pour le morceau en cours."""
    _menu_lines.clear()
    try:
        info = parse_playing(fetch_page())
        if info:
            render(info)
        else:
            render_error("morceau introuvable dans la page")
    except Exception as e:  # noqa: BLE001
        _menu_lines.clear()
        render_error(str(e))
    title, *body = _menu_lines
    return title, "\n".join(body) + "\n"


def prune_cache() -> None:
    """Supprime les images temporaires du plugin qui datent de plus d'un jour."""
    limit = time.time() - CACHE_MAX_AGE
    try:
        for name in os.listdir(tempfile.gettempdir()):
            if name.startswith("cinemix-") and name.endswith((".png", ".src")):
                path = os.path.join(tempfile.gettempdir(), name)
                if os.path.getmtime(path) < limit:
                    os.remove(path)
    except OSError:
        pass


def main() -> None:
    prune_cache()
    title, body = build_menu()
    print(title)
    print(body, end="")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--set-platform":
        save_platform(sys.argv[2])
    else:
        main()
