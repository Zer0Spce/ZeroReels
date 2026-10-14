from zeroreels.v071_render import _real_media_filter


def test_real_media_filter_preserves_full_source_frame():
    value = _real_media_filter(1080, 1920, 180, True)
    assert "split=2[bg][fg]" in value
    assert "force_original_aspect_ratio=increase" in value
    assert "force_original_aspect_ratio=decrease" in value
    assert "overlay=(W-w)/2:(H-h)/2" in value
    assert "boxblur" in value
    assert "zoompan" in value


def test_static_real_media_filter_still_uses_archival_fit():
    value = _real_media_filter(1080, 1920, 180, False)
    assert "force_original_aspect_ratio=decrease" in value
    assert "overlay=(W-w)/2:(H-h)/2" in value
    assert "zoompan" not in value
