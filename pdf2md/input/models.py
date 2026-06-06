from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TextBlock:
    text: str
    font_size: float
    is_bold: bool
    page_num: int
    y_pos: float


@dataclass
class TableBlock:
    rows: list[list[str | None]]
    page_num: int


@dataclass
class ImageBlock:
    data: bytes
    ext: str
    width: int
    height: int
    page_num: int
    img_index: int


@dataclass
class Section:
    heading: str
    level: int  # 1=H1, 2=H2, 3=H3
    page_num: int = 0
    text_blocks: list[TextBlock] = field(default_factory=list)
    tables: list[TableBlock] = field(default_factory=list)
    images: list[ImageBlock] = field(default_factory=list)
    children: list["Section"] = field(default_factory=list)


@dataclass
class Document:
    title: str
    path: Path
    page_count: int = 0
    split_depth: int = 3
    root_sections: list[Section] = field(default_factory=list)
    preamble: list[TextBlock] = field(default_factory=list)
    preamble_tables: list[TableBlock] = field(default_factory=list)
    preamble_images: list[ImageBlock] = field(default_factory=list)
