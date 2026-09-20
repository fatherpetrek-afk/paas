"""Loaded via PYTHONPATH so plt.show / cv2.imshow / PIL / pygame write into output/."""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

_OUT = Path("output") / "_display"
_n = 0


def _next() -> Path:
    global _n
    _OUT.mkdir(parents=True, exist_ok=True)
    _n += 1
    return _OUT / f"{_n:04d}.png"


def _named(label: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(label or "window")).strip("._") or "window"
    _OUT.mkdir(parents=True, exist_ok=True)
    return _OUT / f"{safe}.png"


def _patch_matplotlib() -> None:
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except Exception:
        return

    def show(*_a, **_k):
        for num in list(plt.get_fignums()):
            fig = plt.figure(num)
            try:
                fig.savefig(_named(f"fig-{num}"), bbox_inches="tight")
            except Exception:
                pass
        plt.close("all")

    plt.show = show  # type: ignore[method-assign]


def _patch_cv2() -> None:
    try:
        import cv2
    except Exception:
        return

    def imshow(win, img):
        try:
            cv2.imwrite(str(_named(f"cv2-{win}")), img)
        except Exception:
            pass

    cv2.imshow = imshow  # type: ignore[method-assign]
    cv2.waitKey = lambda *_a, **_k: 1  # type: ignore[assignment]
    cv2.destroyAllWindows = lambda *_a, **_k: None  # type: ignore[assignment]


def _patch_pil() -> None:
    try:
        from PIL import Image
    except Exception:
        return

    def show(self, *_a, **_k):
        try:
            self.save(_next())
        except Exception:
            pass

    Image.Image.show = show  # type: ignore[method-assign]


def _patch_pygame() -> None:
    try:
        import pygame
    except Exception:
        return
    orig_flip = getattr(pygame.display, "flip", None)
    orig_update = getattr(pygame.display, "update", None)
    if orig_flip is None:
        return

    def _dump() -> None:
        try:
            surf = pygame.display.get_surface()
            if surf is not None:
                pygame.image.save(surf, str(_named("pygame")))
        except Exception:
            pass

    def flip(*a, **k):
        out = orig_flip(*a, **k)
        _dump()
        return out

    def update(*a, **k):
        out = orig_update(*a, **k) if orig_update else None
        _dump()
        return out

    pygame.display.flip = flip  # type: ignore[method-assign]
    if orig_update is not None:
        pygame.display.update = update  # type: ignore[method-assign]


def _patch_web_ui() -> None:
    port = int(os.environ.get("PAAS_UI_PORT") or 0)
    prefix = str(os.environ.get("PAAS_UI_PREFIX") or "")
    if port <= 0:
        return
    os.environ.setdefault("GRADIO_SERVER_NAME", "127.0.0.1")
    os.environ.setdefault("GRADIO_SERVER_PORT", str(port))
    os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
    if prefix:
        os.environ.setdefault("GRADIO_ROOT_PATH", prefix)
        os.environ.setdefault("SCRIPT_NAME", prefix)
        os.environ.setdefault("APPLICATION_ROOT", prefix)
    _patch_flask(port, prefix)
    _patch_gradio(port, prefix)


class _PrefixMid:
    def __init__(self, app, prefix: str):
        self.app = app
        self.prefix = prefix.rstrip("/") or ""

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO") or ""
        if self.prefix and path.startswith(self.prefix):
            environ["SCRIPT_NAME"] = self.prefix
            environ["PATH_INFO"] = path[len(self.prefix) :] or "/"
        return self.app(environ, start_response)


def _patch_flask(ui_port: int, prefix: str) -> None:
    try:
        import flask
    except Exception:
        return
    orig = flask.Flask.run

    def run(self, host=None, port=None, debug=None, load_dotenv=True, **options):
        del host, port
        options.pop("host", None)
        options.pop("port", None)
        if prefix:
            self.config["APPLICATION_ROOT"] = prefix
            self.wsgi_app = _PrefixMid(self.wsgi_app, prefix)
        options.setdefault("threaded", True)
        return orig(self, "127.0.0.1", ui_port, debug=debug, load_dotenv=load_dotenv, **options)

    flask.Flask.run = run  # type: ignore[method-assign]


def _patch_gradio(port: int, prefix: str) -> None:
    try:
        import gradio as gr
    except Exception:
        return

    def wrap(orig):
        def launch(*args, **kwargs):
            kwargs["server_name"] = "127.0.0.1"
            kwargs["server_port"] = port
            kwargs["inbrowser"] = False
            kwargs["share"] = False
            if prefix:
                kwargs["root_path"] = prefix
            return orig(*args, **kwargs)

        return launch

    for cls in (getattr(gr, "Blocks", None), getattr(gr, "Interface", None)):
        if cls is not None and hasattr(cls, "launch"):
            cls.launch = wrap(cls.launch)


_patch_matplotlib()
_patch_cv2()
_patch_pil()
_patch_pygame()
_patch_web_ui()
