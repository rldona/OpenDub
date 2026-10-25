# Auditoría 1 · Producto

Estado real de OpenDub a 25 de octubre de 2026 (commit `9fe1fee`), leído en la
implementación y comprobado con ejecuciones, no en el README. Ingeniería
(arquitectura, fiabilidad, tests, seguridad) está en
[02-ingenieria.md](02-ingenieria.md); la numeración de gaps continúa allí.

## Método y evidencia

- Código leído: `src/opendub/` (pipeline, fases, motores, web) y `frontend/src/`
  (shell, biblioteca, vídeo, comparación, hablantes, estilo, preferencias).
- Ejecutado:
  - `uv run pytest` → **160 pasan, 1 omitido**. El omitido es el smoke test de motores, que pide `OPENDUB_SMOKE`.
  - CI en local, en un venv limpio con solo `--extra web` (sin torch) → 160 pasan. `npm ci && npm run build` reproduce `src/opendub/web/static` sin diferencias.
  - En GitHub, el último run de CI pasa (run 40215031183).
  - `ruff`, `mypy` y cobertura (`pytest-cov`, total 78 %).
  - Una sonda de peticiones cross-site contra la API.
  - Medidas de sonoridad EBU R128 y estadísticas de ajuste sobre doblajes reales de `work/`.
- Documentos leídos:
  - [v2-plan.md](../v2-plan.md).
  - [bench/README.md](../bench/README.md) y `bench/metrics.py`.
  - [bench/diarize/README.md](../bench/diarize/README.md).
- Las preguntas P1–P9 están al final de [02-ingenieria.md](02-ingenieria.md#preguntas-para-el-propietario).
- Leyenda de las afirmaciones:
  - **Hecho** (verificado en código o ejecución).
  - **Hipótesis** (deducido del código, no ejecutado).
  - **Pregunta** (para el propietario).

### Diferencias con el contexto del encargo

| Encargo | Realidad verificada |
|---|---|
| "Un único hablante; diarización prevista para más adelante" | **Hecho**: ya existe, opt-in. `--multi-speaker` y la casilla "Varias voces" de la web usan Nemotron 3 Diarization (`diarize.py`, commits `a360aee`–`9fe1fee`). Desactivada por defecto; el flujo de una voz no cambia. |
| "Chatterbox (afinado es-ES) por defecto" | **Hecho**: `clone._load` carga `ChatterboxMultilingualTTS.from_pretrained(t3_model="v3")`, el modelo **multilingüe V3**, no el afinado `Chatterbox-Multilingual-es-es`. `v2-plan.md` (Fase C) dice que se eligió V3 tras escuchar. **Pregunta P1**. |
| "Chatterbox por defecto" | **Hecho**: es el valor por defecto en la CLI (`Settings.engine = "chatterbox"`), pero **no en la web**: `JobRequest.engine = "auto"` y `prefs.tsx` usa `engine: "auto"`. *Automático* elige IndexTTS si la referencia baja de 165 Hz (`tts.resolve_engine`), algo que `v2-plan.md` describe como opt-in. **Pregunta P2**. |
| "Solo español" | **Hecho**: la traducción apunta a castellano o español latino neutro (`style.target_name`); no hay otros idiomas de destino. |

## 1. Estado del producto en una frase

OpenDub dobla de punta a punta un vídeo de YouTube al español con la voz
clonada del hablante, desde la CLI o desde una web local. Usa caché por fase,
control de calidad por clip, versiones comparables y retoque de frases sueltas.
Es sólido en el camino feliz y está bien instrumentado. Sus debilidades están en
lo que pasa fuera de ese camino: cancelar, trabajar sin red, poner orden en el
disco, sonoridad homogénea y una evaluación de calidad repetible.

## 2. Inventario de capacidades

Estados: **V** implementada y verificada · **P** implementada pero poco probada ·
**Pa** parcial · **E** experimental o frágil · **A** ausente · **D** desconocida.

| Capacidad | Estado | Evidencia |
|---|---|---|
| Descarga (yt-dlp, H.264 ≤1080p, subtítulos manuales y automáticos, miniatura) | P | `download.run`; cobertura 32 %. Hoy YouTube bloqueó descargas ("Sign in to confirm you're not a bot") y no hay vía alternativa (G-001). |
| Transcripción (subtítulos manuales → automáticos → faster-whisper) | V | `transcribe._choose_source`, `segments.regroup`; 11 tests de segmentación; reagrupado de fragmentos (`join_fragments`). |
| Separación HTDemucs (MLX en Apple Silicon, PyTorch en el resto) | P | `separate.py`; los 3 tests no ejecutan el modelo. Bench en `v2-plan.md` Fase B. |
| Diarización (Nemotron 3, opt-in) | E | `diarize.py`, `segments._assign_speakers`. Bench con conversaciones sintéticas y 1 entrevista real; integración probada en 1 vídeo real, sin escucha. |
| Traducción con Claude (CLI o API), por bloques y con caché por bloque | V | `translate.run`, 14 tests. Reanudación tras fallo (`test_run_resumes_from_saved_blocks_and_caches`). |
| Estilo y glosario (global y por vídeo) | V | `style.py`; tests; retraducción selectiva probada en real (1 bloque de 7). |
| Calibración del ritmo de cada voz | V | `tts.cloned_speaking_rate`, `fit_pace`, caché en `voice_rates.json`. |
| edge-tts (voz de stock) | V | `_synthesize_all` con 3 reintentos; depende de un servicio de Microsoft no oficial. |
| Chatterbox Multilingual V3, pool de 2 procesos | V | `clone.synthesize_batch`; `v2-plan.md` Fase D (320,9 → 254,2 s). |
| IndexTTS-2.5 (venv propio) | V | `indextts.py`, `engines.Worker`; bench y doblajes reales. |
| CosyVoice 3 (venv propio) | V | `cosyvoice.py`, `engines/cosyvoice/uv.lock`. |
| Ajuste de duración (atempo ≤1,25; factor nativo con suelo 0,7 → acortar → 0,5) | V | `tts._fit_native`, `_shorten_overflows`, `_below_floor`; tests en `test_indextts.py` y `test_tts.py`. |
| QC por clip (duración anómala y CER de whisper) con cadena de reparación | V | `tts.suspicious`, `clone.unintelligible`, `tts._repair_clones`; tests de la cadena. |
| Mezcla (fondo separado u original atenuado, retraso sin solapes) | P | `mix.place/compose/filter_graph`; 4 tests. **Sin normalización de sonoridad** (§5.5). |
| Versiones (una por doblaje, enlace duro, borrar las no actuales) | V | `mix.archive`, `videos.outputs`; 5 tests. |
| Comparación A/B sincronizada | P | `Compare.tsx`. Sin tests de frontend (G-026). |
| Edición de traducción y retoque de frases (otra toma, ediciones) | V | `tts.retouch`, `test_retouch.py`; probado en real (3 frases en 42 s). |
| Exportar MKV, M4A y SRT | V | `export.py`, 3 tests con ffmpeg real. |
| Varias voces: referencia y voz por hablante, concordancia de sexo, correcciones web | E | `tts.speaker_voices`, `speakers.py`, `Speakers.tsx`; probado en 1 vídeo real (§5.7). |
| Cola de trabajos web con progreso SSE y ETA | V | `web/jobs.py`, `job.tsx`; tests de SSE y reanudación (`Last-Event-ID`). |
| Cancelar un trabajo | A | Ni en el código Python ni en el frontend (G-002). |
| Borrar un vídeo o limpiar intermedios desde la web | A | Solo `DELETE /videos/{id}/outputs/{version}` (G-003). |
| Varios idiomas de destino | A | Fuera de alcance (solo español). |
| Instalación de motores (`setup-engine`) | P | Instaladores para indextts, cosyvoice y nemotron; sin tests de instalación. |
| Funcionamiento sin conexión con motores locales | A | La fase de voz consulta edge-tts por red siempre (G-004). |

## 3. Recorridos de usuario

### 3.1 CLI: `uv run opendub dub <url> --tts clone --separate`

1. **`pipeline.dub`:** el orden es descarga → transcripción → separación →
   traducción → voz → mezcla. Con `--multi-speaker`, la separación y la
   diarización van antes de transcribir. Cada fase guarda en `manifest.json`
   un hash de sus parámetros y se salta si coincide (`WorkDir.is_done`).
2. **Errores:** las fases cortan con `SystemExit` y un mensaje legible, por
   ejemplo motor no instalado (`SETUP_HINT`), ffmpeg ausente
   (`media.require_ffmpeg`) o sin voces separadas. **Hecho**: los mensajes
   dicen qué comando ejecutar.
3. **Resultado:** `work/<id>/output.mp4`, más `outputs/<fecha>-<motor>.mp4`
   como versión guardada. Con `-o` se copia a otra ruta.
4. **Retocar:** `opendub retouch <id> --take N` rehace frases sueltas; `opendub
   export` exporta MKV, M4A o SRT.
5. **Fricción observada:**
   - `--tts clone` exige `--separate` para conservar la música. Sin él, la mezcla
     usa el original atenuado a −15 dB, con la voz original por debajo
     (`mix.filter_graph`).
   - La CLI no tiene `--keep-music`; el nombre `--separate` describe el cómo, no
     el qué.

### 3.2 Web: `uv run opendub web`

1. **Biblioteca:**
   - Se pega una URL y se elige voz y motor (por defecto *Automático*), conservar
     la música y "Varias voces" (`Library.tsx/NewDub`).
   - El progreso aparece en "Doblando ahora" con fases, porcentaje, ETA y log
     (`NowDubbing`).
   - La lista muestra versiones, la última, avisos y estado, con botón de
     reintentar.
2. **Vídeo** (`Video.tsx`):
   - Reproductor, línea de tiempo de avisos y versiones (descargar en 5
     formatos, borrar las no actuales).
   - Tarjetas de hablantes y de estilo.
   - Tabla de traducción editable, con contador de caracteres y avisos por
     frase.
   - Barra de retoque o redoblaje.
3. **Comparar:** dos versiones sincronizadas; teclas A/B; tabla de cómo encajó
   cada una y lista de frases donde difieren.
4. **Motores:** licencia, dónde corre, cifras del bench e instalación. Las
   cifras salen de un catálogo estático (`catalog.ts`).
5. **Preferencias:** tema, acento de color, idioma, valores por defecto de
   nuevos doblajes y estilo global de traducción.

### 3.3 Instalación y primer uso

- **Requisitos:** `uv`, `ffmpeg`, el CLI de Claude Code con suscripción o
  `ANTHROPIC_API_KEY`, y conexión (YouTube, Claude, edge-tts, Hugging Face).
- **Extras opcionales:** `web`, `separate` (torch cu128), `clone`. Los motores
  propios se instalan con `setup-engine`. La [instalación del README](../../README.md#installation)
  es clara y da el comando para cada motor.
- **Plataformas:**
  - **Linux + CUDA** es el objetivo y está probado (RTX 5080).
  - **CPU**: whisper y Demucs caen a CPU con aviso (**Hecho**,
    `transcribe.whisper_device`, `separate._separate_torch`). Chatterbox en CPU
    no está medido.
  - **Apple Silicon**: separación con MLX y whisper en CPU. IndexTTS, CosyVoice
    y Nemotron fijan wheels CUDA 12.8 (`engines/*/pyproject.toml`; Nemotron
    además limita el entorno a Linux), así que no se instalan en un Mac
    (**hipótesis**, no probado). `clone._device` contempla `mps`, pero nadie lo
    ha probado (**desconocida**).
- **Disco hasta el primer doblaje** (medido en esta máquina):
  - Modelos de motores: 15 GB en `~/.local/share/opendub` y 23 GB de caché de
    Hugging Face (incluye los benches).
  - Por vídeo: 0,2 GB (2,5 min), 1,2 GB (30–47 min) y 3,0 GB (70 min, con
    voces separadas de 1,4 GB).
  - Hoy `work/` ocupa 51 GB, 43 de ellos de benches.
- **Tiempo:**
  - Vídeo de 28 min con IndexTTS: 19,9 min (`v2-plan.md`, Fase D).
  - Entrevista de 70 min con varias voces y Chatterbox: unos 22 min (traducción
    285 s, voz 831 s, mezcla 118 s).

## 4. UX: problemas observados

Solo lo inspeccionado en los componentes citados.

| # | Problema del usuario | Comportamiento actual | Esperado | Evidencia |
|---|---|---|---|---|
| U1 | No puede parar un doblaje lanzado por error o atascado | No hay botón ni endpoint; solo un doble Ctrl+C en el terminal, que mata el servidor entero | Cancelar el trabajo en curso o quitarlo de la cola | `web/jobs.py` (sin cancelación), `app.ExitGuard` |
| U2 | No puede borrar un vídeo ni recuperar disco desde la web | Solo se borran versiones no actuales; las voces separadas, los clips en bruto y los vídeos quedan | Borrar un vídeo entero o limpiar sus intermedios | `app.delete_version`; §2.4 de ingeniería |
| U3 | La interfaz en español muestra mensajes en inglés | Logs del trabajo, errores de la API ("Not translated yet") y `job_failed` con el mensaje crudo de la fase | Mensajes de error traducidos, o al menos marcados como técnicos | `NowDubbing` (`ul.log lang="en"`), `app.py` |
| U4 | El idioma por defecto de la interfaz es inglés | `prefs.tsx`: `lang: "en"` | Que siga el idioma del navegador o del propietario | `prefs.tsx` |
| U5 | No puede pasar un vídeo ya doblado a varias voces desde su página | `RedubDialog` no tiene la opción; hay que volver a pegar la URL en "Nuevo doblaje" | La opción también al redoblar | `RedubDialog.tsx` |
| U6 | Algunos controles por frase no se descubren | "+ glosario" y "otra toma" tienen opacidad 0 hasta pasar el ratón o enfocar (en pantallas táctiles sí se ven) | Una pista visible de que existen | `styles.css` `.add-term`, `.row-action` |
| U7 | Si YouTube bloquea la descarga, el error es un volcado de yt-dlp | "Sign in to confirm you're not a bot" sin explicar qué hacer | Explicar la causa y las opciones | Observado hoy; `download.run` |
| U8 | La carga se indica con "…" | Las páginas muestran el texto `…` mientras cargan | Un estado de carga reconocible | `Video.tsx`, `Compare.tsx` |
| U9 | La web y la CLI eligen motor distinto por defecto | Web: *Automático* (F0); CLI: Chatterbox | Un mismo criterio, o el porqué visible | Diferencias con el encargo; P2 |

**Bien resuelto:**
- Estados vacío y "sin coincidencias" en la biblioteca, servidor inalcanzable en
  el pie y vídeo no encontrado.
- Edición bloqueada mientras se dobla (409), con un aviso.
- `aria-*` y roles en controles, barras de progreso y grupos de radio.
- Teclas A/B en Comparar y foco visible.
- Tablas anchas con scroll en móvil.

## 5. Calidad del doblaje

### 5.1 Lo medido en doblajes reales

| Vídeo | Motor | Clips | Acelerados (máx.) | No caben (máx.) | Retrasados en la mezcla (máx. · suma) | edge-tts | Acortados |
|---|---|---|---|---|---|---|---|
| `17kBVfGjI8c` (2,5 min, hombre) | CosyVoice | 24 | 0 | 0 | 0 | 0 | — |
| `rwF-X5STYks` (2 min, mujer) | CosyVoice | 17 | 0 | 0 | 0 | **1** | — |
| `KS837a-TFRc` (19 min) | Chatterbox | 199 | 46 (23 %, 1,25×) | 1 (+0,09 s) | 49 (0,45 s · 8,4 s) | 0 | 0* |
| `h7PA4mXE_GA` (70 min, 3 voces) | Chatterbox | 738 | 91 (12 %, 1,25×) | 9 (+1,81 s) | 100 (1,89 s · 14,1 s) | 2 | 11 |

\* La última versión de `KS837a` es un retoque; `stats.shortened` cuenta solo
ese retoque.

### 5.2 Traducción

- **Qué hace bien:**
  - Límite de caracteres por frase según el ritmo calibrado de la voz.
  - Contexto de las 5 frases anteriores.
  - Esquema JSON validado, con 3 reintentos si faltan ids.
  - Glosario y tratamiento.
  - Las ediciones a mano se respetan y nunca se acortan.
- **Sin medir:** fidelidad y pérdida semántica al acortar. En `KS837a` hubo 14
  frases "probablemente largas" en la traducción y la ronda de acortado reescribe
  sin comprobar el significado. No hay retrotraducción ni revisión automática
  (G-005). **Hipótesis**: Chatterbox, que no controla su ritmo, acorta más que
  los motores con factor nativo, como apunta `v2-plan.md` (36 frases acortadas
  con IndexTTS frente a 4 con CosyVoice en el mismo vídeo).

### 5.3 Voz y QC

- Los motores se eligieron por escucha (no se reabre).
- **Cadena de reparación:** QC por CER de whisper (umbral 0,3; 0,6 en textos
  cortos) más duración anómala. Si falla: otra semilla → frase acortada →
  referencia fija → edge-tts. Cifras: 19 clips rehechos y 2 en edge-tts en 70
  min; 0–1 en vídeos cortos.
- **Defecto verificado (G-006):** con una sola voz, el último recurso es
  `settings.voice` (por defecto `es-ES-AlvaroNeural`, masculina) aunque el
  hablante sea mujer. En `rwF-X5STYks` (F0 214 Hz) la frase 11 la dice Álvaro en
  mitad de una voz femenina clonada. Con varias voces ya se elige la voz de stock
  por sexo (`tts.stock_voice`).
- **edge-tts como reserva:** cambia de timbre a mitad de vídeo. Está registrado
  (`overflow.log`, aviso "fallback" en la web), pero no se puede evitar salvo con
  `--clone-ref`.

### 5.4 Sincronía

- **Recursos:** atempo hasta 1,25× (en el 12–23 % de los clips con Chatterbox) y
  retraso del clip siguiente con 0,08 s de hueco cuando no cabe (`mix.place`).
  La deriva se recupera en la siguiente pausa. Con CosyVoice no hizo falta
  ninguno en los vídeos cortos.
- **Sin medir:** el desfase acumulado entre voz e imagen. Los retrasos máximos
  (1,9 s) indican que puede haber tramos con voz tardía (G-007).

### 5.5 Mezcla y sonoridad (medido)

| Vídeo | Sonoridad integrada | Rango (LRA) | Pico |
|---|---|---|---|
| `17kBVfGjI8c` | −14,9 LUFS | 6,0 LU | **−0,1 dBFS** |
| `rwF-X5STYks` | −17,5 LUFS | 8,8 LU | −2,0 dBFS |
| `KS837a-TFRc` | **−26,6 LUFS** | 12,3 LU | −1,5 dBFS |

- **Hecho:** no hay normalización de sonoridad. La voz se suma al fondo con
  `amix normalize=0` y los clips se recortan con `np.clip` (`mix.compose`).
- **Resultado:** casi 12 dB de diferencia entre vídeos, y un pico a −0,1 dBFS
  que roza el recorte (G-008).
- **Lo que funciona:** conservar la música con el fondo separado a 0 dB.

### 5.6 Subtítulos y reproducibilidad

- **SRT exportado:** sigue la voz que se oye (tiempos de la mezcla) en pantallas
  de 2 líneas.
- **Reproducibilidad:**
  - Semilla fija (`SEED = 0`) y caché de clips en bruto por hash: un doblaje
    repetido produce los mismos clips.
  - La traducción de Claude no es determinista, pero queda en caché por bloque.
  - El acortado no es determinista y no se guarda: rehacer el TTS puede decir
    distinto una frase acortada.

### 5.7 Varias voces (nuevo)

- **Probado en una entrevista real de 70 min:**
  - 3 hablantes.
  - Cortes de frase donde el texto dice que cambia la persona.
  - Ritmo por hablante: 17,9, 13,7 y 16,5 caracteres por segundo.
- **No se ha escuchado el resultado.** Las reasignaciones y fusiones desde la web
  solo están probadas en tests (G-009).

### 5.8 ¿Las métricas del bench predicen lo que se oye?

- **Lo que sí detectan** (`docs/bench`), como **filtros**:
  - El acento: `p_es` descartó Qwen3-TTS.
  - Las frases ininteligibles o desbocadas: CER.
  - El encaje en el hueco.
- **Lo que no deciden:**
  - La similitud ECAPA puntuó mejor a Qwen, rechazado de oído.
  - El temblor de 3–9 Hz varía ±0,03–0,05 solo con el texto y no es fiable;
    `v2-plan.md` ya concluye que "the ear is".
- **Conclusión:** sirven para descartar, no para ordenar candidatos. Además
  miden frases sueltas, no el doblaje final (mezcla, sincronía, sonoridad).

**Marco de evaluación repetible propuesto:**

1. **Corpus fijo** de 6–8 vídeos representativos, con su URL y segmento:
   - Hombre y mujer, con y sin música.
   - Uno largo (más de 45 min) y uno con varias voces.
   - Guardar sus `segments.json`, para que la traducción y el TTS partan de lo
     mismo.
2. **Métricas automáticas por doblaje**, a un fichero versionado como
   `bench/results`:
   - Encaje: acelerados, no caben, retrasos máximo y suma, acortados, edge-tts,
     CER del QC.
   - Sobre la pista final: sonoridad y pico.
   - CER y `p_es` de whisper sobre la pista doblada en segmentos.
   - Similitud de hablante como dato de contexto.
3. **Escucha humana breve y a ciegas:**
   - 10 fragmentos de 10–15 s por vídeo, dos versiones en orden aleatorio.
   - Notas 1–5 de naturalidad, fidelidad al sentido y sincronía, más una
     preferencia.
   - Guardar las notas junto a las métricas.
4. **Regla:** un cambio de motor, prompt o ajuste solo se da por bueno si no
   empeora las métricas filtro y gana o empata en la escucha.

## 6. Fortalezas a conservar

- **Caché por fase con hash de parámetros:** cambiar un parámetro rehace solo lo
  que depende de él; la traducción se reanuda por bloque (`workdir.py`,
  `translate.py`).
- **Ajuste de duración por capas, medido en benches:** factor nativo → acortar →
  bajo el suelo → atempo → retraso.
- **QC por clip con una cadena que no cambia de voz** salvo como último recurso,
  y todo queda registrado y visible en la web.
- **Motores pesados en venvs propios** con un protocolo JSON-lines común
  (`engines.py`): el venv principal no se contamina.
- **Versiones conservadas, comparación A/B, retoque en segundos y exportación**
  sin recodificar: un ciclo de revisión corto.
- **Decisiones documentadas con datos** (`v2-plan.md`, `docs/bench`): se puede
  reconstruir el porqué de cada elección.
- **Tests aislados de GPU y red** (`tests/conftest.py`) y una CI que comprueba
  también que el build del frontend está al día.

## Gaps (producto)

- **G-001** · YouTube puede bloquear la descarga y no hay alternativa ni mensaje accionable · observado el 2026-10-25 en `download.run` ("Sign in to confirm you're not a bot").
- **G-002** · No se puede cancelar un trabajo ni quitarlo de la cola · ausente en `web/jobs.py`, `app.py` y el frontend.
- **G-003** · No se puede borrar un vídeo ni limpiar sus intermedios desde la web · solo `DELETE /videos/{id}/outputs/{version}`.
- **G-004** · La fase de voz necesita red aunque el motor sea local · `asyncio.run(_check_voice(...))` en `tts.run` y `tts.retouch`.
- **G-005** · No se mide la pérdida de sentido al acortar ni la fidelidad de la traducción · `translate.shorten` sin comprobación posterior.
- **G-006** · Con una sola voz, la reserva edge-tts no respeta el sexo del hablante · `rwF-X5STYks` #11 dicha por `es-ES-AlvaroNeural`; `_repair_clones` usa `voices[i].stock or settings.voice`.
- **G-007** · No se mide la deriva acumulada entre voz e imagen · solo hay retrasos por clip en `overflow.log`.
- **G-008** · Sin normalización de sonoridad ni limitador · −14,9 a −26,6 LUFS entre vídeos; pico de −0,1 dBFS; `mix.filter_graph` con `normalize=0`.
- **G-009** · Varias voces validada en un solo vídeo real y sin escucha · §5.7.
- **G-010** · Mensajes de error y logs en inglés en la interfaz en español · `NowDubbing`, mensajes de `app.py`.
- **G-011** · El idioma por defecto de la interfaz es inglés · `prefs.tsx` `lang: "en"`.
- **G-012** · El diálogo de redoblaje no permite activar varias voces · `RedubDialog.tsx`.
- **G-013** · Controles por frase ocultos hasta pasar el ratón · `.add-term`, `.row-action` en `styles.css`.
- **G-014** · Motor por defecto distinto en la web (*Automático*) y en la CLI (Chatterbox) · `JobRequest.engine`, `prefs.tsx`, `Settings.engine`.
- **G-015** · El modelo de Chatterbox cargado (Multilingual V3) no coincide con el "afinado es-ES" del encargo · `clone._load`.
- **G-016** · No hay un corpus ni un protocolo de evaluación de doblajes completos; el bench mide frases sueltas · `docs/bench/README.md`.
- **G-017** · Funcionamiento en Apple Silicon y en CPU sin probar para la clonación · `clone._device` contempla `mps`; los venvs de motores fijan CUDA 12.8.
