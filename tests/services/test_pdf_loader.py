from app.services.parser.pdf_loader import _decode_pdf_string


def test_decode_pdf_string_ignores_non_ascii_digit_escape():
    assert _decode_pdf_string("(\\¹)") == "¹"


def test_decode_pdf_string_ignores_invalid_octal_escape():
    assert _decode_pdf_string("(\\9)") == "9"


def test_decode_pdf_string_decodes_valid_octal_escape():
    assert _decode_pdf_string("(\\123)") == "S"
