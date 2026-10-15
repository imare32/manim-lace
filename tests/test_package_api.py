"""The package namespace contract, independent of whether Manim is installed."""

import importlib.util
import subprocess
import sys

import pytest

import manim_lace

HAS_MANIM = importlib.util.find_spec("manim") is not None


def test_every_advertised_name_is_reachable():
    assert manim_lace.__all__
    for name in manim_lace.__all__:
        assert getattr(manim_lace, name) is not None


def test_lace_is_advertised_only_when_manim_is_available():
    # The literal in __init__ lists Lace; the runtime value follows the dependency.
    assert ("Lace" in manim_lace.__all__) is HAS_MANIM
    assert ("Lace" in dir(manim_lace)) is HAS_MANIM


def test_lace_resolves_lazily_from_the_module_namespace():
    if HAS_MANIM:
        from manim_lace import Lace

        assert manim_lace.Lace is Lace
    else:
        with pytest.raises(ImportError, match="manim-lace\\[manim\\]"):
            manim_lace.Lace  # noqa: B018


def test_unknown_attribute_raises_attribute_error():
    with pytest.raises(AttributeError, match="not_a_real_symbol"):
        manim_lace.not_a_real_symbol  # noqa: B018


def test_importing_the_package_does_not_import_manim():
    code = "import sys, manim_lace; sys.exit(1 if 'manim' in sys.modules else 0)"
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


_NO_MANIM_BODY = (
    "import manim_lace\n"
    "assert 'Lace' not in manim_lace.__all__, manim_lace.__all__\n"
    "assert 'Lace' not in dir(manim_lace)\n"
    "assert manim_lace.LaceEngine is not None\n"
    "try:\n"
    "    manim_lace.Lace\n"
    "except ImportError as exc:\n"
    "    assert 'manim-lace[manim]' in str(exc), exc\n"
    "else:\n"
    "    raise SystemExit('expected ImportError for Lace without manim')\n"
)

# ``sys.modules[name] = None`` is the documented way to forbid an import.
_BLOCKED_IMPORT = "import sys\nsys.modules['manim'] = None\n" + _NO_MANIM_BODY
# A hostile finder that raises instead of answering, as a half-initialised
# ``sys.modules`` entry or a broken importer hook can.
_RAISING_FINDER = (
    "import sys\n"
    "class Boom:\n"
    "    def find_spec(self, name, path=None, target=None):\n"
    "        if name == 'manim':\n"
    "            raise ValueError('blocked')\n"
    "        return None\n"
    "sys.meta_path.insert(0, Boom())\n"
) + _NO_MANIM_BODY


@pytest.mark.parametrize("script", [_BLOCKED_IMPORT, _RAISING_FINDER], ids=["blocked", "raising"])
def test_the_package_survives_a_missing_or_unfindable_manim(script):
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
