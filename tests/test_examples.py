from pathlib import Path

import pytest

from funnelbot.loader import load_funnel

EXAMPLES = sorted((Path(__file__).resolve().parent.parent / "examples").glob("*.yaml"))


def test_examples_exist():
    assert len(EXAMPLES) >= 3


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_is_valid(path):
    funnel = load_funnel(path, {})
    assert funnel.steps and funnel.products


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_digital_goods_always_offer_stars(path):
    funnel = load_funnel(path, {})
    assert funnel.payments.stars is not None
    for pid in funnel.products:
        assert "stars" in funnel.methods_for(pid)
