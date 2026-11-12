"""Tests del parche de whisper para MPS (float64 → float32).

Se prueba con módulos simulados para no depender del whisper instalado ni
alterar el estado global del proceso.
"""

import pytest

from subtitles import _patch_mps_float32


class FakeTensor:
    """Simula un tensor de torch con los métodos usados por el parche."""

    def __init__(self, dtype="float64", device="mps"):
        self.dtype = dtype
        self.device = device
        self.is_cuda = False

    def to(self, device=None, dtype=None):
        return FakeTensor(dtype=dtype or self.dtype, device=device or self.device)

    def double(self):
        # MPS no soporta float64: este es exactamente el punto del fallo.
        if self.device == "mps":
            raise TypeError(
                "Cannot convert a MPS Tensor to float64 dtype as the MPS "
                "framework doesn't support float64. Please use float32 instead."
            )
        return FakeTensor("float64", self.device)


class FakeTorch:
    float32 = "float32"


def _make_modules():
    """Crea un whisper simulado con audio.mel_filters y timing.dtw."""

    class FakeAudio:
        @staticmethod
        def mel_filters(device, n_mels):
            # Como el original: devuelve float64.
            return FakeTensor("float64", device)

    class FakeTiming:
        @staticmethod
        def dtw(x):
            # Como el original: convierte a float64 (falla en MPS).
            return x.double()

    class FakeWhisper:
        audio = FakeAudio()
        timing = FakeTiming()

    return FakeWhisper()


def test_patch_is_idempotent():
    """Aplicar el parche dos veces no debe duplicar el envoltorio."""
    whisper = _make_modules()
    _patch_mps_float32(whisper, FakeTorch)
    first = whisper.audio.mel_filters
    _patch_mps_float32(whisper, FakeTorch)
    assert whisper.audio.mel_filters is first


def test_mel_filters_returns_float32():
    """Los filtros mel deben devolverse en float32."""
    whisper = _make_modules()
    _patch_mps_float32(whisper, FakeTorch)

    result = whisper.audio.mel_filters("mps", 80)
    assert result.dtype == "float32"


def test_dtw_moves_tensor_to_cpu_before_double():
    """El tensor debe llegar a CPU: `.double()` falla en MPS."""
    whisper = _make_modules()
    _patch_mps_float32(whisper, FakeTorch)

    # Si el parche no moviera el tensor a CPU, esto reventaría.
    result = whisper.timing.dtw(FakeTensor("float32", "mps"))
    assert result is not None


def test_dtw_keeps_cuda_path():
    """En CUDA se conserva el comportamiento original."""
    whisper = _make_modules()
    _patch_mps_float32(whisper, FakeTorch)

    class CudaTensor(FakeTensor):
        def __init__(self):
            super().__init__("float32", "cuda")
            self.is_cuda = True

    result = whisper.timing.dtw(CudaTensor())
    assert result is not None


def test_patch_handles_missing_submodules():
    """Si whisper no tiene audio/timing, no debe romperse."""

    class FakeWhisper:
        pass

    _patch_mps_float32(FakeWhisper(), FakeTorch)


def test_real_whisper_dtw_works_on_mps():
    """Con whisper y torch reales, el DTW parcheado funciona en MPS."""
    torch = pytest.importorskip("torch")
    whisper = pytest.importorskip("whisper")

    if not getattr(torch.backends, "mps", None) or not torch.backends.mps.is_available():
        pytest.skip("MPS no disponible en esta máquina")

    _patch_mps_float32(whisper, torch)

    x = torch.ones(4, 8, device="mps")
    # La versión original fallaría aquí con el error de float64.
    result = whisper.timing.dtw(x)
    assert result is not None
