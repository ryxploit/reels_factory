"""
Reels Factory - Video Processor Module
========================================
Processes videos for Facebook Reels format.
- Reframes to 9:16 aspect ratio (1080x1920)
- Trims to max 55 seconds
- Adds branding overlay
- Applies Facebook-compatible encoding
- Burns subtitles

Optimized for macOS Apple Silicon.
"""

import queue
import random
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from config import config
from deps import resolve_binaries
from utils import (
    ProgressCallback,
    check_ffmpeg_subtitles_support,
    generate_unique_filename,
    get_video_info,
    setup_logger,
)

logger = setup_logger("processor", config.paths.LOGS_PATH / "processor.log")


@dataclass
class ProcessingResult:
    """Result of a video processing operation."""

    success: bool
    file_path: Path | None
    video_info: dict | None
    error_message: str | None = None
    warnings: list[str] | None = None
    thumbnail_path: Path | None = None


class VideoProcessor:
    """
    Video processor for Facebook Reels optimization.
    Handles reframing, trimming, branding, and encoding.
    """

    def __init__(self, output_dir: Path | None = None, temp_dir: Path | None = None):
        """
        Initialize the video processor.

        Args:
            output_dir: Directory for processed videos
            temp_dir: Directory for temporary files
        """
        self.output_dir = output_dir or config.paths.PROCESSED_PATH
        self.temp_dir = temp_dir or config.paths.TEMP_PATH

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.video_config = config.video
        self.branding_config = config.branding
        # Archivos temporales creados durante el render (se limpian al terminar).
        self._temp_artifacts: list[Path] = []

    def _calculate_crop_filter(
        self, input_width: int, input_height: int, target_width: int, target_height: int
    ) -> str:
        """
        Calculate FFmpeg crop filter for center crop.

        Args:
            input_width: Source video width
            input_height: Source video height
            target_width: Target width
            target_height: Target height

        Returns:
            FFmpeg filter string
        """
        target_ratio = target_width / target_height
        input_ratio = input_width / input_height

        if input_ratio > target_ratio:
            # Input is wider - crop sides
            new_width = int(input_height * target_ratio)
            crop_x = (input_width - new_width) // 2
            return f"crop={new_width}:{input_height}:{crop_x}:0"
        else:
            # Input is taller - crop top/bottom
            new_height = int(input_width / target_ratio)
            crop_y = (input_height - new_height) // 2
            return f"crop={input_width}:{new_height}:0:{crop_y}"

    def _build_video_filters(
        self,
        input_width: int,
        input_height: int,
        logo_path: Path | None = None,
    ) -> str:
        """
        Build complete FFmpeg filter chain.

        Args:
            input_width: Source video width
            input_height: Source video height
            logo_path: Optional path to logo image

        Returns:
            FFmpeg filter_complex string
        """
        target_width = self.video_config.WIDTH
        target_height = self.video_config.HEIGHT

        filters = []

        # 1. Crop to target aspect ratio (center crop)
        crop_filter = self._calculate_crop_filter(
            input_width, input_height, target_width, target_height
        )
        filters.append(crop_filter)

        # 2. Scale to exact output dimensions
        filters.append(f"scale={target_width}:{target_height}")

        # 3. Set frame rate
        filters.append(f"fps={self.video_config.FPS}")

        # 4. Apply subtle variations to avoid content fingerprint detection
        if self.video_config.ENABLE_VARIATIONS:
            # Instancia local: no se siembra el RNG global del proceso.
            rng = random.Random(int(time.time() * 1000))

            # Subtle brightness/contrast variation (imperceptible to human eye)
            brightness_var = rng.uniform(
                -self.video_config.BRIGHTNESS_VARIATION, self.video_config.BRIGHTNESS_VARIATION
            )
            contrast_var = rng.uniform(
                1 - self.video_config.CONTRAST_VARIATION, 1 + self.video_config.CONTRAST_VARIATION
            )
            saturation_var = rng.uniform(
                1 - self.video_config.SATURATION_VARIATION,
                1 + self.video_config.SATURATION_VARIATION,
            )
            filters.append(
                f"eq=brightness={brightness_var:.4f}:contrast={contrast_var:.4f}:saturation={saturation_var:.4f}"
            )

            # Add minimal noise to alter pixel fingerprint (almost invisible)
            noise_strength = rng.randint(
                self.video_config.NOISE_STRENGTH_MIN, self.video_config.NOISE_STRENGTH_MAX
            )
            filters.append(f"noise=c0s={noise_strength}:allf=t")

        # Combine base video filters
        video_filter = ",".join(filters)

        # Handle complex filter graph if we have overlays
        if logo_path and logo_path.exists():
            # Calculate logo position (bottom right corner)
            logo_x = (
                target_width
                - self.branding_config.LOGO_WIDTH
                - self.branding_config.LOGO_MARGIN_RIGHT
            )
            logo_y = (
                target_height
                - self.branding_config.LOGO_HEIGHT
                - self.branding_config.LOGO_MARGIN_BOTTOM
            )

            return (
                f"[0:v]{video_filter}[base];"
                f"[1:v]scale={self.branding_config.LOGO_WIDTH}:{self.branding_config.LOGO_HEIGHT},"
                f"format=rgba,colorchannelmixer=aa={self.branding_config.LOGO_OPACITY}[logo];"
                f"[base][logo]overlay={logo_x}:{logo_y}[out]"
            )

        return video_filter

    def _build_ffmpeg_command(
        self,
        input_path: Path,
        output_path: Path,
        input_width: int,
        input_height: int,
        duration: float,
        logo_path: Path | None = None,
        subtitle_path: Path | None = None,
    ) -> list[str]:
        """
        Build complete FFmpeg command for video processing.

        The command is constructed in stages:
        1. Input files
        2. Video filters (crop, scale, variations, subtitles, logo)
        3. Encoding settings
        4. Metadata removal

        Args:
            input_path: Source video path
            output_path: Output video path
            input_width: Source video width
            input_height: Source video height
            duration: Video duration in seconds
            logo_path: Optional logo image path
            subtitle_path: Optional subtitle file path

        Returns:
            FFmpeg command as list of arguments
        """
        max_duration = min(duration, self.video_config.MAX_DURATION_SECONDS)

        bins = resolve_binaries()
        if not bins.ffmpeg:
            raise RuntimeError("FFmpeg not found")

        cmd = [str(bins.ffmpeg), "-y"]

        # Add input files
        cmd.extend(self._add_input_files(input_path, logo_path))

        # Set duration limit
        cmd.extend(["-t", str(max_duration)])

        # Build and add video filters
        video_filter = self._build_video_filters(
            input_width,
            input_height,
            logo_path if logo_path and logo_path.exists() else None,
        )

        use_complex_filter = logo_path and logo_path.exists()
        if use_complex_filter:
            cmd.extend(["-filter_complex", video_filter, "-map", "[out]", "-map", "0:a?"])
        else:
            cmd.extend(["-vf", video_filter])

        # Add subtitle filters if needed
        self._add_subtitle_filters(cmd, subtitle_path, use_complex_filter)

        # Add encoding settings
        cmd.extend(self._add_encoding_settings())

        # Add metadata and optimization settings
        cmd.extend(self._add_metadata_settings())

        # Output file
        cmd.append(str(output_path))

        return cmd

    def _add_input_files(self, input_path: Path, logo_path: Path | None) -> list[str]:
        """
        Add input files to FFmpeg command.

        Args:
            input_path: Path to the main video file
            logo_path: Optional path to logo file

        Returns:
            List of FFmpeg arguments for inputs
        """
        cmd = ["-i", str(input_path)]
        if logo_path and logo_path.exists():
            cmd.extend(["-i", str(logo_path)])
        return cmd

    def _add_subtitle_filters(
        self, cmd: list[str], subtitle_path: Path | None, use_complex_filter: bool
    ) -> None:
        """
        Add subtitle filters to the FFmpeg command if subtitles are provided.

        Args:
            cmd: FFmpeg command list to modify
            subtitle_path: Path to subtitle file
            use_complex_filter: Whether complex filter is being used
        """
        if not subtitle_path or not subtitle_path.exists():
            return

        # Create a temporary copy with a safe filename to avoid FFmpeg escaping issues
        safe_subtitle_path = self.temp_dir / f"subs_{uuid.uuid4().hex[:8]}.ass"
        shutil.copy2(subtitle_path, safe_subtitle_path)
        # Se registra para borrarla al terminar el render.
        self._temp_artifacts.append(safe_subtitle_path)

        escaped_path = self._escape_filter_value(str(safe_subtitle_path))
        subtitle_filter = f"subtitles=filename='{escaped_path}':charenc=UTF-8"

        if use_complex_filter:
            current_filter = cmd[cmd.index("-filter_complex") + 1]
            new_filter = current_filter.replace("[out]", f"[temp];[temp]{subtitle_filter}[out]")
            cmd[cmd.index("-filter_complex") + 1] = new_filter
        else:
            current_vf = cmd[cmd.index("-vf") + 1]
            cmd[cmd.index("-vf") + 1] = f"{current_vf},{subtitle_filter}"

    def _add_encoding_settings(self) -> list[str]:
        """
        Add video and audio encoding settings.

        Returns:
            List of FFmpeg encoding arguments
        """
        cmd = []

        # Video codec settings (H.264 compatible with Facebook)
        cmd.extend(
            [
                "-c:v",
                self.video_config.VIDEO_CODEC,
                "-preset",
                self.video_config.VIDEO_PRESET,
                "-b:v",
                self.video_config.VIDEO_BITRATE,
                "-maxrate",
                self.video_config.VIDEO_MAXRATE,
                "-bufsize",
                self.video_config.VIDEO_BUFSIZE,
                "-profile:v",
                self.video_config.VIDEO_PROFILE,
                "-level",
                self.video_config.VIDEO_LEVEL,
                "-pix_fmt",
                self.video_config.PIXEL_FORMAT,
            ]
        )

        # Audio codec settings
        cmd.extend(
            [
                "-c:a",
                self.video_config.AUDIO_CODEC,
                "-b:a",
                self.video_config.AUDIO_BITRATE,
                "-ar",
                str(self.video_config.AUDIO_SAMPLE_RATE),
                "-ac",
                str(self.video_config.AUDIO_CHANNELS),
            ]
        )

        # Normalización de loudness: Facebook/TikTok esperan -14 LUFS.
        if self.video_config.ENABLE_LOUDNORM:
            cmd.extend(
                [
                    "-af",
                    (
                        f"loudnorm=I={self.video_config.LOUDNORM_I}"
                        f":TP={self.video_config.LOUDNORM_TP}"
                        f":LRA={self.video_config.LOUDNORM_LRA}"
                    ),
                ]
            )

        # Optimize for streaming/upload
        cmd.extend(["-movflags", "+faststart"])

        return cmd

    def _add_metadata_settings(self) -> list[str]:
        """
        Add metadata removal and bitexact settings to avoid platform detection.

        Returns:
            List of FFmpeg metadata arguments
        """
        return [
            # Strip all metadata from source to avoid platform detection
            "-map_metadata",
            "-1",
            # Remove chapter markers
            "-map_chapters",
            "-1",
            # Produce reproducible output without timestamps
            "-fflags",
            "+bitexact",
            # Video stream bitexact
            "-flags:v",
            "+bitexact",
            # Audio stream bitexact
            "-flags:a",
            "+bitexact",
        ]

    def _escape_filter_value(self, value: str) -> str:
        """
        Escape special characters for FFmpeg filter values.

        Args:
            value: String to escape

        Returns:
            Escaped string safe for FFmpeg filters
        """
        return (
            value.replace("\\", r"\\\\")
            .replace("'", r"\\'")
            .replace(":", r"\\:")
            .replace("#", r"\\#")
            .replace("[", r"\\[")
            .replace("]", r"\\]")
            .replace(",", r"\\,")
            .replace(";", r"\\;")
        )

    def _parse_ffmpeg_progress(
        self, line: str, total_duration: float
    ) -> tuple[float | None, str | None]:
        """
        Parse FFmpeg progress from stderr.

        Args:
            line: Output line from FFmpeg
            total_duration: Total video duration

        Returns:
            Tuple of (progress_percentage, status_message)
        """
        # Match time progress: time=00:00:10.50
        time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
        if time_match:
            hours = int(time_match.group(1))
            minutes = int(time_match.group(2))
            seconds = float(time_match.group(3))
            current_time = hours * 3600 + minutes * 60 + seconds

            max_time = min(total_duration, self.video_config.MAX_DURATION_SECONDS)
            percentage = min((current_time / max_time) * 100, 100)

            return percentage, f"Processing: {percentage:.1f}%"

        return None, None

    def process(
        self,
        input_path: Path,
        output_filename: str | None = None,
        logo_path: Path | None = None,
        subtitle_path: Path | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ProcessingResult:
        """
        Process a video for Facebook Reels.

        Args:
            input_path: Source video path
            output_filename: Optional custom output filename
            logo_path: Optional logo image for branding
            subtitle_path: Optional subtitle file to burn
            progress_callback: Optional progress callback

        Returns:
            ProcessingResult with success status and file info
        """
        progress = ProgressCallback(progress_callback)
        progress.update(5, 100, "Analyzing video...")

        # Verify input exists
        if not input_path.exists():
            return ProcessingResult(
                success=False,
                file_path=None,
                video_info=None,
                error_message=f"Input file not found: {input_path}",
            )

        # Get video info
        video_info = get_video_info(input_path)
        if not video_info:
            return ProcessingResult(
                success=False,
                file_path=None,
                video_info=None,
                error_message="Could not read video information",
            )

        logger.info(
            f"Processing video: {input_path.name} "
            f"({video_info['width']}x{video_info['height']}, "
            f"{video_info['duration_formatted']})"
        )

        if subtitle_path and subtitle_path.exists():
            ok, msg = check_ffmpeg_subtitles_support()
            if not ok:
                return ProcessingResult(
                    success=False,
                    file_path=None,
                    video_info=None,
                    error_message=msg,
                )

        progress.update(10, 100, "Preparing output...")

        # Generate output filename
        if output_filename:
            if not output_filename.endswith(".mp4"):
                output_filename += ".mp4"
        else:
            output_filename = generate_unique_filename(f"reel_{input_path.stem}", "mp4")

        output_path = self.output_dir / output_filename

        # Build FFmpeg command
        cmd = self._build_ffmpeg_command(
            input_path=input_path,
            output_path=output_path,
            input_width=video_info["width"],
            input_height=video_info["height"],
            duration=video_info["duration"],
            logo_path=logo_path,
            subtitle_path=subtitle_path,
        )

        logger.debug(f"FFmpeg command: {' '.join(cmd)}")

        progress.update(15, 100, "Processing video...")

        try:
            # Run FFmpeg with progress tracking
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
            )

            stderr_lines: list[str] = []

            q: queue.Queue[str | None] = queue.Queue()

            def reader():
                try:
                    if not process.stderr:
                        q.put(None)
                        return
                    for line in process.stderr:
                        q.put(line)
                finally:
                    q.put(None)

            t = threading.Thread(target=reader, daemon=True)
            t.start()

            cancelled = False

            # Read stderr for progress
            while True:
                if cancel_event and cancel_event.is_set() and not cancelled:
                    cancelled = True
                    try:
                        process.terminate()
                    except Exception:
                        pass

                try:
                    line = q.get(timeout=0.2)
                except queue.Empty:
                    if process.poll() is not None:
                        break
                    continue

                if line is None:
                    break

                stderr_lines.append(line.rstrip())

                percentage, status = self._parse_ffmpeg_progress(line, video_info["duration"])

                if percentage is not None:
                    mapped_progress = 15 + int(percentage * 0.75)
                    progress.update(mapped_progress, 100, status or "Processing...")

                logger.debug(line.strip())

            if cancelled:
                try:
                    process.wait(timeout=2)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                return ProcessingResult(
                    success=False,
                    file_path=None,
                    video_info=None,
                    error_message="Cancelado",
                )

            # `stderr` ya fue drenado por el hilo lector; `communicate()` solo
            # recogería el resto de stdout.
            _, stdout_tail = process.communicate()
            if stdout_tail:
                logger.debug(stdout_tail.strip())

            if process.returncode != 0:
                stderr_compact = "\n".join(stderr_lines[-80:]).strip()
                logger.error(f"FFmpeg failed: {stderr_compact}")
                return ProcessingResult(
                    success=False,
                    file_path=None,
                    video_info=None,
                    error_message=(
                        f"Video processing failed: {stderr_compact[-800:] if stderr_compact else 'Unknown error'}"
                    ),
                )

            progress.update(95, 100, "Finalizing...")

            # Verify output
            if not output_path.exists():
                return ProcessingResult(
                    success=False,
                    file_path=None,
                    video_info=None,
                    error_message="Output file was not created",
                )

            # Get output video info
            output_info = get_video_info(output_path)

            progress.update(100, 100, "Complete!")

            logger.info(
                f"Processing complete: {output_path.name} "
                f"({output_info['size_formatted'] if output_info else 'unknown size'})"
            )

            # Verifica que el resultado cumple las especificaciones de la
            # plataforma. Un fallo aquí no invalida el vídeo, pero debe
            # advertirse al usuario en vez de fallar en silencio.
            warnings: list[str] = []
            if self.video_config.VALIDATE_OUTPUT:
                warnings = self._validate_output(output_info)

            thumbnail_path = self._generate_thumbnail(output_path, output_path)

            return ProcessingResult(
                success=True,
                file_path=output_path,
                video_info=output_info,
                warnings=warnings,
                thumbnail_path=thumbnail_path,
            )

        except Exception as e:
            logger.error(f"Processing error: {e}")
            return ProcessingResult(
                success=False, file_path=None, video_info=None, error_message=str(e)
            )
        finally:
            self._cleanup_temp_artifacts()

    def _validate_output(self, output_info: dict | None) -> list[str]:
        """Comprueba que el vídeo final cumple las especificaciones.

        Facebook Reels exige 1080x1920 y una duración máxima de 55s. Si el
        resultado se aparta de esos valores, se devuelve un aviso para que la
        GUI lo muestre en lugar de fallar en silencio.

        Args:
            output_info: Metadatos del vídeo de salida

        Returns:
            Lista de avisos (vacía si todo es correcto)
        """
        if not output_info:
            return ["No se pudieron leer los metadatos del vídeo final."]

        warnings: list[str] = []
        target_w = self.video_config.WIDTH
        target_h = self.video_config.HEIGHT
        max_dur = self.video_config.MAX_DURATION_SECONDS

        width = output_info.get("width", 0)
        height = output_info.get("height", 0)
        duration = output_info.get("duration", 0.0)

        if (width, height) != (target_w, target_h):
            warnings.append(
                f"El vídeo final es {width}x{height} en lugar de {target_w}x{target_h}."
            )

        if duration > max_dur + 0.5:
            warnings.append(
                f"El vídeo final dura {duration:.1f}s, por encima del máximo de {max_dur}s."
            )

        if duration <= 0:
            warnings.append("El vídeo final tiene duración 0s.")

        return warnings

    def _generate_thumbnail(
        self, video_path: Path, output_path: Path, timestamp: float = 1.0
    ) -> Path | None:
        """Genera una miniatura PNG del primer segundo del vídeo.

        Args:
            video_path: Vídeo de entrada
            output_path: Vídeo de salida (para derivar el nombre)
            timestamp: Segundo del que se extrae el fotograma

        Returns:
            Ruta de la miniatura, o None si no se pudo generar
        """
        bins = resolve_binaries()
        if not bins.ffmpeg:
            return None

        thumbs_dir = config.paths.THUMBNAILS_PATH
        thumbs_dir.mkdir(parents=True, exist_ok=True)
        thumb_path = thumbs_dir / f"{output_path.stem}.jpg"

        cmd = [
            str(bins.ffmpeg),
            "-y",
            "-ss",
            str(timestamp),
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=270:-2",
            "-q:v",
            "3",
            str(thumb_path),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and thumb_path.exists():
                return thumb_path
            logger.warning(f"Could not generate thumbnail: {result.stderr[-200:]}")
        except Exception as e:
            logger.warning(f"Could not generate thumbnail: {e}")

        return None

    def _cleanup_temp_artifacts(self):
        """Elimina los archivos temporales creados durante el render."""
        for artifact in self._temp_artifacts:
            try:
                artifact.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Could not remove temp artifact {artifact}: {e}")
        self._temp_artifacts.clear()

    def cleanup_temp(self):
        """Clean up temporary files."""
        try:
            for file in self.temp_dir.glob("*"):
                if file.is_file():
                    file.unlink()
            logger.info("Temporary files cleaned up")
        except Exception as e:
            logger.warning(f"Could not clean temp files: {e}")


# Convenience function
def process_for_reels(
    input_path: Path,
    output_dir: Path | None = None,
    logo_path: Path | None = None,
    subtitle_path: Path | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> ProcessingResult:
    """
    Convenience function to process a video for Facebook Reels.

    Args:
        input_path: Source video path
        output_dir: Optional output directory
        logo_path: Optional logo image path
        subtitle_path: Optional subtitle file path
        progress_callback: Optional progress callback

    Returns:
        ProcessingResult
    """
    processor = VideoProcessor(output_dir)
    return processor.process(
        input_path=input_path,
        logo_path=logo_path,
        subtitle_path=subtitle_path,
        progress_callback=progress_callback,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python processor.py <input_video> [logo_path]")
        sys.exit(1)

    input_file = Path(sys.argv[1])
    logo_file = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    def print_progress(current, total, status):
        print(f"\r[{current:3d}%] {status}", end="", flush=True)

    print(f"Processing: {input_file}")
    result = process_for_reels(input_file, logo_path=logo_file, progress_callback=print_progress)

    print()  # New line

    if result.success:
        print(f"✓ Output: {result.file_path}")
        if result.video_info:
            print(f"  Size: {result.video_info['size_formatted']}")
            print(f"  Duration: {result.video_info['duration_formatted']}")
    else:
        print(f"✗ Error: {result.error_message}")
