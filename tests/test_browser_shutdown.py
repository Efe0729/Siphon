"""Frozen startup/close race: workers must never call Tk from their thread."""
import queue
import threading
from types import SimpleNamespace
import pytest
from siphon.apps import browse


def test_worker_dispatch_uses_queue_without_tk_calls():
    callbacks = queue.SimpleQueue()
    errors, executed = [], []
    def after(*args):
        raise RuntimeError('worker must not enter Tk')
    app = SimpleNamespace(_is_closing=False, _build_gen=1,
                          _ui_callbacks=callbacks, after=after)
    def worker():
        try:
            browse.ModernApp._ui(app, lambda: executed.append(1), gen=1)
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(1)
    assert not errors
    assert not executed
    assert not callbacks.empty()


def test_mainloop_close_during_customtkinter_setup_is_normal(monkeypatch):
    class App:
        _is_closing = False
        def __init__(self, **kwargs):
            pass
        def mainloop(self):
            self._is_closing = True
            raise browse.tk.TclError('application has been destroyed')
    monkeypatch.setattr(browse, 'ModernApp', App)
    browse.gui_modern_main()


def test_mainloop_real_tcl_failure_is_not_hidden(monkeypatch):
    class App:
        _is_closing = False
        def __init__(self, **kwargs):
            pass
        def mainloop(self):
            raise browse.tk.TclError('unexpected failure')
    monkeypatch.setattr(browse, 'ModernApp', App)
    with pytest.raises(browse.tk.TclError):
        browse.gui_modern_main()


def test_close_during_widget_construction_is_deferred():
    app = SimpleNamespace(_startup_complete=False, _is_closing=False,
                          _close_requested=False)
    browse.ModernApp._on_close(app)
    assert app._is_closing and app._close_requested


def test_drain_discards_stale_and_closing_callbacks():
    called = []
    callbacks = queue.SimpleQueue()
    callbacks.put((0, lambda: called.append('stale')))
    callbacks.put((1, lambda: called.append('current')))
    app = SimpleNamespace(_is_closing=False, _build_gen=1,
                          _ui_callbacks=callbacks, after=lambda *a: None,
                          _drain_ui_callbacks=lambda: None)
    browse.ModernApp._drain_ui_callbacks(app)
    assert called == ['current']
    app._is_closing = True
    callbacks.put((1, lambda: called.append('closed')))
    browse.ModernApp._drain_ui_callbacks(app)
    assert called == ['current']


def test_close_prompts_when_active_transfers_exist(monkeypatch):
    destroyed = []
    prompts = []

    def _make_app(answer=False, installing=False):
        return SimpleNamespace(
            _startup_complete=True,
            _is_closing=False,
            _close_requested=False,
            _update_installing=installing,
            _dlmgr=SimpleNamespace(active_count=1, _lock=threading.Lock(), _items={}, save_csv=lambda *a: None, cancel_all=lambda **k: None),
            _upmgr=SimpleNamespace(jobs=lambda: [SimpleNamespace(state='uploading')], close=lambda: None),
            _thumb_executor=SimpleNamespace(shutdown=lambda **k: None),
            _save_resume_list=lambda: None,
            _has_active_transfers=lambda: browse.ModernApp._has_active_transfers(SimpleNamespace(
                _dlmgr=SimpleNamespace(active_count=1),
                _upmgr=SimpleNamespace(jobs=lambda: [SimpleNamespace(state='uploading')]),
            )),
            destroy=lambda: destroyed.append(True),
        )

    monkeypatch.setattr(browse.messagebox, 'askyesno',
                        lambda title, body, **k: prompts.append((title, body)) or False)
    app = _make_app(answer=False)
    browse.ModernApp._on_close(app)
    assert len(prompts) == 1
    assert not app._is_closing
    assert not destroyed

    monkeypatch.setattr(browse.messagebox, 'askyesno',
                        lambda title, body, **k: prompts.append((title, body)) or True)
    browse.ModernApp._on_close(app)
    assert len(prompts) == 2
    assert app._is_closing and destroyed == [True]

    app_upd = _make_app(installing=True)
    browse.ModernApp._on_close(app_upd)
    assert len(prompts) == 2
    assert app_upd._is_closing and len(destroyed) == 2
