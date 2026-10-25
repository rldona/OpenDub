# Auditoría 1 · Ingeniería

Arquitectura, fiabilidad, rendimiento, tests, seguridad y mantenibilidad de
OpenDub a 25 de octubre de 2026 (commit `9fe1fee`). El producto está en
[01-producto.md](01-producto.md), cuyos gaps llegan a G-017; aquí la numeración
continúa. Leyenda: **Hecho**, **Hipótesis**, **Pregunta**, como en el otro
documento.

## 1. Arquitectura

```
CLI (typer, cli.py) ─┐
                     ├─► pipeline.dub / pipeline.retouch ─► fases (un módulo cada una)
Web (FastAPI, web/) ─┘        │
  JobManager: 1 hilo,         ├─ download.py   yt-dlp → video.mp4, audio.wav, subs, meta.json
  cola en memoria,            ├─ separate.py   HTDemucs (torch | mlx) → stems/vocals, background
  job.json por vídeo          ├─ diarize.py    Nemotron 3 (venv propio, subproceso) → diarization.json
  eventos SSE (log.py)        ├─ transcribe.py subtítulos | faster-whisper → segments.json
                              ├─ translate.py  claude -p | API → translation.json (+ caché por bloque)
                              ├─ tts.py        edge-tts | Chatterbox (pool) | IndexTTS/CosyVoice (workers)
                              │                → tts/*.wav, tts.json, overflow.log
                              └─ mix.py        numpy + ffmpeg → output.mp4, outputs/<fecha>-<motor>.*
Frontend React 19 (frontend/) → build commiteado en src/opendub/web/static (servido por FastAPI)
```

- **Estado en disco, sin base de datos.** Todo vive en `work/<id>/`.
  `manifest.json` guarda por fase un hash de sus parámetros
  (`workdir.params_hash`). Rehacer una fase invalida las que dependen de ella
  según `workdir.DEPENDS`; `diarize` depende de `separate`, y `transcribe`
  registra en sus parámetros qué diarización usó.
- **Procesos hijos:** todos se lanzan por `media.popen`, sin shell y con lista
  de argumentos. Con el servidor web corren en otra sesión, para que un Ctrl+C no
  los mate a medias (`media.CHILD_SESSION`, `app.ExitGuard`).
- **Motores con dependencias incompatibles:** IndexTTS, CosyVoice y Nemotron van
  en venvs propios. `engines/<motor>/pyproject.toml` lleva su `uv.lock`, salvo
  IndexTTS, que usa el de su repo fijado a `REPO_REV`. Hablan JSON lines por
  stdin/stdout (`engines.Worker`); Chatterbox reutiliza el mismo protocolo para su
  pool de 2 procesos. Nemotron es un subproceso de una sola llamada
  (`workers/diarize_worker.py`).
- **Tamaño:** 5.933 líneas de Python en `src/opendub` y 2.749 de TypeScript en
  `frontend/src`. El módulo crítico es `tts.py` (1.128 líneas).

**Fortalezas a conservar:**
- El grafo de fases con caché por parámetros.
- El protocolo de workers común.
- La separación CLI/web sobre el mismo `pipeline`, porque la web no añade lógica
  a las fases.
- El frontend sin Node en tiempo de uso, con su comprobación en CI.

## 2. Fiabilidad

### 2.1 Fallos de correctitud

| Id | Fallo | Evidencia | Tipo |
|---|---|---|---|
| F1 | La reserva edge-tts de una sola voz ignora el sexo del hablante | `tts._repair_clones`: `voices[i].stock or settings.voice`; `rwF-X5STYks` #11 | Hecho (G-006) |
| F2 | La fase de voz falla sin red aunque el motor sea local | `tts.run` y `tts.retouch` llaman a `_check_voice` (`edge_tts.list_voices()`) antes de nada | Hecho en código; sin red no se ha ejecutado (G-004) |
| F3 | Un worker colgado bloquea el trabajo para siempre | `engines.Worker._read` hace `readline()` sin timeout; no hay cancelación | Hipótesis (G-018) |
| F4 | JSON a medio escribir si el proceso muere al guardar | `WorkDir._write`, `save_segments`, `tts.json` y `voice_rates.json` usan `write_text` directo; solo el MP4 y los wav pasan por `.part` → `replace` | Hipótesis (G-019) |
| F5 | La CLI y la web pueden trabajar a la vez sobre el mismo vídeo | No hay bloqueo de carpeta. El `JobManager` serializa solo los trabajos web, y la edición se bloquea con 409 solo si el trabajo activo es web | Hecho: ocurrió en esta sesión al lanzar doblajes por CLI con el servidor arrancado (G-020) |

Un detalle de diseño que no es fallo: en la web, el `job.json` recuerda las
opciones del último trabajo. Un retoque las reutiliza y un `POST /jobs` nunca
hereda el retoque, gracias al filtrado de `JobRequest`. Hay un test que lo
comprueba (`test_retouch_queues_a_job_with_the_last_options`).

### 2.2 Idempotencia, reanudación y caché

- **Hecho:** cada fase se salta si su hash coincide. La traducción se reanuda
  por bloque (`translate_blocks/blocks/<hash>.json`) y el TTS reutiliza los
  clips en bruto por hash de texto, voz, semilla y factor (`tts._raw_path`), así
  que un TTS interrumpido no vuelve a sintetizar lo ya hecho.
- **Hecho:** los trabajos que quedaron en cola o en marcha al parar el servidor
  se marcan como interrumpidos al arrancar (`JobManager._mark_interrupted`).
- **Hecho:** el acortado no se guarda en caché. Rehacer el TTS vuelve a llamar a
  Claude y puede decir distinto una frase que ya cabía.
- **Riesgo:** al invalidar desde `separate` no se invalida `transcribe` en el
  grafo. La transcripción solo se rehace porque sus parámetros incluyen el hash
  de la diarización. Es correcto, pero depende de una convención fuera de
  `DEPENDS`.

### 2.3 Servicios externos y timeouts

| Servicio | Uso | Timeout y reintentos | Fallo observado |
|---|---|---|---|
| YouTube (yt-dlp) | descarga, miniatura | los de yt-dlp | **Bloqueo antibots el 2026-10-25** en todas las descargas (G-001) |
| Claude (CLI `claude -p` o API) | traducir, acortar | 600 s por llamada, 3 intentos (`translate._ask`) | — |
| edge-tts (Microsoft) | voz de stock, reserva, `list_voices` | 3 intentos con espera (`_synthesize_all`); `list_voices` sin reintento | — |
| Hugging Face | pesos de modelos en la instalación | — | — |

### 2.4 GPU, memoria y disco

- **GPU (hecho):**
  - Un solo trabajo web a la vez.
  - Entre trabajos se liberan los workers, Chatterbox y la caché de CUDA
    (`pipeline.release_models`).
  - El pool de Chatterbox solo arranca con 12 GB o más de VRAM.
  - Nada impide lanzar a la vez un trabajo por CLI y otro por web (F5), con
    riesgo de quedarse sin memoria de GPU.
- **Memoria (hipótesis por cálculo):**
  - `separate._load` decodifica todo el audio a float32 estéreo de 44,1 kHz, que
    son 1,5 GB por hora y por pista; luego hay 4 stems en memoria.
  - Un vídeo de 70 min ronda 7–9 GB de pico. Uno de 3 horas podría no caber en
    32 GB (G-021).
- **Disco (hecho, medido):**
  - Clips en bruto acumulados sin límite: 1.241 ficheros (249 MB) para 199 frases
    en `KS837a-TFRc`.
  - Voces separadas en wav de 44,1 kHz: 1,4 GB para 70 min.
  - Unos 110 MB por versión guardada.
  - No hay limpieza (G-003, G-022).

### 2.5 Cancelación y muerte del proceso

- **Hecho:** sin cancelación de trabajos (G-002). Solo existe el doble Ctrl+C,
  que para el servidor y los hijos (`media.stop_children`).
- **Hecho:** si la app que lanzó el servidor se reinicia, el servidor muere. En
  esta sesión pasó varias veces y se perdieron procesos en segundo plano. No es
  un fallo de OpenDub, pero muestra que no hay ningún modo servicio.
- **Pregunta P6.**

## 3. Rendimiento

- **Dónde va el tiempo:** la voz es el 86 % (`v2-plan.md`, Fase D). Las mejoras
  ya hechas están medidas:
  - Acelerador de IndexTTS: 1,31×.
  - Pool de Chatterbox: 1,26×.
  - QC con decodificación greedy: la mitad de tiempo.
- **Entrevista de 70 min con varias voces y Chatterbox:**
  - Diarización: 8,7 s en el bench.
  - Traducción con calibración de 3 voces: 285 s.
  - Voz: 831 s.
  - Mezcla: 118 s.
- **Oportunidades** (sin medir; no son fallos):
  - La biblioteca: `videos.list_videos` lee el `tts.json` y el `overflow.log` de
    cada versión de cada vídeo en cada carga, porque `outputs()` llama a
    `issues()` por versión. Con muchas versiones crecerá linealmente (G-023).
  - La mezcla de 118 s para 70 min compone en numpy y recodifica el audio a AAC;
    no se ha perfilado.
  - Calibrar cada voz cuesta unos 8–9 s por hablante.

## 4. Tests y CI

### 4.1 Estado

- **Suite:** `uv run pytest`: 160 pasan y 1 se omite (smoke test con
  `OPENDUB_SMOKE`), en 2 s. Ningún test toca GPU, red ni motores reales:
  `tests/conftest.py` sustituye la síntesis real por una función que falla y
  aísla `work/style.json`.
- **CI** (`.github/workflows/ci.yml`):
  - Job de pytest con `--extra web` y ffmpeg.
  - Job de frontend: tipos, build y comprobación de que el build commiteado
    coincide.
  - Último run correcto. Reproducida en local con un venv limpio sin torch.
- **Cobertura por línea**, como orientación (78 % en total):

  | Módulo | Cobertura |
  |---|---|
  | `cli.py` | 0 % |
  | `download.py` | 32 % |
  | `pipeline.py` | 42 % |
  | `separate.py` | 53 % |
  | `clone.py` | 56 % |
  | `transcribe.py` | 58 % |
  | `mix.py` | 64 % |
  | `tts.py` | 84 % |
  | `translate.py` | 89 % |
  | `web/` | 90–95 % |

- **Hay tests de regresión de fallos ya vistos:**
  - Textos muy cortos ("Yo").
  - Fragmentos partidos por una pausa.
  - Orden de versiones en el mismo segundo, que falló en CI.
  - Pool con un solo clip.
  - Glosario, retoque y concordancia por hablante.
- **Calidad estática** (fuera de la CI):
  - `ruff`: 15 avisos, sin fallos reales (variables `l`, imports sin usar y
    anotaciones `Pace` sin importar que nunca se evalúan).
  - `mypy`: 47 errores en 14 ficheros, sobre todo `Optional` sin comprobar
    (`engines.Worker`) y anotaciones. No he encontrado ninguno que falle en
    ejecución (G-024).

### 4.2 Tests ausentes de más valor

1. **Extremo a extremo del pipeline sin red ni GPU.** Un vídeo sintético
   generado con ffmpeg, traducción falsa y una voz falsa que escribe wavs, y
   que llegue hasta `output.mp4`. Hoy `pipeline.py` está al 42 % y `cli.py` al
   0 % (G-025).
2. **Invariantes de mezcla con audio real:**
   - Un clip nunca solapa al siguiente.
   - La suma de retrasos se recupera en la siguiente pausa.
   - La pista dura lo mismo que el vídeo.
   - La sonoridad queda dentro de un rango, cuando exista normalización.
3. **Fallos parciales:** un `manifest.json` o `tts.json` truncado, un worker que
   muere o se cuelga, y un `edge_tts.list_voices` sin red (F2–F4).
4. **Frontend:** no hay ningún test (`package.json` sin script de test) (G-026).
   Los de más valor serían el cálculo de progreso y ETA de `job.tsx`, las
   diferencias de `Compare.tsx` y los estados de la barra de retoque.
5. **Una prueba de humo real y periódica de cada motor** con el smoke test
   existente (`OPENDUB_SMOKE`), al menos antes de cambiar pins.

## 5. Seguridad, privacidad y licencias

Solo amenazas realistas para una herramienta local de un usuario.

| Área | Estado | Evidencia |
|---|---|---|
| Exposición del servidor | Bien | Escucha en `127.0.0.1`; `TrustedHostMiddleware` frena el DNS rebinding |
| Peticiones desde otras webs (CSRF) | Bien (verificado) | Sonda con el cliente de tests: `POST /jobs` con `text/plain` o un formulario → 422; solo acepta JSON, que exige preflight, y no hay cabeceras CORS |
| Rutas | Bien | Ids validados con `[\w-]{11}` (`app.check_id`), versiones con `mix.VERSION`, clips con `\d{4}\.wav`, hablantes con `[A-H]` |
| Subprocesos | Bien | Listas de argumentos, sin `shell=True`. Una URL que no es de YouTube va a `yt_dlp.extract_info` (petición de red a cualquier sitio soportado por yt-dlp); riesgo bajo en local |
| Secretos | Bien | `ANTHROPIC_API_KEY` y `HF_TOKEN` en `.env` (ignorado por git); no se escriben en logs |
| Datos enviados fuera | Hecho | La transcripción va a Anthropic (traducir y acortar); los textos de la voz de stock y de la reserva, a Microsoft (edge-tts); la descarga, a YouTube |
| Cadena de suministro | Pa | `uv.lock` del proyecto y de CosyVoice y Nemotron; commits fijados de Chatterbox, IndexTTS, CosyVoice y NeMo. **Los pesos de Hugging Face no fijan revisión** (`snapshot_download` y `hf_hub_download` sin `revision`; Chatterbox con `from_pretrained`) (G-027) |
| Consentimiento y derechos | A | Ni el README ni la web mencionan el consentimiento para clonar una voz ni los derechos de los vídeos de origen. Solo `docs/bench/README.md` explica que el audio no se sube porque son voces de terceros. Chatterbox marca su salida con Perth (`clone.py`) (G-028) |
| Licencia del repositorio | A | El repo es **público** en GitHub y **no tiene `LICENSE`**: por defecto, todos los derechos reservados. **Pregunta P3** (G-029) |
| Licencias de motores (solo si se distribuye) | Hecho | Chatterbox: MIT. CosyVoice: Apache 2.0. IndexTTS: bilibili Model Use License (restrictiva, revocable). Nemotron: OpenMDW 1.1. edge-tts usa un servicio no oficial de Microsoft. Datos en `v2-plan.md` y `README.md` |

- **Logs y temporales:** los workers acumulan en `work/*.log` sin rotación
  (2,1 MB el mayor; no es un problema práctico). La diarización usa
  `tempfile.TemporaryDirectory`. Los medios quedan en `work/` indefinidamente
  (G-003).

## 6. Mantenibilidad y deuda técnica

- **`tts.py` (1.128 líneas) concentra demasiado:** calibración, ajuste nativo,
  acortado, QC y reparación, voces por hablante, retoque e informes.
  - Funciona y está bien cubierto (84 %).
  - Hay funciones con 7–9 parámetros que viajan juntos (`wd`, `clips`, `voices`,
    `slots`, `by_id`, `settings`, `only`, `fixed`) (G-030).
  - Hipótesis: separar retoque, voces y reparación lo haría más legible sin
    cambiar comportamiento. No es urgente.
- **Convenciones implícitas:**
  - Invalidaciones fuera de `DEPENDS` (§2.2).
  - Valores por defecto duplicados entre `Settings`, `JobOptions`, `JobRequest`
    y `prefs.tsx`, que ya divergen en el motor (G-014).
- **El build del frontend va commiteado:** es deliberado y está cubierto por la
  CI. El coste es un diff de assets en cada cambio de frontend.
- **Documentación:** buena y viva (`v2-plan.md`, `docs/bench`, README).
  `docs/architecture.md` no se ha revisado frente a lo añadido hoy (varias voces,
  exportación, retoque): **hipótesis** de que está desfasado (G-031).

## Preguntas para el propietario

- **P1** · ¿El modelo por defecto debe ser Chatterbox Multilingual V3 (el que se carga hoy y el que eligió `v2-plan.md`) o el afinado es-ES que cita el encargo?
- **P2** · ¿Qué motor por defecto quieres: Chatterbox (CLI) o *Automático* por tono (web)?
- **P3** · El repo es público y no tiene licencia: ¿debe seguir público? ¿Qué licencia, si alguna, mientras la distribución sigue abierta?
- **P4** · ¿Debe poder doblarse sin conexión cuando el motor es local? Hoy la fase de voz consulta edge-tts y la traducción necesita Claude.
- **P5** · ¿Qué duraciones y tamaño de biblioteca esperas: vídeos de más de 2 horas, cientos de vídeos? Decide la prioridad de memoria (G-021) y disco (G-022, G-023).
- **P6** · ¿Basta con arrancar `opendub web` a mano o quieres que corra como servicio y sobreviva a cerrar el terminal?
- **P7** · ¿Harías sesiones cortas de escucha a ciegas (unos 10 min por vídeo) para el marco de evaluación? ¿Qué vídeos formarían el corpus?
- **P8** · Varias voces ya existe aunque el encargo la situaba más adelante: ¿entra en el alcance de la ejecución 3?
- **P9** · ¿Política de disco: conservar todas las versiones para siempre? ¿Se pueden borrar las voces separadas y los clips en bruto de vídeos terminados?

## Gaps (ingeniería)

- **G-018** · Las peticiones a un worker no tienen timeout; un worker colgado bloquea el trabajo sin poder cancelarlo · `engines.Worker._read`.
- **G-019** · Escrituras no atómicas del estado (`manifest.json`, `translation.json`, `tts.json`, `voice_rates.json`) · `WorkDir._write`, `save_segments`, `tts.run`.
- **G-020** · Sin bloqueo entre la CLI y la web sobre el mismo vídeo ni sobre la GPU · ocurrió en esta sesión; `JobManager` solo serializa la web.
- **G-021** · La separación carga el audio entero en memoria; los vídeos muy largos pueden no caber · `separate._load`, estimación de 7–9 GB para 70 min.
- **G-022** · Los clips en bruto se acumulan sin límite · 1.241 ficheros para 199 frases en `KS837a-TFRc/tts/raw`.
- **G-023** · Cargar la biblioteca relee el estado de cada versión de cada vídeo · `videos.outputs` → `issues()` por versión.
- **G-024** · `ruff` y `mypy` no están en la CI (15 y 47 avisos) · salidas de esta auditoría.
- **G-025** · Sin test de extremo a extremo; `cli.py` al 0 % y `pipeline.py` al 42 % · cobertura de esta auditoría.
- **G-026** · El frontend no tiene tests · `frontend/package.json`.
- **G-027** · Los pesos de los modelos no fijan revisión de Hugging Face · `indextts.setup`, `cosyvoice.setup`, `diarize.setup`, `clone._load`.
- **G-028** · Sin aviso de consentimiento de clonación ni de derechos del material de origen · README y web.
- **G-029** · Repo público sin `LICENSE` · raíz del repositorio.
- **G-030** · `tts.py` concentra demasiadas responsabilidades, con funciones de muchos parámetros · 1.128 líneas.
- **G-031** · `docs/architecture.md` probablemente desfasado frente a varias voces, retoque y exportación · no revisado.
