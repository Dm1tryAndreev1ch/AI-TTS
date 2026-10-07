import asyncio
import sys
import types
import pytest
from gateway.voice.tts_piper import PiperSpeaker, default_player, player_from_env


@pytest.mark.parametrize("platform,expected", [("win32", ("winsound",)), ("darwin", ("afplay",)),
                                               ("linux", ("aplay",))])
def test_default_player_per_platform(monkeypatch, platform, expected):
    monkeypatch.setattr(sys, "platform", platform)
    assert default_player() == expected
    assert player_from_env(None) == expected and player_from_env("") == expected
    assert player_from_env(" AUTO ") == expected


def test_player_from_env_custom_command(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert player_from_env("ffplay -nodisp -autoexit") == ("ffplay", "-nodisp", "-autoexit")
    monkeypatch.setattr(sys, "platform", "win32")
    assert player_from_env(r"C:\Tools\mpv.exe --no-video") == (r"C:\Tools\mpv.exe", "--no-video")


def stub_piper(monkeypatch, calls):
    class Voice:
        @staticmethod
        def load(path):
            return Voice()

        def synthesize_wav(self, text, wav_file):
            calls.append(text)
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\x00\x00" * 10)
    monkeypatch.setitem(sys.modules, "piper", types.SimpleNamespace(PiperVoice=Voice))


def test_winsound_playback_path(monkeypatch, tmp_path):
    played, synth = [], []
    stub_piper(monkeypatch, synth)
    monkeypatch.setitem(sys.modules, "winsound", types.SimpleNamespace(
        SND_FILENAME=131072, PlaySound=lambda path, flags: played.append((path, flags))))
    model = tmp_path / "v.onnx"
    model.write_bytes(b"x")
    sp = PiperSpeaker(str(model), player=("winsound",))

    async def go():
        await sp.say("привет")
        await sp.say("привет")
    asyncio.run(go())
    sp.close()
    assert synth == ["привет"] and len(played) == 2
    assert played[0][0].endswith(".wav") and played[0][1] == 131072 and played[0][0] == played[1][0]


def test_external_player_still_works_and_default_is_used(monkeypatch, tmp_path):
    synth = []
    stub_piper(monkeypatch, synth)
    model = tmp_path / "v.onnx"
    model.write_bytes(b"x")
    sp = PiperSpeaker(str(model), player=(sys.executable, "-c", "pass"))
    asyncio.run(sp.say("один"))
    sp.close()
    assert synth == ["один"]
    monkeypatch.setattr(sys, "platform", "win32")
    sp2 = PiperSpeaker(str(model))
    assert sp2._player == ("winsound",)
    sp2.close()
    with pytest.raises(FileNotFoundError):
        PiperSpeaker(str(tmp_path / "missing.onnx"))
