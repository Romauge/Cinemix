# Cinemix Now Playing

A [SwiftBar](https://swiftbar.app) plugin that shows what is playing on [Cinemix](https://www.cinemix.radio/), the film-soundtrack radio, right in the macOS menu bar.

[Version française](README.fr.md)

<!-- Add a screenshot here, for example: ![Cinemix Now Playing](docs/screenshot.png) -->

> Unofficial plugin, not affiliated with Cinemix. It reads the public page
> `https://cinemix.us/SAM/playing.php`, whose structure can change without notice.
> Provided as is.

## Features

- Current track in the menu bar, with a radio icon.
- Menu with the album cover (rounded corners), title, artist, album and duration.
- Next album coming up.
- Shortcuts: open Cinemix.radio, listen to the station in Apple Music, search the current track on your streaming platform.
- Platform setting: Apple Music, Spotify, Deezer, Qobuz or YouTube Music (menu "Plateforme d'écoute").
- Light and dark mode.
- Demo mode to take screenshots with any track you like.

## Requirements

- macOS and SwiftBar.
- Python 3.7 or later (the one shipped with Xcode / Command Line Tools works). No package to install.
- Optional: `swiftc` (Xcode or Command Line Tools) for the rounded cover and the menu bar icon. Without it, the plugin falls back to a simpler display.

## Installation

1. Install SwiftBar: `brew install --cask swiftbar`, or download it from [swiftbar.app](https://swiftbar.app).
2. Launch SwiftBar and choose a plugin folder.
3. Copy `cinemix.30s.py` into that folder and make it executable:

   ```bash
   chmod +x cinemix.30s.py
   ```

4. In SwiftBar, click "Refresh All". The `30s` in the file name means the plugin refreshes every 30 seconds.

## Listening platform

Open the "Plateforme d'écoute" submenu and pick your platform. The choice is remembered.

| Platform | "Listen" | "Search" |
|---|---|---|
| Apple Music | Opens the Cinemix station in Music | Searches "Artist - Title" |
| Spotify, Deezer, Qobuz, YouTube Music | Not shown (they have no Cinemix station) | Searches "Artist - Title" |

## Demo mode (screenshots)

Show a track of your choice instead of the live one. The cover is found automatically through the iTunes Search API.

```bash
python3 cinemix.30s.py --demo "John Williams" "Theme from Jurassic Park" \
  --album "Jurassic Park (Original Motion Picture Soundtrack)" --duration 3:08
```

Other options: `--cover <url or image path>`, `--next "Next album"`, `--hours <n>` (default 2: demo mode stops by itself).

Back to the live track:

```bash
python3 cinemix.30s.py --demo-off
```

## Customizing

The constants at the top of `cinemix.30s.py` control the look: cover size, text colors, width of the "next" line, size and position of the menu bar icon, list of platforms.

## Files created

- `~/.config/cinemix/`: chosen platform, demo state, and a small Swift helper (`cinemix-card`) compiled on first run. It draws the rounded cover and the menu bar icon. Its source is the `CARD_SWIFT` constant in the plugin.
- Your temporary folder: small cached images (`cinemix-*.png`), deleted after 24 hours.

To remove everything, delete the plugin and `~/.config/cinemix/`.

## Troubleshooting

- **"Permission denied"**: run `chmod +x` on the plugin again. Replacing the file loses the executable bit.
- **"You have not agreed to the Xcode license agreements"**: after an Xcode update, run `sudo xcodebuild -license accept` in a terminal.
- **Simple display instead of the rounded cover**: the Swift helper is still compiling (a few seconds) or `swiftc` is missing. Refresh again after a minute.
- **"morceau introuvable dans la page"**: the Cinemix page changed or is unreachable. Check [cinemix.us/SAM/playing.php](https://cinemix.us/SAM/playing.php).

## License

[MIT](LICENSE)
