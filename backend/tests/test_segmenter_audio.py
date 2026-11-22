import numpy as np
import pytest

from app.services import audio_service, segmenter


def P(text, **kw):
    return segmenter.parse_text(text, **kw)


def test_sentences_and_pauses():
    s = P("Xin chào các bạn. Hôm nay trời đẹp! Bạn khỏe không?")
    assert [x.text for x in s] == ["Xin chào các bạn.", "Hôm nay trời đẹp!", "Bạn khỏe không?"]
    assert s[0].pause_after == 450 and s[1].pause_after == 450
    assert s[-1].pause_after == 0                      # không nghỉ thừa ở cuối


def test_ellipsis_is_long_pause():
    s = P("Chờ chút... rồi đi.")
    assert s[0].text == "Chờ chút..." and s[0].pause_after == 800


def test_newline_pause_and_custom():
    s = P("Dòng một.\nDòng hai.", pauses={"newline": 1200})
    assert s[0].pause_after == 1200


def test_pause_tag_not_in_text():
    s = P("Xin chào [pause=500] các bạn.")
    assert [x.text for x in s] == ["Xin chào", "các bạn."]
    assert s[0].pause_after == 500 and s[0].explicit_after
    assert all("pause" not in x.text.lower() and "[" not in x.text for x in s)


def test_pause_tag_at_start_and_own_line():
    s = P("[pause=300]Mở đầu.\n[pause=900]\nTiếp theo.")
    assert s[0].pause_before == 300
    assert s[0].pause_after == 900 and s[1].text == "Tiếp theo."


def test_decimal_not_split():
    s = P("Giá là 3.5 triệu đồng.")
    assert len(s) == 1


def test_split_commas_option():
    off = P("Một, hai, ba.")
    on = P("Một, hai, ba.", split_commas=True)
    assert len(off) == 1 and len(on) == 3
    assert on[0].pause_after == 250 and on[1].pause_after == 250


def test_long_sentence_is_chunked():
    long = " ".join(["từ"] * 200) + "."
    s = P(long, max_chars=100)
    assert len(s) > 1 and all(len(x.text) <= 100 for x in s)


def test_punctuation_only_skipped():
    assert P("...  !!!") == []


def test_merge_inserts_real_silence(tmp_path):
    sr = 48000
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    tone = (0.5 * np.sin(np.linspace(0, 440 * 2 * np.pi, sr // 2))).astype(np.float32)  # 0.5s
    audio_service.write_wav(a, tone, sr)
    audio_service.write_wav(b, tone, sr)
    out, osr = audio_service.merge_with_pauses([(a, 0, 500), (b, 250, 0)])
    assert osr == sr
    expected = len(tone) * 2 + int(sr * 0.75)
    assert abs(len(out) - expected) <= 2
    gap = out[len(tone) + 10: len(tone) + int(sr * 0.75) - 10]
    assert np.all(np.abs(gap) < 1e-4)                  # khoảng lặng thật, toàn mẫu 0


@pytest.mark.parametrize("fmt", ["wav", "mp3"])
def test_streaming_merge_matches_in_memory(tmp_path, fmt):
    if fmt == "mp3" and not audio_service.ffmpeg_path():
        pytest.skip("không có ffmpeg")
    import soundfile as sf
    sr = 48000
    items = []
    for i in range(5):
        p = tmp_path / f"{i}.wav"
        audio_service.write_wav(p, (0.4 * np.sin(np.linspace(0, 300 * (i + 1), sr // 2))).astype(np.float32), sr)
        items.append((p, 200 if i == 0 else 0, 300))
    seen = []
    dur = audio_service.merge_to_file(items, tmp_path / f"out.{fmt}", fmt, progress=lambda d, t: seen.append((d, t)))
    ref, _ = audio_service.merge_with_pauses(items)
    assert abs(dur - len(ref) / sr) < 1e-6
    assert seen[-1] == (5, 5)
    got = sf.info(str(tmp_path / f"out.{fmt}")).duration
    assert abs(got - len(ref) / sr) < (0.1 if fmt == "mp3" else 0.001)
    assert not list(tmp_path.glob("*.part"))


def test_streaming_merge_failure_leaves_no_partial(tmp_path):
    p = tmp_path / "a.wav"
    audio_service.write_wav(p, np.zeros(4800, dtype=np.float32), 48000)
    with pytest.raises(Exception):
        audio_service.merge_to_file([(p, 0, 0), (tmp_path / "missing.wav", 0, 0)], tmp_path / "o.wav", "wav")
    assert not (tmp_path / "o.wav").exists() and not list(tmp_path.glob("*.part"))


def test_speed_changes_duration(tmp_path):
    if not audio_service.ffmpeg_path():
        pytest.skip("không có ffmpeg")
    sr = 48000
    src, dst = tmp_path / "s.wav", tmp_path / "d.wav"
    audio_service.write_wav(src, (0.3 * np.random.randn(sr * 2)).astype(np.float32), sr)
    dur = audio_service.apply_speed(src, dst, 1.25)
    assert abs(dur - 2 / 1.25) < 0.05


def test_mp3_export(tmp_path):
    if not audio_service.ffmpeg_path():
        pytest.skip("không có ffmpeg")
    sr = 48000
    dst = tmp_path / "o.mp3"
    audio_service.save_as((0.3 * np.random.randn(sr)).astype(np.float32), sr, dst, "mp3")
    assert dst.exists() and dst.stat().st_size > 1000
