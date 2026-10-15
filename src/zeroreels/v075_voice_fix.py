from __future__ import annotations

from pathlib import Path
import subprocess

from PySide6.QtWidgets import QLabel

from . import services, ui, v070_ui, v070_voice
from .config import find_executable
from .win_subprocess import run_hidden


CHATTERBOX_RUNNER = r'''from pathlib import Path
import argparse
import inspect
import soundfile as sf
from chatterbox.tts_turbo import ChatterboxTurboTTS

p=argparse.ArgumentParser()
p.add_argument('--text-file')
p.add_argument('--ref')
p.add_argument('--out')
p.add_argument('--device', default='cpu')
a=p.parse_args()
text=Path(a.text_file).read_text(encoding='utf-8')

factory=ChatterboxTurboTTS.from_pretrained
try:
    params=inspect.signature(factory).parameters
except (TypeError, ValueError):
    params={}
kwargs={'device': a.device}
mode='Turbo compatibility'
if 'nano' in params:
    kwargs['nano']=True
    mode='Nano'
model=factory(**kwargs)
wav=model.generate(text, audio_prompt_path=a.ref)
array=wav.detach().cpu().numpy()
while getattr(array, 'ndim', 1) > 1 and array.shape[0] == 1:
    array=array[0]
sf.write(a.out, array, model.sr, subtype='PCM_16')
print('ZEROREELS_CHATTERBOX_MODE=' + mode)
'''


F5_RUNNER = r'''from pathlib import Path
import argparse
import soundfile as sf
import torch
import torchaudio

p=argparse.ArgumentParser()
p.add_argument('--text-file')
p.add_argument('--ref')
p.add_argument('--ref-text', default='')
p.add_argument('--out')
p.add_argument('--ffmpeg', default='')
a=p.parse_args()
text=Path(a.text_file).read_text(encoding='utf-8')
ref_text=(a.ref_text or '').strip()
if not ref_text:
    raise SystemExit('F5-TTS requires the reference transcript in ZeroReels Settings. Automatic transcription is disabled on Windows to avoid TorchCodec DLL failures.')

# TorchAudio 2.9 routes audio decoding through TorchCodec. TorchCodec currently requires a
# full-shared FFmpeg install on Windows and can fail even when ZeroReels itself has a working
# static FFmpeg executable. F5 only needs a tensor + sample rate here, so use SoundFile for WAV
# loading and leave TorchAudio transforms/resampling intact.
def _soundfile_load(uri, frame_offset=0, num_frames=-1, normalize=True, channels_first=True, format=None, buffer_size=4096, backend=None):
    data, sample_rate = sf.read(str(uri), dtype='float32', always_2d=True)
    start=max(0, int(frame_offset or 0))
    end=None if num_frames is None or int(num_frames) < 0 else start + int(num_frames)
    data=data[start:end]
    tensor=torch.from_numpy(data.copy())
    if channels_first:
        tensor=tensor.transpose(0, 1).contiguous()
    return tensor, int(sample_rate)

def _soundfile_save(uri, src, sample_rate, channels_first=True, format=None, encoding=None, bits_per_sample=None, buffer_size=4096, backend=None, compression=None):
    tensor=src.detach().cpu()
    if channels_first and tensor.ndim == 2:
        tensor=tensor.transpose(0, 1)
    sf.write(str(uri), tensor.numpy(), int(sample_rate), subtype='PCM_16')

torchaudio.load=_soundfile_load
torchaudio.save=_soundfile_save

if a.ffmpeg:
    try:
        from pydub import AudioSegment
        AudioSegment.converter=a.ffmpeg
        AudioSegment.ffmpeg=a.ffmpeg
    except Exception:
        pass

from f5_tts.api import F5TTS
model=F5TTS()
model.infer(ref_file=a.ref, ref_text=ref_text, gen_text=text, file_wave=a.out)
print('ZEROREELS_F5_MODE=SoundFile compatibility')
'''


F5_SMOKE = r'''import soundfile as sf
import torch
import torchaudio

def _load(uri, frame_offset=0, num_frames=-1, normalize=True, channels_first=True, format=None, buffer_size=4096, backend=None):
    data, sr = sf.read(str(uri), dtype='float32', always_2d=True)
    t = torch.from_numpy(data.copy())
    if channels_first:
        t = t.transpose(0, 1).contiguous()
    return t, int(sr)

torchaudio.load = _load
from f5_tts.api import F5TTS
print('F5_IMPORT_OK')
'''


def _ffmpeg_path(settings) -> str:
    ffmpeg = find_executable(getattr(settings, 'ffmpeg_exe', ''), 'ffmpeg')
    if ffmpeg:
        return str(ffmpeg)
    try:
        import imageio_ffmpeg
        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return ''


def _failure_summary(engine: str, detail: str) -> str:
    text = (detail or '').lower()
    if 'torchcodec' in text or 'libtorchcodec' in text:
        return 'TorchCodec/FFmpeg DLL compatibility problem'
    if 'unexpected keyword argument' in text and 'nano' in text:
        return 'installed Chatterbox API is older than Nano support'
    if 'reference transcript' in text:
        return 'reference transcript is missing'
    lines = [line.strip() for line in (detail or '').splitlines() if line.strip()]
    return (lines[-1] if lines else f'{engine} returned an unknown error')[:220]


def _fallback_to_kokoro(service, project, out_dir: Path, progress, detail: str) -> Path:
    reason = _failure_summary(service.engine, detail)
    v070_voice._progress(
        progress,
        22,
        f'{service.engine} unavailable • {reason} • falling back to Kokoro Directed',
    )
    try:
        target = v070_voice.KokoroDirectedVoiceService(service.settings, service.delivery).generate(
            project, out_dir, progress
        )
    except Exception as fallback_exc:
        raise RuntimeError(
            f'{service.engine} failed ({reason}), and Kokoro Directed fallback also failed: {fallback_exc}'
        ) from fallback_exc
    project.voice_engine_used = f'Kokoro Directed (fallback from {service.engine})'
    return target


def compatible_external_generate(self, project, out_dir: Path, progress=None) -> Path:
    python_exe = (
        Path(self.settings.chatterbox_python).expanduser()
        if self.engine == 'Chatterbox Nano'
        else Path(self.settings.f5_python).expanduser()
    )
    runner_source = CHATTERBOX_RUNNER if self.engine == 'Chatterbox Nano' else F5_RUNNER

    if not python_exe.exists():
        return _fallback_to_kokoro(
            self,
            project,
            out_dir,
            progress,
            f'{self.engine} isolated Python environment was not found',
        )

    ref = Path(self.settings.natural_voice_ref).expanduser() if self.settings.natural_voice_ref else None
    if not ref or not ref.exists():
        return _fallback_to_kokoro(
            self,
            project,
            out_dir,
            progress,
            f'{self.engine} reference WAV is missing',
        )

    ref_text = (getattr(self.settings, 'natural_voice_ref_text', '') or '').strip()
    if self.engine == 'F5-TTS Studio' and not ref_text:
        return _fallback_to_kokoro(
            self,
            project,
            out_dir,
            progress,
            'F5-TTS reference transcript is missing',
        )

    v070_voice._progress(progress, 20, f'Natural Voice • {self.engine} • {self.delivery}')
    text_path = out_dir / 'voice_directed.txt'
    text_path.write_text(v070_voice.directed_script(project, self.delivery), encoding='utf-8')
    runner = out_dir / '_natural_voice_runner.py'
    runner.write_text(runner_source, encoding='utf-8')
    target = out_dir / 'narration.wav'

    command = [
        str(python_exe), str(runner), '--text-file', str(text_path), '--ref', str(ref), '--out', str(target)
    ]
    if self.engine == 'Chatterbox Nano':
        command += ['--device', 'cpu']
    else:
        command += ['--ref-text', ref_text]
        ffmpeg = _ffmpeg_path(self.settings)
        if ffmpeg:
            command += ['--ffmpeg', ffmpeg]

    try:
        proc = run_hidden(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1800,
        )
    except Exception as exc:
        try:
            runner.unlink(missing_ok=True)
        except OSError:
            pass
        return _fallback_to_kokoro(self, project, out_dir, progress, str(exc))

    try:
        runner.unlink(missing_ok=True)
    except OSError:
        pass

    if proc.returncode != 0 or not target.exists() or target.stat().st_size < 1000:
        detail = (proc.stderr or proc.stdout or 'unknown error')[-4000:]
        return _fallback_to_kokoro(self, project, out_dir, progress, detail)

    duration = v070_voice._wav_duration(target)
    v070_voice.apply_scene_timing(project, duration, self.delivery)
    project.actual_seconds = round(duration, 2)
    engine_used = self.engine
    if self.engine == 'Chatterbox Nano' and 'ZEROREELS_CHATTERBOX_MODE=Turbo compatibility' in (proc.stdout or ''):
        engine_used = 'Chatterbox Turbo (compatibility mode)'
        v070_voice._progress(progress, 28, 'Chatterbox package has no Nano flag • Turbo compatibility mode used')
    project.voice_engine_used = engine_used
    project.voice_delivery = self.delivery
    v070_voice._progress(progress, 29, f'Natural Voice ready • {duration:.1f}s • {engine_used}')
    return target


def install_optional_voice_engine_compat(settings, engine: str, progress=None) -> None:
    """Install the optional engine and verify ZeroReels' compatibility path before reporting ready."""
    v070_voice.install_optional_voice_engine(settings, engine, progress)
    python_exe = (
        Path(settings.chatterbox_python).expanduser()
        if engine == 'Chatterbox Nano'
        else Path(settings.f5_python).expanduser()
    )
    if not python_exe.exists():
        raise RuntimeError(f'{engine} installer finished but its Python environment is missing.')

    if engine == 'Chatterbox Nano':
        smoke = (
            "import inspect; from chatterbox.tts_turbo import ChatterboxTurboTTS; "
            "p=inspect.signature(ChatterboxTurboTTS.from_pretrained).parameters; "
            "print('CHATTERBOX_NANO=' + ('1' if 'nano' in p else '0'))"
        )
    else:
        # SoundFile is used by our Windows runner to bypass TorchCodec for reference-WAV loading.
        run_hidden(
            [str(python_exe), '-m', 'pip', 'install', '--upgrade', 'soundfile'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=600,
        )
        smoke = F5_SMOKE

    result = run_hidden(
        [str(python_exe), '-c', smoke],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or 'unknown smoke-test failure')[-2200:]
        raise RuntimeError(f'{engine} installed, but its compatibility check failed:\n{detail}')

    if progress:
        if engine == 'Chatterbox Nano' and 'CHATTERBOX_NANO=0' in (result.stdout or ''):
            progress(100, 'Chatterbox ready • installed package uses Turbo compatibility mode')
        elif engine == 'F5-TTS Studio':
            progress(100, 'F5-TTS ready • Windows SoundFile compatibility path verified')
        else:
            progress(100, f'{engine} compatibility verified')


def install() -> None:
    # Replace the fragile runners and make optional engines non-fatal to a whole video.
    v070_voice.RUNNER_CHATTERBOX = CHATTERBOX_RUNNER
    v070_voice.RUNNER_F5 = F5_RUNNER
    v070_voice.ExternalNaturalVoiceService.generate = compatible_external_generate

    # v070_ui imported this symbol directly, so patch its module-global binding as well as the
    # source module. Existing setup button lambdas resolve this name at click time.
    v070_ui.install_optional_voice_engine = install_optional_voice_engine_compat

    original_sidebar = ui.MainWindow._sidebar

    def sidebar(self):
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith('v0.'):
                label.setText('v0.7.5 VOICE')
                label.setMaximumWidth(126)
                break
        return frame

    ui.MainWindow._sidebar = sidebar
