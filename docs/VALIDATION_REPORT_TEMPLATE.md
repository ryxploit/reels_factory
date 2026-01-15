# Informe de validación — plantilla

## Alcance

- Versiones objetivo:
  - macOS: estable actual + N-1 + N-2
  - Windows 10: 21H2+
  - Windows 11: 22H2+

## Matriz de pruebas

| Plataforma | Arquitectura | Caso | Resultado | Evidencia |
|---|---:|---|---|---|
| macOS | arm64 | Descargar TikTok |  |  |
| macOS | arm64 | Procesar 1080x1920 <=55s |  |  |
| macOS | arm64 | Subtítulos (Whisper) |  |  |
| Windows 10 | x64 | Descargar TikTok |  |  |
| Windows 10 | x64 | Procesar 1080x1920 <=55s |  |  |
| Windows 10 | x64 | Subtítulos (Whisper) |  |  |

## Pruebas de rendimiento

- Tiempo descarga
- Tiempo render FFmpeg
- Tiempo transcripción
- Memoria pico

## Instalación / desinstalación limpia

- macOS: arrastre a Applications / borrar
- Windows: Add/Remove Programs

## Checksums

- Adjuntar `SHA256SUMS.txt`

