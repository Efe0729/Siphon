import inspect
import re
import types
from pathlib import Path

from siphon.apps import browse as gui_modern
from siphon.i18n import locales
from siphon.ui import theme as ui_theme


def _rgb(hex_color):
    return tuple(int(hex_color[index:index + 2], 16) / 255
                 for index in (1, 3, 5))


def _luminance(hex_color):
    channels = []
    for value in _rgb(hex_color):
        channels.append(value / 12.92 if value <= 0.04045
                        else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(a, b):
    light, dark = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_responsive_breakpoints_prioritize_readability():
    assert ui_theme.browse_columns_for_width(979) == 2
    assert ui_theme.browse_columns_for_width(1080) == 3
    assert ui_theme.browse_columns_for_width(1499) == 3
    assert ui_theme.browse_columns_for_width(1500) == 4
    assert ui_theme.category_columns_for_width(1119) == 2
    assert ui_theme.category_columns_for_width(1120) == 3


def test_primary_text_contrast_is_accessible_in_both_themes():
    for index in (0, 1):
        assert _contrast(ui_theme.TEXT_PRI[index], ui_theme.BG_DARK[index]) >= 7
        assert _contrast(ui_theme.TEXT_PRI[index], ui_theme.BG_CARD[index]) >= 7


def test_windows_version_resources_match_app_version():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / '.github' / 'workflows' / 'windows-build.yml').read_text(
        encoding='utf-8')
    assert '$expected = "1.0.0.0"' in workflow
    packaging = root / 'packaging' / 'windows'
    generator = (packaging / 'gen_version.py').read_text(
        encoding='utf-8')
    assert 'VERSION = (1, 0, 0, 0)' in generator
    for name in ('Siphon.version',):
        resource = (packaging / name).read_text(encoding='utf-8')
        assert 'filevers=(1, 0, 0, 0)' in resource
        assert "StringStruct('FileVersion', '1.0.0.0')" in resource
        assert "StringStruct('ProductName', 'Siphon')" in resource
    for name in ('Siphon.spec',):
        spec = (packaging / name).read_text(encoding='utf-8')
        assert "'curl_cffi'" in spec


def test_windows_distribution_is_hardened_and_verifiable():
    root = Path(__file__).resolve().parents[1]
    browse_spec = (
        root / 'packaging' / 'windows' / 'Siphon.spec'
    ).read_text(encoding='utf-8')
    workflow = (
        root / '.github' / 'workflows' / 'windows-build.yml'
    ).read_text(encoding='utf-8')

    assert 'upx=False' in browse_spec
    assert 'upx=True' not in browse_spec
    assert "'siphon.core.updater'" in browse_spec

    # The official PyInstaller guidance recommends rebuilding its bootloader
    # from source to reduce false positives tied to widely shared bootloaders.
    assert 'PYINSTALLER_COMPILE_BOOTLOADER' in workflow
    assert '--no-binary=PyInstaller' in workflow
    assert 'pip uninstall --yes PyInstaller' in workflow
    assert 'pip cache remove PyInstaller' in workflow
    # Keep the previously qualified PyInstaller release for this hotfix;
    # only the bootloader provenance changes.
    assert 'pyinstaller==6.13.0' in workflow.lower()

    # Checksums and provenance help users verify origin.  They do not replace
    # Authenticode and must remain separate from malware-detection claims.
    assert 'Siphon_SHA256SUMS.txt' in workflow
    assert 'actions/attest@v4' in workflow
    assert 'attestations: write' in workflow
    assert 'Compatibility alias is not byte-identical' not in workflow
    # Every path the workflow watches must be a file that exists, and the
    # documents shipped beside the exe must be among them.
    root = Path(__file__).resolve().parents[1]
    watched = re.findall(r'^      - "([^"]+)"$', workflow, re.M)
    for path in watched:
        assert list(root.glob(path)), f'workflow watches missing {path}'
    for documentation in ('README.md', 'THIRD_PARTY_NOTICES.md',
                          'WINDOWS_SECURITY.md'):
        assert f'"{documentation}"' in workflow

    # A version tag must publish the exe as a Release, which is where the
    # updater looks for it.
    assert 'tags: ["v*"]' in workflow
    assert 'contents: write' in workflow
    assert 'gh release create' in workflow




def test_modern_defers_initial_workers_until_mainloop():
    init_source = inspect.getsource(gui_modern.ModernApp.__init__)
    assert 'self.after_idle(self._start_initial_background_tasks)' in init_source
    assert 'self._start_update_check(manual=False)' not in init_source

    app = gui_modern.ModernApp.__new__(gui_modern.ModernApp)
    calls = []
    app._is_closing = False
    app._start_update_check = lambda **kwargs: calls.append(('update', kwargs))
    app._load_categories = lambda: calls.append(('categories', {}))

    app._start_initial_background_tasks()

    # Personal fork: no check for official updates at startup.
    assert calls == [('categories', {})]


def test_modern_concurrency_is_editable_persisted_and_clamped(monkeypatch):
    assert gui_modern.MAX_CONCURRENT == 32
    init_source = inspect.getsource(gui_modern.ModernApp.__init__)
    settings_source = inspect.getsource(
        gui_modern.ModernApp._build_settings_tab)
    footer_source = inspect.getsource(
        gui_modern.ModernApp._refresh_downloads)
    assert 'config.get_download_concurrency()' in init_source
    assert 'self._conc_entry = ctk.CTkEntry(' in settings_source
    assert "self._conc_entry.bind('<Return>'" in settings_source

    class _Var:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    app = gui_modern.ModernApp.__new__(gui_modern.ModernApp)
    app._conc_var = _Var('99')
    app._dlmgr = types.SimpleNamespace(max_concurrent=2)
    saved = []

    def _save(value):
        saved.append(value)
        return max(1, min(int(value), 32))

    monkeypatch.setattr(gui_modern.config, 'set_download_concurrency', _save)
    app._on_conc_change()

    assert saved == [99]
    assert app._dlmgr.max_concurrent == 32
    assert app._conc_var.get() == '32'

    app._conc_var.set('invalid')
    app._on_conc_change()
    assert saved == [99]
    assert app._conc_var.get() == '32'


def test_site_thumbnail_context_reuses_cf_override_only_on_trusted_zone(
        monkeypatch):
    override = {'cookie': 'test-clearance', 'ua': 'Exact Browser UA'}
    monkeypatch.setattr(
        gui_modern.config, 'get_cf_override',
        lambda host: dict(override) if host == 'example.com' else None)

    request_headers, cookies = gui_modern._thumbnail_request_context(
        'https://img.example.com/thumbs/example.jpg', 'site')

    assert request_headers['User-Agent'] == 'Exact Browser UA'
    assert request_headers['Referer'] == 'https://example.com/'
    assert cookies.get_dict(domain='.example.com') == {
        'cf_clearance': 'test-clearance',
    }
    trusted = gui_modern.requests.Request(
        'GET', 'https://img.example.com/thumb.jpg', cookies=cookies).prepare()
    disguised = gui_modern.requests.Request(
        'GET', 'https://img.example.com.evil.example/thumb.jpg',
        cookies=cookies).prepare()
    insecure = gui_modern.requests.Request(
        'GET', 'http://img.example.com/thumb.jpg', cookies=cookies).prepare()
    assert trusted.headers['Cookie'] == 'cf_clearance=test-clearance'
    assert 'Cookie' not in disguised.headers
    assert 'Cookie' not in insecure.headers

    external_headers, external_cookies = gui_modern._thumbnail_request_context(
        'https://images.example.test/thumb.jpg', 'site')
    assert external_headers['User-Agent'] == gui_modern.headers['User-Agent']
    assert 'Referer' not in external_headers
    assert external_cookies is None

    for url, site_key in (
            ('https://img.example.com.evil.example/thumb.jpg', 'site'),
            ('http://img.example.com/thumb.jpg', 'site'),
            ('https://img.example.com/thumb.jpg', 'site')):
        untrusted_headers, untrusted_cookies = (
            gui_modern._thumbnail_request_context(url, site_key))
        assert untrusted_headers == gui_modern.headers
        assert untrusted_cookies is None


def test_failed_thumbnail_replaces_loading_placeholder(monkeypatch):
    configured = []

    class _ImmediateExecutor:
        def submit(self, callback):
            callback()

    class _Label:
        def winfo_exists(self):
            return True

        def configure(self, **kwargs):
            configured.append(kwargs)

    app = gui_modern.ModernApp.__new__(gui_modern.ModernApp)
    app._is_closing = False
    app._grid_gen = 7
    app._build_gen = 9
    app._thumb_executor = _ImmediateExecutor()
    app._ui = lambda callback, gen=None: callback()
    monkeypatch.setattr(gui_modern, '_fetch_thumbnail', lambda *_args: None)

    app._load_thumb_async(
        'https://img.example.com/missing.jpg', _Label(), 7, 9, 'site')

    assert configured[-1]['text'] == gui_modern.T('no_thumbnail')


def test_stale_site_thumbnail_override_retries_without_credentials(
        monkeypatch):
    calls = []

    class _Response:
        def __init__(self, status_code, content=b''):
            self.status_code = status_code
            self.content = content

        def close(self):
            pass

    class _Session:
        def get(self, url, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return _Response(403)
            return _Response(200, b'image-bytes')

    class _Image:
        size = (300, 169)

        def convert(self, _mode):
            return self

        def thumbnail(self, _size, _resample):
            pass

    monkeypatch.setattr(gui_modern, '_get_thumb_session', lambda: _Session())
    monkeypatch.setattr(gui_modern.Image, 'open', lambda _stream: _Image())
    monkeypatch.setattr(gui_modern, '_thumb_cache', {})
    monkeypatch.setattr(
        gui_modern.config, 'get_cf_override',
        lambda _host: {'cookie': 'stale', 'ua': 'Stale UA'})

    result = gui_modern._fetch_thumbnail(
        'https://img.example.com/thumb.jpg', 'site')

    assert result is not None
    assert len(calls) == 2
    assert calls[0]['headers']['User-Agent'] == 'Stale UA'
    assert calls[0]['cookies'].get_dict(domain='.example.com') == {
        'cf_clearance': 'stale',
    }
    assert calls[1]['headers'] == gui_modern.headers
    assert 'cookies' not in calls[1]



def test_readme_describes_this_app_and_credits_the_project_it_forks():
    root = Path(__file__).resolve().parents[1]
    readme = (root / 'README.md').read_text(encoding='utf-8')

    assert 'Siphon' in readme
    # the install steps must name files that exist
    root_files = {entry.name for entry in root.iterdir()}
    for named in re.findall(r'\*\*([A-Za-z0-9_.-]+\.bat)\*\*', readme):
        assert named in root_files, f'README tells the reader to run {named}'
    assert 'Siphon.bat' in readme
    # features that were removed must not be promised
    for gone in ('subtitle', 'Watcher', 'reazonspeech', 'UAV Browser', 'Kur.bat'):
        assert gone not in readme, gone
    # the fork it comes from is named, as the licence requires
    assert 'UAV-Downloader' in readme and 'Apache-2.0' in readme


def test_windows_spec_runs_the_way_pyinstaller_runs_it():
    """PyInstaller exec()s the spec with its own globals — and no __file__.

    A name that only exists in a normal module (``__file__`` is the usual
    slip) blows the build up minutes in, so the spec is executed here the
    same way, with the PyInstaller helpers stubbed out.
    """
    import sys
    import types

    root = Path(__file__).resolve().parents[1]
    spec_path = root / 'packaging' / 'windows' / 'Siphon.spec'

    hooks = types.ModuleType('PyInstaller.utils.hooks')
    hooks.collect_all = lambda name: ([], [], [])
    hooks.copy_metadata = lambda name: []
    utils = types.ModuleType('PyInstaller.utils')
    utils.hooks = hooks
    pyinstaller = types.ModuleType('PyInstaller')
    pyinstaller.utils = utils
    stubs = {'PyInstaller': pyinstaller, 'PyInstaller.utils': utils,
             'PyInstaller.utils.hooks': hooks}
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        namespace = {
            '__name__': '__main__',
            'Analysis': lambda *a, **k: types.SimpleNamespace(
                pure=[], scripts=[], binaries=[], datas=[]),
            'PYZ': lambda *a, **k: object(),
            'EXE': lambda *a, **k: object(),
            'COLLECT': lambda *a, **k: object(),
            'SPEC': str(spec_path),
            'SPECPATH': str(spec_path.parent),
            'DISTPATH': str(root / 'dist'),
            'WORKPATH': str(root / 'build'),
        }
        exec(compile(spec_path.read_text(encoding='utf-8'),
                     str(spec_path), 'exec'), namespace)
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
