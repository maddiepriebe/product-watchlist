from pathlib import Path

from extract.meta import page_meta

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_farmrio_uses_jsonld_name_and_upgrades_og_image() -> None:
    m = page_meta(
        fixture("fixture-farmrio-com-products-rustic-flowers-winter-white-sleeveless-.html"),
        "https://farmrio.com/products/x",
    )
    assert m.title == "Multicolor Rustic Flowers Sleeveless Ruched Maxi Dress"
    assert m.image_url is not None and m.image_url.startswith("https://farmrio.com/cdn/")


def test_tracksmith_name_is_trimmed() -> None:
    m = page_meta(
        fixture("fixture-www-tracksmith-com-products-w-meridian-speed-shorts-sku-WB71.html"),
        "https://www.tracksmith.com/products/x",
    )
    assert m.title == "Meridian Speed Shorts"


def test_vuori_falls_back_to_jsonld_image() -> None:
    m = page_meta(
        fixture("fixture-vuoriclothing-com-products-womens-daily-piped-bra-black-refS.html"),
        "https://vuoriclothing.com/products/x",
    )
    assert m.title == "Daily Piped Bra"
    assert m.image_url is not None and m.image_url.startswith("https://cdn.shopify.com/")


def test_og_fallbacks_and_relative_image() -> None:
    html = (
        '<html><head><title>Fallback | Shop</title>'
        '<meta property="og:title" content="Linen Shirt &amp; Tie">'
        '<meta property="og:image" content="/img/shirt.jpg"></head></html>'
    )
    m = page_meta(html, "https://shop.test/p/1")
    assert m.title == "Linen Shirt & Tie"
    assert m.image_url == "https://shop.test/img/shirt.jpg"


def test_title_tag_last_resort_and_no_image() -> None:
    m = page_meta("<html><head><title> Just  a title </title></head></html>", "https://x.test/")
    assert m.title == "Just a title"
    assert m.image_url is None


def test_graph_and_image_object() -> None:
    html = (
        '<script type="application/ld+json">{"@graph": [{"@type": ["Product"], '
        '"name": "Graph Dress", "image": {"url": "//cdn.test/a.jpg"}}]}</script>'
    )
    m = page_meta(html, "https://x.test/p")
    assert m.title == "Graph Dress"
    assert m.image_url == "https://cdn.test/a.jpg"


def test_empty_page() -> None:
    assert page_meta("", "https://x.test/") == page_meta("<html></html>", "https://x.test/")
