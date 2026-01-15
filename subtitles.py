"""
Reels Factory - Subtitles Module
=================================
Generates automatic subtitles using OpenAI Whisper.
Creates stylized ASS subtitles optimized for social media.

Optimized for macOS Apple Silicon.
"""

import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional, Callable, List
from dataclasses import dataclass
import subprocess

from config import config
from deps import resolve_binaries
from utils import setup_logger, ProgressCallback, sanitize_filename


logger = setup_logger('subtitles', config.paths.LOGS_PATH / 'subtitles.log')


@dataclass
class SubtitleSegment:
    """A single subtitle segment."""
    start: float  # Start time in seconds
    end: float    # End time in seconds
    text: str     # Subtitle text


@dataclass
class SubtitleResult:
    """Result of subtitle generation."""
    success: bool
    subtitle_path: Optional[Path]
    segments: Optional[List[SubtitleSegment]]
    language: Optional[str]
    error_message: Optional[str] = None


class SubtitleGenerator:
    """
    Automatic subtitle generator using OpenAI Whisper.
    Generates stylized ASS subtitles for social media videos.
    """
    
    def __init__(
        self,
        output_dir: Optional[Path] = None,
        model_size: Optional[str] = None
    ):
        """
        Initialize the subtitle generator.
        
        Args:
            output_dir: Directory for subtitle files
            model_size: Whisper model size (tiny, base, small, medium, large)
        """
        self.output_dir = output_dir or config.paths.SUBTITLES_PATH
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.model_size = model_size or config.subtitle.MODEL_SIZE
        self.subtitle_config = config.subtitle
        
        self._model = None
        self._model_loaded = False
    
    def _load_model(self):
        """Load the Whisper model (lazy loading)."""
        if self._model_loaded:
            return
        
        audio_path: Optional[Path] = None
        try:
            import whisper
            import torch
            
            logger.info(f"Loading Whisper model: {self.model_size}")

            device = "cpu"
            if self.subtitle_config.USE_MPS and getattr(torch.backends, "mps", None) is not None:
                try:
                    if torch.backends.mps.is_available():
                        device = "mps"
                except Exception:
                    device = "cpu"

            self._model = whisper.load_model(self.model_size, device=device)
            
            self._model_loaded = True
            logger.info("Whisper model loaded successfully")
            
        except ImportError:
            raise ImportError(
                "openai-whisper not installed. "
                "Install with: pip install openai-whisper"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load Whisper model: {e}")
    
    def _format_ass_time(self, seconds: float) -> str:
        """
        Format time in ASS subtitle format (H:MM:SS.cc).
        
        Args:
            seconds: Time in seconds
        
        Returns:
            Formatted time string
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centisecs = int((seconds % 1) * 100)
        
        return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"
    
    def _create_ass_header(self, video_width: int = 1080, video_height: int = 1920) -> str:
        """
        Create ASS subtitle file header with styling.
        
        Args:
            video_width: Video width for positioning
            video_height: Video height for positioning
        
        Returns:
            ASS header string
        """
        cfg = self.subtitle_config
        
        header = f"""[Script Info]
Title: Reels Factory Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {video_width}
PlayResY: {video_height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{cfg.FONT_NAME},{cfg.FONT_SIZE},{cfg.PRIMARY_COLOR},{cfg.HIGHLIGHT_COLOR},{cfg.OUTLINE_COLOR},{cfg.BACK_COLOR},-1,0,0,0,100,100,0,0,1,{cfg.OUTLINE_WIDTH},{cfg.SHADOW_DEPTH},2,10,10,{cfg.MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        return header
    
    def _segments_to_ass(
        self,
        segments: List[SubtitleSegment],
        video_width: int = 1080,
        video_height: int = 1920
    ) -> str:
        """
        Convert subtitle segments to ASS format.
        
        Args:
            segments: List of subtitle segments
            video_width: Video width
            video_height: Video height
        
        Returns:
            Complete ASS file content
        """
        ass_content = self._create_ass_header(video_width, video_height)
        
        for segment in segments:
            start_time = self._format_ass_time(segment.start)
            end_time = self._format_ass_time(segment.end)
            
            # Clean text and escape special characters
            text = segment.text.strip()
            text = text.replace('\n', '\\N')  # ASS line break
            
            # Add dialogue line
            ass_content += f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{text}\n"
        
        return ass_content
    
    def _extract_audio(self, video_path: Path, cancel_event: Optional[threading.Event] = None) -> Path:
        """
        Extract audio from video for transcription.
        
        Args:
            video_path: Path to video file
        
        Returns:
            Path to extracted audio file
        """
        fd, tmp_path = tempfile.mkstemp(suffix=".wav", dir=str(config.paths.TEMP_PATH))
        os.close(fd)
        audio_path = Path(tmp_path)

        bins = resolve_binaries()
        if not bins.ffmpeg:
            raise RuntimeError("FFmpeg not found")
        
        cmd = [
            str(bins.ffmpeg),
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(audio_path),
        ]

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            while process.poll() is None:
                if cancel_event and cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except Exception:
                        process.kill()
                    audio_path.unlink(missing_ok=True)
                    raise RuntimeError("Cancelado")
                time.sleep(0.1)

            stdout, stderr = process.communicate()
            if process.returncode != 0:
                audio_path.unlink(missing_ok=True)
                raise RuntimeError(f"Audio extraction failed: {(stderr or stdout).strip()}")
        finally:
            try:
                if process.stdout:
                    process.stdout.close()
            except Exception:
                pass
            try:
                if process.stderr:
                    process.stderr.close()
            except Exception:
                pass

        return audio_path
    
    def generate(
        self,
        video_path: Path,
        output_filename: Optional[str] = None,
        language: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> SubtitleResult:
        """
        Generate subtitles for a video.
        
        Args:
            video_path: Path to video file
            output_filename: Optional custom filename for subtitle file
            language: Optional language code (auto-detected if not specified)
            progress_callback: Optional progress callback
        
        Returns:
            SubtitleResult with subtitle file path and segments
        """
        progress = ProgressCallback(progress_callback)
        progress.update(5, 100, "Initializing...")

        def raise_if_cancelled():
            if cancel_event and cancel_event.is_set():
                raise RuntimeError("Cancelado")
        
        # Verify input
        if not video_path.exists():
            return SubtitleResult(
                success=False,
                subtitle_path=None,
                segments=None,
                language=None,
                error_message=f"Video not found: {video_path}"
            )
        
        try:
            raise_if_cancelled()
            progress.update(10, 100, "Loading Whisper model...")
            self._load_model()

            raise_if_cancelled()
            
            progress.update(20, 100, "Extracting audio...")
            
            # Extract audio
            audio_path = self._extract_audio(video_path, cancel_event=cancel_event)

            raise_if_cancelled()
            
            progress.update(30, 100, "Transcribing audio...")
            
            logger.info(f"Transcribing: {video_path.name}")
            
            # Transcribe with OpenAI Whisper
            transcribe_options = {
                "task": "transcribe",
                "verbose": False,
            }
            
            if language:
                transcribe_options["language"] = language
            
            result = self._model.transcribe(str(audio_path), **transcribe_options)

            raise_if_cancelled()
            
            detected_language = result.get("language", "unknown")
            logger.info(f"Detected language: {detected_language}")
            
            progress.update(70, 100, "Processing segments...")
            
            # Convert to SubtitleSegment objects
            segments: List[SubtitleSegment] = []
            whisper_segments = result.get("segments", [])
            total_segments = len(whisper_segments)
            
            for i, segment in enumerate(whisper_segments):
                segments.append(SubtitleSegment(
                    start=segment["start"],
                    end=segment["end"],
                    text=segment["text"]
                ))
                
                # Update progress (70-85% range)
                if total_segments > 0:
                    seg_progress = 70 + int((i / total_segments) * 15)
                    progress.update(seg_progress, 100, f"Processing segment {i+1}/{total_segments}")
            
            if not segments:
                audio_path.unlink(missing_ok=True)
                return SubtitleResult(
                    success=False,
                    subtitle_path=None,
                    segments=None,
                    language=detected_language,
                    error_message="No speech detected in video"
                )
            
            progress.update(85, 100, "Creating subtitle file...")
            
            # Generate ASS content
            ass_content = self._segments_to_ass(segments)
            
            # Save subtitle file
            if output_filename:
                if not output_filename.endswith('.ass'):
                    output_filename += '.ass'
            else:
                output_filename = f"{sanitize_filename(video_path.stem)}.ass"
            
            subtitle_path = self.output_dir / output_filename
            subtitle_path.write_text(ass_content, encoding='utf-8')
            
            progress.update(95, 100, "Cleaning up...")
            
            # Clean up audio file
            audio_path.unlink(missing_ok=True)
            
            progress.update(100, 100, "Complete!")
            
            logger.info(f"Subtitles generated: {subtitle_path} ({len(segments)} segments)")
            
            return SubtitleResult(
                success=True,
                subtitle_path=subtitle_path,
                segments=segments,
                language=detected_language
            )
            
        except ImportError as e:
            return SubtitleResult(
                success=False,
                subtitle_path=None,
                segments=None,
                language=None,
                error_message=str(e)
            )
        except Exception as e:
            logger.error(f"Subtitle generation failed: {e}")
            return SubtitleResult(
                success=False,
                subtitle_path=None,
                segments=None,
                language=None,
                error_message=str(e)
            )
        finally:
            try:
                if audio_path:
                    audio_path.unlink(missing_ok=True)
            except Exception:
                pass
    
    def generate_srt(
        self,
        video_path: Path,
        output_filename: Optional[str] = None,
        language: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> SubtitleResult:
        """
        Generate SRT subtitles (simpler format).
        
        Args:
            video_path: Path to video file
            output_filename: Optional custom filename
            language: Optional language code
            progress_callback: Optional progress callback
        
        Returns:
            SubtitleResult with SRT file path
        """
        # First generate ASS
        result = self.generate(video_path, None, language, progress_callback)
        
        if not result.success:
            return result
        
        # Convert to SRT
        srt_content = self._segments_to_srt(result.segments)
        
        if output_filename:
            if not output_filename.endswith('.srt'):
                output_filename += '.srt'
        else:
            output_filename = f"{video_path.stem}.srt"
        
        srt_path = self.output_dir / output_filename
        srt_path.write_text(srt_content, encoding='utf-8')
        
        return SubtitleResult(
            success=True,
            subtitle_path=srt_path,
            segments=result.segments,
            language=result.language
        )
    
    def _segments_to_srt(self, segments: List[SubtitleSegment]) -> str:
        """
        Convert segments to SRT format.
        
        Args:
            segments: List of subtitle segments
        
        Returns:
            SRT file content
        """
        srt_content = ""
        
        for i, segment in enumerate(segments, 1):
            start = self._format_srt_time(segment.start)
            end = self._format_srt_time(segment.end)
            
            srt_content += f"{i}\n"
            srt_content += f"{start} --> {end}\n"
            srt_content += f"{segment.text.strip()}\n\n"
        
        return srt_content
    
    def _format_srt_time(self, seconds: float) -> str:
        """Format time for SRT (HH:MM:SS,mmm)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


# Convenience function
def generate_subtitles(
    video_path: Path,
    output_dir: Optional[Path] = None,
    language: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> SubtitleResult:
    """
    Convenience function to generate subtitles for a video.
    
    Args:
        video_path: Path to video file
        output_dir: Optional output directory
        language: Optional language code
        progress_callback: Optional progress callback
    
    Returns:
        SubtitleResult
    """
    generator = SubtitleGenerator(output_dir)
    return generator.generate(video_path, None, language, progress_callback)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python subtitles.py <video_file> [language]")
        print("Example: python subtitles.py video.mp4 es")
        sys.exit(1)
    
    video_file = Path(sys.argv[1])
    lang = sys.argv[2] if len(sys.argv) > 2 else None
    
    def print_progress(current, total, status):
        print(f"\r[{current:3d}%] {status}", end='', flush=True)
    
    print(f"Generating subtitles for: {video_file}")
    result = generate_subtitles(video_file, language=lang, progress_callback=print_progress)
    
    print()  # New line
    
    if result.success:
        print(f"✓ Subtitles: {result.subtitle_path}")
        print(f"  Language: {result.language}")
        print(f"  Segments: {len(result.segments)}")
    else:
        print(f"✗ Error: {result.error_message}")
