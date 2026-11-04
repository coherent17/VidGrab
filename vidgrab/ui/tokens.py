"""The few sizes the whole interface is built from, so pages agree with each other.

Spacing steps (px) for gaps, margins and padding; the type scale for the stylesheet; the
margins every full page uses. New layouts should take their numbers from here, and
`tests/unit/test_tokens.py` keeps the stylesheet's font sizes on the scale."""
from __future__ import annotations

SPACE = (4, 8, 12, 16, 24)  # tight, related items, group, section, page

# font sizes (px)
TYPE_CAPTION = 11  # small caps labels, status bar
TYPE_SMALL = 12  # hints, secondary lines
TYPE_BODY = 13  # normal text and buttons
TYPE_LARGE = 15  # emphasised buttons
TYPE_TITLE = 17  # a card or panel heading
TYPE_DISPLAY = 22  # the page title and the brand
TYPE_SCALE = (TYPE_CAPTION, TYPE_SMALL, TYPE_BODY, TYPE_LARGE, TYPE_TITLE, TYPE_DISPLAY)

PAGE_MARGINS = (24, 12, 24, 12)  # left, top, right, bottom of a full page
CARD_RADIUS = 14
