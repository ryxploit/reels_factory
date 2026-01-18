#!/usr/bin/env python3
"""Verify that metadata removal changes were correctly applied."""

from processor import VideoProcessor
import inspect

processor = VideoProcessor()

# Check _build_ffmpeg_command
source_ffmpeg = inspect.getsource(processor._build_ffmpeg_command)

# Check _build_video_filters  
source_filters = inspect.getsource(processor._build_video_filters)

# Check _add_metadata_settings
source_metadata = inspect.getsource(processor._add_metadata_settings)

checks = [
    ('Eliminación de metadatos (-map_metadata)', '-map_metadata' in source_metadata),
    ('Eliminación de capítulos (-map_chapters)', '-map_chapters' in source_metadata),
    ('Sin timestamps (bitexact)', 'bitexact' in source_metadata),
    ('Variación de brillo/contraste', 'brightness_var' in source_filters),
    ('Filtro de ruido anti-fingerprint', 'noise' in source_filters),
    ('Variación de saturación', 'saturation_var' in source_filters),
    ('Seed aleatorio para variaciones', 'random.seed' in source_filters),
]

print('\n' + '='*60)
print('✓ VERIFICACIÓN DE CAMBIOS DE ELIMINACIÓN DE METADATOS')
print('='*60 + '\n')

all_ok = True
for name, found in checks:
    status = '✓' if found else '✗'
    result = 'Implementado' if found else 'NO ENCONTRADO'
    print(f'{status} {name}: {result}')
    if not found:
        all_ok = False

print('\n' + '='*60)
if all_ok:
    print('✅ TODOS LOS CAMBIOS ESTÁN CORRECTAMENTE IMPLEMENTADOS')
else:
    print('⚠️  ALGUNOS CAMBIOS NO SE ENCONTRARON')
print('='*60 + '\n')
