"""The complete v1 venue code table."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Venue:
    code: int
    name: str


VENUES: tuple[Venue, ...] = (
    Venue(1, "桐生"),
    Venue(2, "戸田"),
    Venue(3, "江戸川"),
    Venue(4, "平和島"),
    Venue(5, "多摩川"),
    Venue(6, "浜名湖"),
    Venue(7, "蒲郡"),
    Venue(8, "常滑"),
    Venue(9, "津"),
    Venue(10, "三国"),
    Venue(11, "びわこ"),
    Venue(12, "住之江"),
    Venue(13, "尼崎"),
    Venue(14, "鳴門"),
    Venue(15, "丸亀"),
    Venue(16, "児島"),
    Venue(17, "宮島"),
    Venue(18, "徳山"),
    Venue(19, "下関"),
    Venue(20, "若松"),
    Venue(21, "芦屋"),
    Venue(22, "福岡"),
    Venue(23, "唐津"),
    Venue(24, "大村"),
)

VENUE_BY_CODE = {venue.code: venue for venue in VENUES}
