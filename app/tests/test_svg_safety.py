"""check_static_svg guards the gallery, which serves model-produced SVG markup back to browsers."""
from __future__ import annotations

import pytest

from image_gen import check_static_svg

SAFE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#1A73E8"/></svg>'


def test_static_svg_accepted():
    check_static_svg(SAFE)


def test_xml_prolog_and_internal_fragment_refs_accepted():
    svg = (
        '<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg">'
        '<defs><linearGradient id="g"/></defs><rect fill="url(#g)"/><use href="#g"/></svg>'
    )
    check_static_svg(svg)


@pytest.mark.parametrize(
    "markup",
    [
        '<svg><script>alert(1)</script></svg>',
        '<svg><SCRIPT src="x.js"></SCRIPT></svg>',
        '<svg onload="alert(1)"><rect/></svg>',
        '<svg><rect onclick = "x()"/></svg>',
        '<svg><foreignObject><div>hi</div></foreignObject></svg>',
        '<svg><image href="https://evil.example/x.png"/></svg>',
        '<svg><a href="javascript:alert(1)"><rect/></a></svg>',
        "<svg><image src='http://evil.example/x.png'/></svg>",
        '<svg><image href="data:text/html;base64,PHNjcmlwdD4="/></svg>',
    ],
)
def test_active_or_external_content_rejected(markup):
    with pytest.raises(ValueError, match="scripts, event handlers or external references"):
        check_static_svg(markup)


@pytest.mark.parametrize("not_svg", ["", "<html><body>hi</body></html>", "plain text", '{"svg": false}'])
def test_non_svg_rejected(not_svg):
    with pytest.raises(ValueError, match="not SVG markup"):
        check_static_svg(not_svg)
