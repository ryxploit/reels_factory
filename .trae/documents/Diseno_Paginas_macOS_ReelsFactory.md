# Diseño de pantallas (desktop-first) — App macOS

## Estilos globales
- Layout: base con CSS Grid (2 columnas) + Flexbox para controles; espaciado 8px/16px/24px.
- Breakpoints: desktop (>=1024) como principal; compact (<=900) colapsa sidebar a iconos.
- Tokens:
  - Background: #0B0F14 (app), Surface: #121826 (cards), Border: #243042
  - Primary: #4F8CFF; Success: #2ECC71; Danger: #FF4D4F; Warning: #FFB020
  - Tipografía: SF Pro (system); escala 12/14/16/20/24
  - Botones: primary sólido + hover (brillo +4%); secondary outline; disabled 40% opacidad
  - Links: subrayado on-hover; foco visible (outline 2px Primary)
- Componentes comunes:
  - Sidebar izquierda con navegación y estado global de cola
  - Topbar con nombre de proyecto, selector de carpeta de salida y acciones rápidas
  - Toasts no intrusivos para eventos (descarga iniciada, export finalizada, error)

## 1) Página: Inicio (Importar)
### Meta Information
- Title: “Importar — Reels Factory”
- Description: “Añade URLs de TikTok y crea trabajos con presets.”
- Open Graph: título + descripción + icono de la app (uso interno/compartir logs).

### Page Structure
- Grid 2 columnas: (izq) entrada y presets; (der) resumen + acciones.

### Sections & Components
1. Área “URLs de TikTok”
   - Textarea con pegado múltiple (1 URL por línea).
   - Botón “Validar y añadir” + contador válidas/ignoradas.
2. Preset de salida
   - Selector: “Vertical 1080x1920 (<=55s)” (y variantes si existen).
   - Campos básicos: duración máxima (55s bloqueado por preset), modo encuadre (fit/fill).
3. Destino
   - Selector de carpeta (dialog macOS) + previsualización de ruta.
4. Acción principal
   - Botón primary “Enviar a la cola”.
5. Panel derecho “Resumen”
   - Lista compacta de trabajos a crear (URL → nombre sugerido).
   - Nota de dependencias detectadas (FFmpeg/yt-dlp/Whisper: OK/Fail) con deep-link a Ajustes.

## 2) Página: Cola de trabajos
### Meta Information
- Title: “Cola — Reels Factory”
- Description: “Seguimiento de descargas y procesado por etapas.”

### Page Structure
- Tabla/lista a ancho completo + panel lateral de detalle.

### Sections & Components
1. Lista de trabajos
   - Filtrado por estado (Todos/Pendientes/En curso/Fallidos/Listos).
   - Columnas: nombre, etapa actual, progreso, duración detectada, fecha.
2. Progreso por etapas (en cada fila)
   - Mini-stepper: Descargar → Procesar → Subtítulos → Exportar.
3. Acciones por trabajo
   - Pausar/Cancelar/Reintentar; abrir carpeta; copiar log.
4. Panel de detalle
   - Log estructurado por etapas + errores con mensajes accionables.

## 3) Página: Editor (Overlay + Subtítulos)
### Meta Information
- Title: “Editor — Reels Factory”
- Description: “Ajusta overlay y estilo de subtítulos antes de exportar.”

### Page Structure
- Layout 3 columnas: (izq) assets/overlays, (centro) preview, (der) propiedades.

### Sections & Components
1. Preview central
   - Reproductor 9:16 con safe-area; timeline simple.
   - Botón “Generar preview” (proxy rápido) y “Exportar final”.
2. Overlay
   - Selector de overlay (archivo imagen/video).
   - Controles: posición (x/y), escala, opacidad, anclaje (top/center/bottom).
3. Subtítulos
   - Botón “Generar con Whisper (MPS)” + selector de idioma.
   - Estado del modelo (descargado/cargando) y progreso de transcripción.
   - Toggle “Reformatear en líneas cortas” (legibilidad vertical).
4. Estilo de subtítulos
   - Tipografía, tamaño, color, borde/sombra, fondo semitransparente.
   - Presets: “TikTok Bold”, “Minimal”, “High Contrast”.

## 4) Página: Ajustes
### Meta Information
- Title: “Ajustes — Reels Factory”
- Description: “Configura dependencias locales, rendimiento y defaults.”

### Page Structure
- Secciones apiladas en cards; inputs alineados a la izquierda.

### Sections & Components
1. Dependencias
   - Campos: ruta a FFmpeg, ruta a yt-dlp, ruta a Python.
   - Botón “Auto-detectar” y “Probar”.
2. Whisper
   - Selector de modelo (base/small/medium) y ubicación de caché.
   - Toggle “Usar MPS (Apple Silicon)”.
3. Rendimiento
   - Concurrencia máxima (1–N) con aviso de uso de CPU/GPU.
4. Defaults
   - Plantilla de nombre de export: “{fecha}_{id}_{titulo}”.
   - Carpeta por defecto (si aplica).
