# Plan de la v2

Fases ordenadas por riesgo y valor: primero lo seguro que mejora el resultado
hoy, la clonación (lo más incierto) al final.

## Fase A — Ajuste a los huecos y calidad (sin dependencias nuevas)
- Calibrar la velocidad real de cada voz (voz + `--rate`) sintetizando un texto
  de referencia antes de traducir, y usarla para `max_chars`. Se cachea por voz.
- Retraducir lo que no cabe: si un clip no entra ni a `--max-tempo`, pedir a
  Claude una versión más corta de esa frase y resintetizarla (hasta 2 rondas).
- Control de calidad barato: detectar clips con duración anómala para su
  longitud de texto (vacíos, cortados, repeticiones) y regenerarlos una vez.
- `--rate=-10%` por defecto.

## Fase B — Separación de voz y música
- Nueva fase `separate` (cacheable y ejecutable sola, como las demás) que genera
  `stems/vocals.wav` y `stems/background.wav`.
- Prueba comparativa previa: Mel-Band RoFormer (`audio-separator`) frente a
  HTDemucs en MLX; elegir por calidad y tiempo en Apple Silicon.
- `mix` usa `background.wav` a 0 dB cuando existe (`--separate`).
- Dependencias pesadas en un extra opcional.

## Fase C — Clonación de voz
- Prueba comparativa: Qwen3-TTS (MLX, confirmar licencia Apache 2.0 en la
  model card) frente a Chatterbox Multilingual (MIT, con marca de agua Perth).
- Motor `--tts edge|clone`; edge-tts sigue por defecto y como respaldo.
- Referencia: muestra de 10–15 s extraída de `vocals.wav` con su transcripción,
  **o una referencia fija en español** (fichero propio o voz de stock) como plan B
  si el acento inglés no convence.
- Un solo hablante (el principal); diarización para una v3.
- Control de calidad con whisper opcional, recalibrar velocidad por motor.
