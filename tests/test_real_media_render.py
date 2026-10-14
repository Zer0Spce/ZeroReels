from zeroreels.v071_render import _normalize_final_graph_sar, _real_media_filter


def test_real_media_filter_preserves_full_source_frame_and_normalizes_sar():
    value = _real_media_filter(1080, 1920, 180, True)
    assert "split=2[bg][fg]" in value
    assert "force_original_aspect_ratio=increase" in value
    assert "force_original_aspect_ratio=decrease" in value
    assert "overlay=(W-w)/2:(H-h)/2" in value
    assert "boxblur" in value
    assert "zoompan" in value
    assert "setsar=1" in value


def test_static_real_media_filter_still_uses_archival_fit_and_square_pixels():
    value = _real_media_filter(1080, 1920, 180, False)
    assert "force_original_aspect_ratio=decrease" in value
    assert "overlay=(W-w)/2:(H-h)/2" in value
    assert "zoompan" not in value
    assert "setsar=1" in value


def test_final_combine_graph_forces_square_pixels_on_every_input():
    source = (
        "[0:v]format=yuv420p,setpts=PTS-STARTPTS[v0];"
        "[1:v]format=yuv420p,setpts=PTS-STARTPTS[v1];"
        "[v0][v1]concat=n=2:v=1:a=0[edit1]"
    )
    fixed = _normalize_final_graph_sar(source)
    assert "[0:v]format=yuv420p,setsar=1,setpts=PTS-STARTPTS[v0]" in fixed
    assert "[1:v]format=yuv420p,setsar=1,setpts=PTS-STARTPTS[v1]" in fixed
    assert fixed.count("setsar=1") == 2
