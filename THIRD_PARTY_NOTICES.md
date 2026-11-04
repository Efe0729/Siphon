# Third-party notices

Siphon is licensed under the Apache License 2.0 (see [`LICENSE`](./LICENSE)).

The application depends on these open-source packages, each under its own licence:

| Package | Licence |
| --- | --- |
| [requests](https://github.com/psf/requests) | Apache-2.0 |
| [urllib3](https://github.com/urllib3/urllib3) | MIT |
| [certifi](https://github.com/certifi/python-certifi) | MPL-2.0 |
| [PySocks](https://github.com/Anorov/PySocks) | BSD-3-Clause |
| [beautifulsoup4](https://www.crummy.com/software/BeautifulSoup/) | MIT |
| [m3u8](https://github.com/globocom/m3u8) | MIT |
| [pycryptodome](https://github.com/Legrandin/pycryptodome) | BSD-2-Clause / Public domain |
| [cloudscraper](https://github.com/VeNoMouS/cloudscraper) | MIT |
| [curl_cffi](https://github.com/lexiforest/curl_cffi) | MIT |
| [Pillow](https://github.com/python-pillow/Pillow) | MIT-CMU |
| [customtkinter](https://github.com/TomSchimansky/CustomTkinter) | MIT |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | BSD-2-Clause |

## Bundled with the Windows build

`Siphon.exe` is packaged with [PyInstaller](https://pyinstaller.org/)
(GPL-2.0 with a special exception that allows bundling any program) and
carries the Python runtime (PSF-2.0) with Tcl/Tk (Tcl/Tk licence).

The `imageio-ffmpeg` package supplies a static [FFmpeg](https://ffmpeg.org/)
binary, used to join and convert video. That build is licensed under the
GPL/LGPL of the FFmpeg project; its source is available from the FFmpeg site
and from the imageio-ffmpeg project.

## Used when developing

[pytest](https://github.com/pytest-dev/pytest) (MIT) and
[pytest-timeout](https://github.com/pytest-dev/pytest-timeout) (MIT) run the
tests; they are not shipped.

## Not bundled

Uploads are performed by [rclone](https://rclone.org/) (MIT), which the user
installs separately; Siphon only drives it.
