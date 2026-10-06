"""Small HTML helpers shared by official metadata adapters."""

from lxml import etree, html

from twmarket.errors import SchemaError


def document(content: bytes, *, encoding: str = "utf-8") -> html.HtmlElement:
    try:
        return html.fromstring(  # pyright: ignore[reportUnknownMemberType]
            content.decode(encoding)
        )
    except (UnicodeError, ValueError, etree.ParserError) as exc:
        raise SchemaError("Invalid official HTML document") from exc


def cells(row: html.HtmlElement) -> list[str]:
    return [" ".join(cell.text_content().split()) for cell in row.xpath("./th|./td")]
