# Desktop icon sources

The runtime catalog contains only checked-in, transparent 256×256 PNG files.
The renderer converts every file to RGBA, trims transparent margins, and
resizes with `Image.Resampling.LANCZOS` before compositing.

## Windows shell icons

The following system icons are derived from the Windows shell icon references
published in [TobinCavanaugh/WindowsIcons](https://github.com/TobinCavanaugh/WindowsIcons).
The repository is MIT-licensed; its README identifies the underlying artwork as
Microsoft Windows shell icons.

- `this-pc.png` — shell icon 015
- `recycle-bin.png` — shell icon 031
- `network.png` — shell icon 018
- `new-folder.png` — shell icon 003
- `notepad.png` — shell icon 001
- `file-explorer.png`, `powershell.png`, `remote-desktop.png` — Windows 10 ICO
  files from [FadeMind/W-ICO](https://github.com/FadeMind/W-ICO)

## Application marks

Application marks are sourced from
[Simple Icons](https://github.com/simple-icons/simple-icons), which is
released under CC0. The checked-in PNGs retain the transparent background and
are rendered from the original vector paths.

- `google-chrome.png`
- `firefox.png`
- `teamviewer.png`
- `telegram.png`
- `zoom.png`
- `notepad-plus-plus.png`
- `vlc.png`

`microsoft-word.png` uses the MIT-licensed Windows 10 icon artwork from
[Icons8/windows-10-icons](https://github.com/icons8/windows-10-icons).