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

import subprocess
import queue
import threading
from pathlib import Path
from typing import Optional, Callable, Tuple
from dataclasses import dataclass

from config import config
from deps import resolve_binaries
from utils import (
    setup_logger,
    get_video_info,
    generate_unique_filename,
    ProgressCallback,
    check_ffmpeg_subtitles_support,
)


logger = setup_logger('processor', config.paths.LOGS_PATH / 'processor.log')


@dataclass
class ProcessingResult:
    """Result of a video processing operation."""
    success: bool
    file_path: Optional[Path]
    video_info: Optional[dict]
    error_message: Optional[str] = None


class VideoProcessor:
    """
    Video processor for Facebook Reels optimization.
    Handles reframing, trimming, branding, and encoding.
    """
    
    def __init__(
        self,
        output_dir: Optional[Path] = None,
        temp_dir: Optional[Path] = None
    ):
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
    
    def _calculate_crop_filter(
        self,
        input_width: int,
        input_height: int,
        target_width: int,
        target_height: int
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
        logo_path: Optional[Path] = None,
        subtitle_path: Optional[Path] = None
    ) -> str:
        """
        Build complete FFmpeg filter chain.
        
        Args:
            input_width: Source video width
            input_height: Source video height
            logo_path: Optional path to logo image
            subtitle_path: Optional path to subtitle file
        
        Returns:
            FFmpeg filter_complex string
        """
        target_width = self.video_config.WIDTH
        target_height = self.video_config.HEIGHT
        
        filters = []
        
        # 1. Crop to target aspect ratio (center crop)
        crop_filter = self._calculate_crop_filter(
            input_width, input_height,
            target_width, target_height
        )
        filters.append(crop_filter)
        
        # 2. Scale to exact output dimensions
        filters.append(f"scale={target_width}:{target_height}")
        
        # 3. Set frame rate
        filters.append(f"fps={self.video_config.FPS}")
        
        # Combine base video filters
        video_filter = ",".join(filters)
        
        # Handle complex filter graph if we have overlays
        if logo_path and logo_path.exists():
            # Calculate logo position (bottom right corner)
            logo_x = target_width - self.branding_config.LOGO_WIDTH - self.branding_config.LOGO_MARGIN_RIGHT
            logo_y = target_height - self.branding_config.LOGO_HEIGHT - self.branding_config.LOGO_MARGIN_BOTTOM
            
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
        logo_path: Optional[Path] = None,
        subtitle_path: Optional[Path] = None
    ) -> list[str]:
        """
        Build complete FFmpeg command.
        
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

        cmd = [str(bins.ffmpeg), '-y']
        
        # Input video
        cmd.extend(['-i', str(input_path)])
        
        # Input logo if provided
        use_complex_filter = logo_path and logo_path.exists()
        if use_complex_filter:
            cmd.extend(['-i', str(logo_path)])
        
        # Duration limit
        cmd.extend(['-t', str(max_duration)])
        
        # Build filter
        video_filter = self._build_video_filters(
            input_width, input_height,
            logo_path if use_complex_filter else None,
            subtitle_path
        )
        
        if use_complex_filter:
            cmd.extend(['-filter_complex', video_filter, '-map', '[out]', '-map', '0:a?'])
        else:
            cmd.extend(['-vf', video_filter])
        
        if subtitle_path and subtitle_path.exists():
            escaped_path = self._escape_filter_value(str(subtitle_path))
            subtitle_filter = f"subtitles=filename='{escaped_path}':charenc=UTF-8"

            if use_complex_filter:
                current_filter = cmd[cmd.index('-filter_complex') + 1]
                new_filter = current_filter.replace(
                    '[out]',
                    f"[temp];[temp]{subtitle_filter}[out]"
                )
                cmd[cmd.index('-filter_complex') + 1] = new_filter
            else:
                current_vf = cmd[cmd.index('-vf') + 1]
                cmd[cmd.index('-vf') + 1] = f"{current_vf},{subtitle_filter}"
        
        # Video codec settings (H.264 compatible with Facebook)
        cmd.extend([
            '-c:v', self.video_config.VIDEO_CODEC,
            '-preset', self.video_config.VIDEO_PRESET,
            '-b:v', self.video_config.VIDEO_BITRATE,
            '-maxrate', self.video_config.VIDEO_MAXRATE,
            '-bufsize', self.video_config.VIDEO_BUFSIZE,
            '-profile:v', self.video_config.VIDEO_PROFILE,
            '-level', self.video_config.VIDEO_LEVEL,
            '-pix_fmt', self.video_config.PIXEL_FORMAT,
        ])
        
        # Audio codec settings
        cmd.extend([
            '-c:a', self.video_config.AUDIO_CODEC,
            '-b:a', self.video_config.AUDIO_BITRATE,
            '-ar', str(self.video_config.AUDIO_SAMPLE_RATE),
            '-ac', str(self.video_config.AUDIO_CHANNELS),
        ])
        
        # Optimize for streaming/upload
        cmd.extend(['-movflags', '+faststart'])
        
        # Output file
        cmd.append(str(output_path))
        
        return cmd

    def _escape_filter_value(self, value: str) -> str:
        return (
            value.replace('\\', r'\\\\')
            .replace("'", r"\\'")
            .replace(':', r'\\:')
            .replace('#', r'\\#')
            .replace('[', r'\\[')
            .replace(']', r'\\]')
            .replace(',', r'\\,')
            .replace(';', r'\\;')
        )
    
    def _parse_ffmpeg_progress(
        self,
        line: str,
        total_duration: float
    ) -> Tuple[Optional[float], Optional[str]]:
        """
        Parse FFmpeg progress from stderr.
        
        Args:
            line: Output line from FFmpeg
            total_duration: Total video duration
        
        Returns:
            Tuple of (progress_percentage, status_message)
        """
        import re
        
        # Match time progress: time=00:00:10.50
        time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2}\.\d+)', line)
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
        output_filename: Optional[str] = None,
        logo_path: Optional[Path] = None,
        subtitle_path: Optional[Path] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
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
                error_message=f"Input file not found: {input_path}"
            )
        
        # Get video info
        video_info = get_video_info(input_path)
        if not video_info:
            return ProcessingResult(
                success=False,
                file_path=None,
                video_info=None,
                error_message="Could not read video information"
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
            if not output_filename.endswith('.mp4'):
                output_filename += '.mp4'
        else:
            output_filename = generate_unique_filename(
                f"reel_{input_path.stem}",
                'mp4'
            )
        
        output_path = self.output_dir / output_filename
        
        # Build FFmpeg command
        cmd = self._build_ffmpeg_command(
            input_path=input_path,
            output_path=output_path,
            input_width=video_info['width'],
            input_height=video_info['height'],
            duration=video_info['duration'],
            logo_path=logo_path,
            subtitle_path=subtitle_path
        )
        
        logger.debug(f"FFmpeg command: {' '.join(cmd)}")
        
        progress.update(15, 100, "Processing video...")
        
        try:
            # Run FFmpeg with progress tracking
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            stderr_lines: list[str] = []

            q: queue.Queue[Optional[str]] = queue.Queue()

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

                percentage, status = self._parse_ffmpeg_progress(
                    line,
                    video_info['duration']
                )

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

            _, stderr_tail = process.communicate()
            if stderr_tail:
                stderr_lines.extend([l.rstrip() for l in stderr_tail.splitlines()])
            
            if process.returncode != 0:
                stderr_compact = "\n".join(stderr_lines[-80:]).strip()
                logger.error(f"FFmpeg failed: {stderr_compact}")
                return ProcessingResult(
                    success=False,
                    file_path=None,
                    video_info=None,
                    error_message=(
                        f"Video processing failed: {stderr_compact[-800:] if stderr_compact else 'Unknown error'}"
                    )
                )
            
            progress.update(95, 100, "Finalizing...")
            
            # Verify output
            if not output_path.exists():
                return ProcessingResult(
                    success=False,
                    file_path=None,
                    video_info=None,
                    error_message="Output file was not created"
                )
            
            # Get output video info
            output_info = get_video_info(output_path)
            
            progress.update(100, 100, "Complete!")
            
            logger.info(
                f"Processing complete: {output_path.name} "
                f"({output_info['size_formatted'] if output_info else 'unknown size'})"
            )
            
            return ProcessingResult(
                success=True,
                file_path=output_path,
                video_info=output_info
            )
            
        except Exception as e:
            logger.error(f"Processing error: {e}")
            return ProcessingResult(
                success=False,
                file_path=None,
                video_info=None,
                error_message=str(e)
            )
    
    def cleanup_temp(self):
        """Clean up temporary files."""
        try:
            for file in self.temp_dir.glob('*'):
                if file.is_file():
                    file.unlink()
            logger.info("Temporary files cleaned up")
        except Exception as e:
            logger.warning(f"Could not clean temp files: {e}")


# Convenience function
def process_for_reels(
    input_path: Path,
    output_dir: Optional[Path] = None,
    logo_path: Optional[Path] = None,
    subtitle_path: Optional[Path] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
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
        progress_callback=progress_callback
    )


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python processor.py <input_video> [logo_path]")
        sys.exit(1)
    
    input_file = Path(sys.argv[1])
    logo_file = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    
    def print_progress(current, total, status):
        print(f"\r[{current:3d}%] {status}", end='', flush=True)
    
    print(f"Processing: {input_file}")
    result = process_for_reels(
        input_file,
        logo_path=logo_file,
        progress_callback=print_progress
    )
    
    print()  # New line
    
    if result.success:
        print(f"✓ Output: {result.file_path}")
        if result.video_info:
            print(f"  Size: {result.video_info['size_formatted']}")
            print(f"  Duration: {result.video_info['duration_formatted']}")
    else:
        print(f"✗ Error: {result.error_message}")
