# Auditoría 4 · Estado tras la ejecución 3

> Lo pendiente de aquí y el backlog de la auditoría 2 se ordenan en la segunda ronda
> del roadmap: [05-roadmap.md](05-roadmap.md) (T-26 a T-37).

Estado de `main` en `3d59f0b` (25 de octubre de 2026), después de ejecutar el
[roadmap](03-roadmap.md) completo. Cada gap se ha vuelto a comprobar contra el
código; los que siguen abiertos dicen qué falta y dónde.

## Resumen

- **Los 25 tickets están hechos**, cada uno con sus tests, una prueba con vídeos
  reales y su commit en `main`. La CI pasa: tests (Linux), lint (ruff y la lista
  de mypy), macOS con edge-tts y frontend.
- **Fuera del roadmap** también se hizo:
  - G-012: el diálogo de redoblaje permite activar varias voces.
  - `translate` y `tts` aceptan `--multi-speaker` como fases sueltas.
  - La CI de tests, que fallaba en GitHub desde T-06, vuelve a pasar.
- **Decisiones de las escuchas a ciegas** (detalle en
  [v2-plan.md](../v2-plan.md)):
  - Chatterbox V3 sigue de motor. El afinado es-ES queda solo en la CLI.
  - Varias voces va marcada por defecto en la web cuando Nemotron está
    instalado. En la CLI sigue siendo opcional.
- **Quedan abiertos:**
  - 5 gaps parciales: G-001, G-005, G-010, G-016 y G-024 (G-020 se cerró después, con el bloqueo de GPU).
  - 5 hallazgos nuevos, descritos más abajo.
  - Ninguno es P1.

## Tickets

| Ticket | Commit | Resultado |
|---|---|---|
| T-01 Reserva edge-tts del sexo del hablante | `caa351e` | Con una voz, la reserva usa la voz de stock del sexo del hablante |
| T-02 Chatterbox por defecto en la web | `a686137` | Mismo motor por defecto en la web y en la CLI |
| T-03 Mensajes claros sin red y con YouTube bloqueado | `6865d7d` | Comprobación de edge-tts con timeout (20 s), sondeo de Claude y mensajes de bloqueo y de red |
| T-04 Escrituras atómicas | `6828020` | Todo el estado JSON se escribe con `write_text_atomic` |
| T-05 Un proceso por vídeo | `5ce42e5` | Bloqueo `flock` por vídeo; la web responde 409 |
| T-06 Timeout de workers y cancelación | `ff1a103` | La cancelación surte efecto en 0,2 s; un worker colgado se reinicia una vez |
| T-07 Normalización de sonoridad | `652d926` | −16 LUFS en dos pasadas, techo de −2 dBTP |
| T-08 Borrar intermedios desde la web | `1d4fe26` | Página de almacenamiento por grupos; cada fase rehace lo que falte |
| T-09 Licencias y uso responsable | `0a472d3` | `LICENSE` MIT; el README recoge las licencias de los motores y el uso responsable |
| T-10 Revisiones de Hugging Face | `24d0023` | Cada motor descarga una revisión fija |
| T-11 Escucha a ciegas | `c778ffe` | `docs/bench/listening`: sesión, servidor y resumen |
| T-12 Métricas del doblaje final | `9e2ddbf` | `dub_metrics.py`: T-07 solo cambió la sonoridad (−26,6 → −16,3 LUFS) |
| T-13 Pérdida de sentido al acortar | `dc35739` | 2 de 58 frases acortadas pierden el sentido (3 %) |
| T-14 Varias voces | `417b398` | Escucha: 3,8 frente a 2,2; activada por defecto en la web |
| T-15 Test de extremo a extremo | `ecff5f3` | Cobertura: `cli.py` 79 %, `pipeline.py` 88 %. Encontró 2 fallos |
| T-16 macOS con edge-tts | `967c4f0` | Job de CI en `macos-latest` sin extras |
| T-17 ruff y mypy | `652e296` | ruff limpio; mypy con una lista que solo baja (hoy 36) |
| T-18 Tests de frontend | `17b42d9` | Vitest: 11 tests |
| T-19 Interfaz en español | `2ac6698` | La interfaz sigue el idioma del navegador; errores de la API con código; controles visibles; estado de carga |
| T-20 LAN con autenticación | `89733db` | `--lan` con token en enlace, cookie o bearer; sin token, 401 |
| T-21 `architecture.md` | `6561037` | Documento al día; revisado de nuevo con T-23 y T-24 |
| T-22 Biblioteca sin releer versiones | `0278122` | `/videos`: de 48 a 16 ms |
| T-23 Dividir `tts.py` | `10bab86` | `voices.py`, `repair.py` y `retouch.py`; contexto `Fitting` |
| T-24 Separación por trozos | `5c81570` | Pico de memoria de 6,9 a 3,8 GB con 19 min; ya no crece con la duración |
| T-25 Servicio systemd | `caff637` | Plantilla y documentación; no se instala |

## Estado de los gaps

| Gap | Estado | Cómo |
|---|---|---|
| G-001 Bloqueo de YouTube | **Parcial** | El mensaje explica la causa (T-03), pero no hay alternativa. Ver «Pendiente» |
| G-002 Cancelar trabajos | Cerrado | T-06 |
| G-003 Borrar intermedios | Cerrado | T-08 |
| G-004 Fallo sin red | Cerrado | T-03 |
| G-005 Pérdida de sentido y fidelidad | Cerrado | Acortado medido (T-13); fidelidad de la traducción completa medida (T-27): 0 de 281 frases pierden el sentido |
| G-006 Reserva del sexo | Cerrado | T-01 |
| G-007 Deriva voz-imagen | Cerrado | T-12 (voz con más de 0,5 s de retraso, por versión) |
| G-008 Sonoridad | Cerrado | T-07 |
| G-009 Varias voces sin validar | Cerrado | T-14 |
| G-010 Mensajes en inglés | **Parcial** | Los errores de la API ya se traducen (T-19), pero el error de una fase sigue llegando en inglés |
| G-011 Idioma por defecto | Cerrado | T-19 |
| G-012 Redoblaje sin varias voces | Cerrado | `3d59f0b` |
| G-013 Controles ocultos | Cerrado | T-19 |
| G-014 Motor por defecto en la web | Cerrado | T-02 |
| G-015 | Retirado | — |
| G-016 Corpus y protocolo | **Parcial** | Protocolo, script y corpus hechos (T-11, T-12). El motor *Automático* sigue sin datos para decidirse |
| G-017 Apple Silicon y CPU | Cerrado por decisión | El Mac solo tiene que funcionar con edge-tts (G-032) |
| G-018 Timeout de workers | Cerrado | T-06 |
| G-019 Escrituras atómicas | Cerrado | T-04 |
| G-020 CLI y web a la vez | Cerrado | El vídeo con T-05; la GPU con un bloqueo por máquina (`gpu.py`), hecho tras esta auditoría |
| G-021 Memoria de la separación | Cerrado | T-24 |
| G-022 Clips en bruto sin límite | Cerrado por decisión | Se borran a mano desde la web (T-08); P9 descarta el borrado automático |
| G-023 Biblioteca lenta | Cerrado | T-22 |
| G-024 ruff y mypy | **Parcial** | Están en la CI (T-17), pero quedan 36 errores de mypy en la lista |
| G-025 Test de extremo a extremo | Cerrado | T-15 |
| G-026 Tests de frontend | Cerrado | T-18 |
| G-027 Revisión de los pesos | Cerrado | T-10 |
| G-028 Consentimiento y derechos | Cerrado | T-09 |
| G-029 Licencia | Cerrado | T-09 |
| G-030 `tts.py` | Cerrado | T-23 (de 1.166 a 794 líneas) |
| G-031 `architecture.md` | Cerrado | T-21 |
| G-032 macOS con edge-tts | Cerrado | T-16 |
| G-033 Acceso desde la LAN | Cerrado | T-20 |

## Pendiente

Ordenado por prioridad. Cada punto dice qué falta, dónde está y qué se propone. Los
puntos que vienen de la [Auditoría 2](03-competencia.md#7-decisiones-del-propietario-2026-10-25)
lo indican.

### Requisito de entrada de la ejecución 3: cumplido (2026-10-25)

- **Escucha comparativa a ciegas**, hecha
  ([03-competencia.md §8](03-competencia.md#8-escucha-comparativa-2026-10-25)).
  - Fuentes: OpenDub, una réplica del enfoque de acelerar de Subtitle Edit y
    pyVideoTrans, y ElevenLabs Dubbing v2.
  - Resultado: OpenDub 3,7 de nota media, preferido 9 de 10; la réplica 2,9;
    ElevenLabs 2,0.
  - El lazo de calidad se oye, con los límites del §8: dos vídeos cortos, un oyente,
    la réplica no es el programa real.

### P2

1. **Errores de fase en inglés en la web** (resto de G-010).
   - **Qué falta:** cuando un doblaje falla, la web muestra «Falló: …» con el
     mensaje de la fase tal cual, en inglés. Por ejemplo, los `SystemExit` de
     `download.explain`, `translate`, `tts._check_voice` o el motor no instalado.
   - **Dónde:** `job.error` en `web/jobs.py`, mostrado con `job_failed` en
     `Library.tsx`.
   - **Propuesta:** dar código a los fallos de fase más comunes (bloqueo de
     YouTube, sin red, Claude inalcanzable, motor o diarizador no instalado,
     clips borrados), igual que la API con `fail()`. El texto técnico quedaría
     solo como detalle.
2. **Reducir la lista de mypy** (resto de G-024).
   - **Qué falta:** 36 errores, casi todos `Path | None` pasados donde se espera
     `Path` (referencias de voz) y tipos de `**dict` en `web/jobs.py`.
   - **Propuesta:** corregirlos por módulos. `tools/mypy_baseline.py --update`
     acorta la lista a medida que bajan.
3. **Fidelidad de la traducción completa** (resto de G-005).
   - **Qué falta:** T-13 mide lo que se pierde al acortar, no si la traducción
     completa dice lo mismo que el original.
   - **Propuesta:** el mismo juez de `shortening.py` (rúbrica fija, sin
     guardar frases), aplicado a original frente a traducción en una muestra por
     vídeo del corpus.

### P3

4. **Decidir el motor *Automático*** (resto de G-016).
   - **Qué falta:** sigue marcado como experimental hasta tener datos de 8–10
     vídeos.
   - **Propuesta:** ya existen las herramientas. Doblar el corpus con IndexTTS y
     con Chatterbox, pasar `dub_metrics.py` y una sesión de escucha, y decidir
     si el umbral de 165 Hz se sostiene.
5. **Alternativa al bloqueo de YouTube** (resto de G-001).
   - **Situación:** el bloqueo no se elude. yt-dlp puede usar las cookies del
     navegador del propio usuario (`--cookies-from-browser`). Eso no salta la
     comprobación: descarga como el usuario con su sesión.
   - **Decisión pendiente del propietario:** si se ofrece como opción
     documentada o se deja como está.
6. **LAN sin cifrar.**
   - **Qué pasa:** `--lan` sirve HTTP. Quien escuche la red local puede ver el
     token. Además, el token cambia en cada arranque, así que tras reiniciar
     cada dispositivo debe abrir el enlace nuevo; la cookie, de 30 días, ya no
     sirve.
   - **Propuesta:**
     - Documentar que es para redes de confianza.
     - Ofrecer un token persistente opcional (guardado en `~/.config/opendub`)
       para el servicio systemd.
7. **Varias voces en más casos.**
   - **Qué falta:** la validación con escucha se hizo con un pódcast de hombre y
     mujer. Faltan dos hombres de tono parecido y solapes reales, que en el
     bench solo se probaron con conversaciones sintéticas.
   - **Propuesta:** una sesión con un vídeo así antes de activarla también en la
     CLI.
8. **Afinado es-ES en la CLI.**
   - **Situación:** perdió la escucha (3,17 frente a 3,83) y sigue como
     `--engine chatterbox-es` solo para comparar. Mantenerlo cuesta un
     checkpoint más en caché (~3 GB).
   - **Decisión pendiente:** retirarlo o conservarlo como referencia.

### Backlog de la Auditoría 2

Se ordena en la ejecución 3, con el resultado de la escucha comparativa delante.

9. **Backend de traducción local en Ollama** (decisión del propietario).
   - Modelos candidatos: Gemma 3 27B o Qwen3-30B-A3B.
   - Validación: contra Sonnet en el corpus, con las métricas de longitud y encaje
     que ya existen (`dub_metrics.py`) y el juez de `shortening.py`.
   - Quita la dependencia de la suscripción. Mientras tanto, `--backend api` está
     documentado en el README.
10. **Revisar la traducción antes de sintetizar.** Una pausa opcional tras la
    traducción, como el *Proofread* de HeyGen o Vozo, para no gastar GPU en un vídeo
    largo mal traducido.
11. **Clonar con la voz de cada línea como referencia**, como Subtitle Edit o
    VoiceStudio. Da más expresividad y sirve de respaldo cuando falla la diarización.
12. **Importar y exportar subtítulos con hablante** (actor en ASS, `<v>` en WebVTT),
    para colaborar con Subtitle Edit en lugar de competir con él.

Descartado en la Auditoría 2: sincronización labial, más idiomas, y equipos, API,
cuentas o SaaS.

## Hallazgos de la ejecución

- **Las notas de la escucha.** En las dos sesiones cada fragmento recibió la
  misma nota en naturalidad, sentido y sincronía, así que en la práctica fue una
  nota global más una preferencia. Si se repite, conviene simplificar la página a
  esa nota más la preferencia, o pedir las tres solo cuando difieran.
- **Fallos que encontró el test de extremo a extremo** (T-15, corregidos):
  - Dos doblajes archivados en el mismo segundo pisaban la primera versión.
  - Una orden de fase retenía el bloqueo del vídeo hasta que terminaba el
    proceso, no la orden.
- **La CI rompió en silencio.** Desde T-02, los tests de cancelación usaban el
  motor por defecto sin el fixture que da por instalados los motores. En la CI
  no hay ninguno, así que fallaron en GitHub de T-06 a T-17 y pasaban en local.
  Corregido en `c0eeb1f`.
- **Fases sueltas sin varias voces.** `translate` y `tts` no aceptaban
  `--multi-speaker`. Fase a fase, un vídeo con varios hablantes se traducía y
  doblaba con una sola voz. Corregido en `f94def9`.
- **El enlace del token se cortaba.** Con `--lan`, el log de Rich partía el enlace
  en dos líneas y el token quedaba inservible. Ahora los enlaces se imprimen como
  líneas planas.
- **La separación no es determinista.** Dos pasadas de demucs sobre el mismo audio
  difieren (SNR de 29/23 dB) por sus desplazamientos aleatorios. Es la referencia
  con la que se aceptó la separación por trozos, que queda dentro de esa
  variación.
