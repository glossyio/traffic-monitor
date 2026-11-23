"""Made-up JPEG bytes for tests: the start-of-image marker, a JFIF header, a frame header that carries a size, and the
end marker. No picture is in them."""


def jpeg(width: int, height: int) -> bytes:
    jfif = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    frame = b"\xff\xc0\x00\x0b\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x01\x01\x11\x00"
    return b"\xff\xd8" + jfif + frame + b"\xff\xd9"
