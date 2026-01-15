from utils import sanitize_filename, validate_tiktok_url


def test_sanitize_filename_removes_hash_and_weird_chars():
    assert sanitize_filename("#monkey#funny?.mp4").startswith("monkeyfunny")
    assert "#" not in sanitize_filename("a#b")


def test_validate_tiktok_url_basic():
    assert validate_tiktok_url("https://www.tiktok.com/@user/video/1234567890")
    assert not validate_tiktok_url("https://example.com/video/123")

