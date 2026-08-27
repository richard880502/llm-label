import io

from openpyxl import Workbook

from backend.annotation.models import InputMapping, LabelFieldMapping
from backend.routers.imports import (
    _canonical_metadata,
    _context_text,
    _infer_mapping,
    _read_xlsx,
)


def test_infer_mapping_detects_message_and_ticket_id():
    mapping = _infer_mapping([
        "ticket_no",
        "message",
        "source",
        "priority",
        "product_category",
    ])
    assert mapping.text_field == "message"
    assert mapping.id_field == "ticket_no"
    assert mapping.metadata_fields == ["source", "priority", "product_category"]


def test_generic_metadata_keeps_source_id_labels_and_context():
    row = {
        "ticket_no": "T-1001",
        "message": "五天了還沒有出貨",
        "source": "web",
        "priority": "high",
        "category": "shipping|refund",
        "product_category": "服飾",
    }
    mapping = InputMapping(
        text_field="message",
        id_field="ticket_no",
        labels=LabelFieldMapping(field="category", format="delimiter", delimiter="|"),
        metadata_fields=["source", "priority"],
        context_fields=["product_category"],
    )
    metadata = _canonical_metadata(row, mapping)
    assert metadata["source"] == "web"
    assert metadata["priority"] == "high"
    assert metadata["_source_id"] == "T-1001"
    assert metadata["_source_labels"] == ["shipping", "refund"]
    assert metadata["_context"] == {"product_category": "服飾"}
    assert _context_text(row, mapping) == "product_category: 服飾"


def test_xlsx_with_non_legacy_columns_is_parsed():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["ticket_no", "message", "source", "priority"])
    sheet.append(["T-1001", "訂單五天還沒出貨", "web", "high"])
    sheet.append(["T-1002", "收到商品破損", "email", "medium"])
    stream = io.BytesIO()
    workbook.save(stream)

    rows = _read_xlsx(stream.getvalue())
    assert rows == [
        {"ticket_no": "T-1001", "message": "訂單五天還沒出貨", "source": "web", "priority": "high"},
        {"ticket_no": "T-1002", "message": "收到商品破損", "source": "email", "priority": "medium"},
    ]
