from __future__ import annotations

import opic


def test_package_exposes_version():
    assert isinstance(opic.__version__, str)
    assert opic.__version__ != ""
