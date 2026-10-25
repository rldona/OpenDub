# Auditoría 3 · Roadmap

Plan de trabajo a partir del estado actual de `main` (`cb27106`), no de la
foto de la ejecución 1.

Antes de redactarlo se comprobó en el código que cada gap sigue abierto. Por
ejemplo:
- La reserva de voz de stock usa `voices[i].stock or settings.voice`.
- La web arranca con `engine = "auto"`.
- `_check_voice` se llama en `tts.run` y en `tts.retouch`.
- `engines.Worker._read` no tiene timeout.
- La mezcla usa `amix normalize=0`.
- No hay cancelación, ni `LICENSE`, ni `revision` en las descargas de pesos.

Los gaps G-xxx y las decisiones P1–P9 están en [01-producto.md](01-producto.md)
y [02-ingenieria.md](02-ingenieria.md#respuestas-del-propietario-2026-10-25).

## Decisiones de partida

- **Ámbito:** español; vídeos de 20–30 min como caso habitual y 60 min como
  máximo; biblioteca de decenas de vídeos. El disco importa antes que la memoria.
- **Motor:** Chatterbox Multilingual V3 fijo por defecto. *Automático* espera a
  tener datos de 8–10 vídeos. El afinado es-ES solo entra como variante en la
  escucha a ciegas.
- **Sin conexión** no es requisito, pero todo fallo de red debe dar un mensaje
  claro.
- **Repo** público, con MIT solo para el código de OpenDub. Distribuir
  (empaquetado, soporte) queda fuera.
- **Varias voces:** congelada como experimental. Un solo ticket en la fase 3 y
  sus defectos en P2 como máximo.
- **Mac:** solo tiene que seguir funcionando el modo edge-tts sin separación.
- **LAN:** P2, y siempre con autenticación.
- **Flujo de cada ticket:**
  1. Propuesta.
  2. Implementación.
  3. Prueba con vídeos reales: `17kBVfGjI8c` (voz masculina), `rwF-X5STYks`
     (voz femenina) y uno largo.
  4. Commit con la autoría del propietario.

**Leyenda:**
- Prioridad: **P1** (hacer en este ciclo), **P2** (después), **P3** (opcional).
- Tamaño: **S** (horas), **M** (una o dos sesiones), **L** (varias).

## Resumen

| Fase | Ticket | Prioridad | Tamaño | Gaps |
|---|---|---|---|---|
| 1 · Defectos y errores claros | T-01 Reserva edge-tts del sexo del hablante | P1 | S | G-006 |
| | T-02 Chatterbox por defecto también en la web | P1 | S | G-014 |
| | T-03 Mensajes claros sin red y con YouTube bloqueado | P1 | S | G-001, G-004 |
| | T-04 Escrituras atómicas del estado | P1 | S | G-019 |
| | T-05 Un solo proceso por vídeo (CLI y web) | P1 | S | G-020 |
| | T-06 Timeout de los workers y cancelación de trabajos | P1 | M | G-018, G-002 |
| | T-07 Normalización de sonoridad | P1 | M | G-008 |
| 2 · Disco, licencias y suministro | T-08 Borrar intermedios por vídeo desde la web | P1 | M | G-003, G-022 |
| | T-09 Licencia MIT, licencias de motores y uso responsable | P1 | S | G-029, G-028 |
| | T-10 Fijar la revisión de los pesos de Hugging Face | P2 | S | G-027 |
| 3 · Calidad medida | T-11 Sesión de escucha a ciegas con su script | P1 | M | G-016 |
| | T-12 Métricas del doblaje final | P1 | M | G-007, G-016 |
| | T-13 Medir la pérdida de sentido al acortar | P2 | S | G-005 |
| | T-14 Varias voces: validación y decisión | P2 | M | G-009 (G-012) |
| 4 · Mantenibilidad, UX y acceso | T-15 Test de extremo a extremo sin red ni GPU | P2 | M | G-025 |
| | T-16 Modo edge sin separación comprobado en macOS | P2 | S | G-032 |
| | T-17 ruff y mypy en la CI | P2 | S | G-024 |
| | T-18 Tests mínimos de frontend | P2 | M | G-026 |
| | T-19 Interfaz en español y controles visibles | P2 | M | G-010, G-011, G-013 |
| | T-20 Acceso desde la LAN con autenticación | P2 | M | G-033 |
| | T-21 Actualizar `docs/architecture.md` | P2 | S | G-031 |
| | T-22 Biblioteca sin releer cada versión | P3 | S | G-023 |
| | T-23 Dividir `tts.py` | P3 | M | G-030 |
| | T-24 Separación sin cargar todo el audio | P3 | M | G-021 |
| | T-25 Servicio systemd opcional | P3 | S | (P6) |

**Sin ticket:**
- G-015 está retirado.
- G-017 queda cerrado por la decisión sobre el Mac; su parte pendiente es G-032.
- G-012 queda registrado en P2 dentro de la congelación de varias voces; se
  revisa en T-14.

**Orden sugerido:**
1. T-01, T-02, T-03 y T-04: rápidos y corrigen defectos visibles.
2. T-05 y T-06: dependen de T-04 para escribir el estado sin corromperlo.
3. T-08, que usa T-05 para no borrar mientras se dobla.
4. T-11 y T-12 antes de T-07, para medir la sonoridad y escucharla con la
   herramienta propia.
5. T-15 antes de T-23, como red de seguridad del refactor.

---

## Fase 1 · Defectos y errores claros

### T-01 · La reserva edge-tts respeta el sexo del hablante (P1, S)

- **Problema:** con una sola voz, el último recurso del control de calidad dice
  la frase con `settings.voice` (Álvaro, masculina) aunque la hablante sea
  mujer. Ejemplo: `rwF-X5STYks` #11.
- **Alcance:**
  - En `tts._voices` (rama de una voz), dar a la voz clonada su `stock` y su
    `gender` a partir del tono de la referencia (`gender_of(mean_f0(ref))`), con
    `stock_voice(settings.voice, gender)`.
  - La cadena de reparación ya usa `voices[i].stock`.
- **Aceptación:**
  - Un test de una sola voz con referencia aguda termina en `es-ES-ElviraNeural`.
  - Con referencia grave, en la voz elegida.
  - Si el tono no se puede medir, se mantiene el comportamiento actual.
- **Prueba real:** retocar `rwF-X5STYks` #11 forzando la reserva (otra toma) y
  comprobar la voz en `tts.json` y de oído.

### T-02 · Chatterbox por defecto también en la web (P1, S)

- **Problema:** la web arranca en *Automático* (regla de tono con dos muestras)
  y la CLI en Chatterbox.
- **Alcance:**
  - `JobRequest.engine`, `JobOptions.engine` y `prefs.tsx` pasan a Chatterbox.
  - *Automático* sigue disponible como opción, con la nota de que es
    experimental.
  - Las preferencias guardadas que ya digan "auto" se respetan: solo cambia el
    valor por defecto.
- **Aceptación:**
  - Un `POST /jobs` sin motor usa Chatterbox.
  - Un navegador sin preferencias muestra Chatterbox seleccionado.
  - Tests web actualizados.

### T-03 · Mensajes claros sin red y con YouTube bloqueado (P1, S)

- **Problema:** sin conexión, la fase de voz falla en `edge_tts.list_voices()`
  con una traza. Si YouTube pide verificación, el usuario ve el volcado de
  yt-dlp.
- **Alcance:**
  - Capturar los fallos de red en `_check_voice`, en la descarga y en la
    traducción (CLI y API), y terminar con `SystemExit` y un mensaje que diga qué
    servicio falló y qué hacer.
  - La comprobación de voces no reintenta indefinidamente.
  - Reconocer el "Sign in to confirm you're not a bot" de YouTube y explicarlo:
    es un bloqueo temporal de YouTube y conviene esperar.
  - Cualquier vía para sortearlo, como usar las cookies del propio navegador
    del usuario con yt-dlp, es una **decisión del propietario**. Este ticket no
    la implementa.
- **Aceptación:**
  - Tests que simulan cada fallo de red y comprueban el mensaje.
  - En la web, el mensaje aparece como error del trabajo, sin traza.
- **Prueba real:** cortar la red y lanzar un doblaje con caché hasta la
  traducción.

### T-04 · Escrituras atómicas del estado (P1, S)

- **Problema:** `manifest.json`, `translation.json`, `tts.json`,
  `voice_rates.json` y `job.json` se escriben directamente. Un proceso muerto
  a mitad deja un JSON truncado y la siguiente ejecución falla.
- **Alcance:** un helper `write_json_atomic` (fichero temporal en el mismo
  directorio y `os.replace`), usado en `WorkDir._write`, `save_segments`,
  `tts.run`, `tts.retouch`, la caché de ritmos y `JobManager._save`.
- **Aceptación:**
  - Un test que interrumpe la escritura (monkeypatch que falla tras el
    temporal) y comprueba que el fichero anterior sigue intacto.
  - `grep` sin `write_text(json.dumps` en el estado de `work/`.

### T-05 · Un solo proceso por vídeo, CLI y web (P1, S)

- **Problema:** la CLI y la web pueden doblar a la vez el mismo vídeo, o dos
  vídeos que compiten por la GPU. Pasó durante la auditoría.
- **Alcance:**
  - Un candado por vídeo (`work/<id>/.lock` con `fcntl.flock`) que toman
    `pipeline.dub` y `pipeline.retouch`. El segundo proceso termina con un
    mensaje que dice quién lo tiene.
  - En la web, los endpoints de edición devuelven 409 también cuando el candado
    lo tiene la CLI.
  - Opcional, a decidir en la propuesta: un candado global de GPU que serialice
    la CLI con la web.
  - En Linux y macOS basta `fcntl`; Windows no es objetivo.
- **Aceptación:**
  - Un test con dos procesos sobre el mismo vídeo: el segundo falla en el acto
    con el mensaje.
  - Un test web que, con el candado tomado por otro proceso, recibe 409.

### T-06 · Timeout de los workers y cancelación de trabajos (P1, M)

- **Problema:** un worker colgado bloquea la cola para siempre, y no hay forma
  de parar un trabajo salvo matar el servidor.
- **Alcance:**
  - **Timeout por petición en `engines.Worker`**, con un límite generoso
    proporcional a la longitud del texto. Al vencer, el worker se mata y se
    relanza una vez; si vuelve a fallar, el clip cuenta como fallo del control de
    calidad y su cadena sigue.
  - **`POST /jobs/{id}/cancel`:**
    - Un trabajo en cola se quita.
    - Uno en marcha para sus hijos (`media.stop_children` acotado a ese
      trabajo), queda como `cancelled` y libera los modelos.
  - **Botón "Cancelar"** en "Doblando ahora", con confirmación.
  - **Conservar lo hecho:** la caché por fase y los clips en bruto se mantienen,
    así que relanzar continúa donde se quedó.
- **Aceptación:**
  - Test de un worker falso que no responde: el clip se marca como fallido en
    el tiempo previsto.
  - Test de cancelación en cola y en marcha, con estado final, SSE `end` y sin
    procesos huérfanos.
- **Prueba real:** cancelar a mitad de la fase de voz del vídeo largo y
  relanzar: no se repite lo ya sintetizado.
- **Depende de:** T-04.

### T-07 · Normalización de sonoridad (P1, M)

- **Problema:** de −14,9 a −26,6 LUFS entre vídeos, con un pico a −0,1 dBFS.
- **Alcance:**
  - En `mix.run`, una pasada de medida (`loudnorm` con `print_format=json`) y
    otra de aplicación lineal a un objetivo (−16 LUFS, por definir en la
    propuesta) con techo de pico real a −1,5 dBTP.
  - Configurable con `--loudness`, y desactivable.
  - Añadir el objetivo a los parámetros de la mezcla, para que las versiones
    nuevas se rehagan.
- **Aceptación:**
  - Los tres vídeos medidos quedan a ±1 LU del objetivo y sin pico por encima
    del techo.
  - Un test con audio sintético (tono a −30 LUFS) termina dentro del margen.
- **Prueba real:** los tres vídeos, comparando antes y después con la
  herramienta de T-11.
- **Depende de:** T-11 y T-12 para medir y escuchar.

## Fase 2 · Disco, licencias y suministro

### T-08 · Borrar intermedios pesados por vídeo desde la web (P1, M)

- **Problema:** cada vídeo acumula gigas que no se pueden limpiar desde la web.
  Por ejemplo, 1.241 clips en bruto para 199 frases, o 1,4 GB de voces separadas
  en 70 min.
- **Alcance**, según la política P9:
  - **Se conserva siempre:** `outputs/*.mp4`, `translation.json`, `tts.json` y
    `segments.json`.
  - **Borrable por vídeo:**
    - `video.mp4` y `audio.wav` (se repite la descarga).
    - `stems/` (se repite la separación, y antes de un TTS clonado o de un
      retoque).
    - `tts/raw` y `tts/*.wav` (no se puede retocar sin rehacer la voz).
  - **Endpoints:**
    - `GET /videos/{id}/storage`: tamaño de cada grupo, qué se pierde y qué
      fases habría que repetir.
    - `DELETE` por grupo, que invalida las fases afectadas en `manifest.json`.
  - **En la web:** una sección "Espacio" en la página del vídeo, con el aviso
    antes de borrar.
  - **Limpieza de clips huérfanos:** quitar los clips en bruto que no usa
    ninguna versión conservada.
  - **Sin borrado automático.**
- **Aceptación:**
  - Tests de que cada borrado invalida justo las fases previstas.
  - Las versiones siguen reproduciéndose y exportándose tras borrar
    intermedios.
  - Un doblaje posterior repite solo lo anunciado.
- **Prueba real:** `KS837a-TFRc`, antes y después, con espacio recuperado y un
  retoque posterior que avisa de que hay que rehacer la voz.
- **Depende de:** T-05, para no borrar mientras se dobla.

### T-09 · Licencia MIT, licencias de motores y uso responsable (P1, S)

- **Alcance:**
  - Un `LICENSE` MIT que cubre solo el código de OpenDub.
  - Una sección "Licencias" en el README:
    - Cada motor con su licencia y dónde vive (su venv).
    - Que los pesos no se distribuyen con el repo.
    - Que edge-tts usa un servicio de Microsoft.
  - Una nota de uso responsable: clonar solo con permiso de la persona y
    respetar los derechos de los vídeos de origen.
- **Aceptación:** existen `LICENSE` y las dos secciones; `pyproject.toml` declara
  `license = "MIT"`.

### T-10 · Fijar la revisión de los pesos de Hugging Face (P2, S)

- **Alcance:**
  - Pasar `revision=<commit>` en `indextts.setup`, `cosyvoice.setup` y
    `diarize.setup`, y el equivalente en Chatterbox.
  - Si `from_pretrained` no lo admite, descargar con `snapshot_download` a una
    carpeta propia y cargar con `from_local`.
- **Aceptación:**
  - Constantes `HF_REV` junto a `REPO_REV`.
  - Una instalación nueva descarga exactamente esos commits.

## Fase 3 · Calidad medida

### T-11 · Sesión de escucha a ciegas con su script (P1, M)

- **Problema:** las métricas del bench filtran, pero no ordenan, y no miden el
  doblaje final. Las decisiones se toman de oído, sin registro repetible.
- **Alcance:**
  - **`docs/bench/listening/session.py`:** a partir de dos versiones de los
    mismos vídeos (dos motores, o Chatterbox V3 frente al afinado es-ES), elige
    10–12 fragmentos de 10–15 s.
  - **Página local de escucha** (como la de etiquetado de la diarización):
    - Reparte A/B al azar con semilla fija, igualando la sonoridad de cada par.
    - Pide notas 1–5 de naturalidad, fidelidad y sincronía, más una preferencia.
    - Guarda las respuestas en un JSON y solo revela qué era cada versión al
      terminar.
  - **`summary.py`:** agrega las sesiones.
  - **Corpus:**
    - `17kBVfGjI8c` y `rwF-X5STYks`.
    - Dos vídeos nuevos de 10–20 min, uno con música de fondo y otro con un
      hablante rápido. Los propone el implementador al empezar el ticket, porque
      la descarga depende de que YouTube no esté bloqueando.
  - **Resultados:** las respuestas se commitean, el audio no.
- **Aceptación:**
  - Una sesión se regenera idéntica desde su semilla.
  - El JSON de respuestas incluye vídeo, fragmento, versión oculta, notas y
    preferencia.
  - La primera sesión real compara Chatterbox V3 con el afinado es-ES.

### T-12 · Métricas del doblaje final (P1, M)

- **Alcance:** un script (y opcionalmente una vista en Comparar) que, por
  versión, guarde:
  - **Encaje:** acelerados, no caben, acortados, edge-tts.
  - **Retrasos y deriva:** retraso máximo y medio, y el tiempo con voz tardía
    más de 0,5 s, a partir de `mix.place`.
  - **Pista final:** sonoridad y pico.
  - **Inteligibilidad:** CER y `p_es` de whisper sobre la pista doblada, por
    frases.
  - **Salida:** un JSON versionado junto a los resultados del bench.
- **Aceptación:**
  - Las métricas de los dos vídeos cortos y del largo quedan guardadas y se
    regeneran con un comando.
  - Un cambio de mezcla (T-07) se ve en la sonoridad y no empeora el resto.

### T-13 · Medir la pérdida de sentido al acortar (P2, S)

- **Alcance:**
  - Para las frases acortadas del corpus, comparar la traducción completa con
    la acortada, mediante retrotraducción o un juez con Claude con una rúbrica
    fija: sentido conservado, matizado o perdido.
  - Informe de la proporción.
  - **Solo medir;** cualquier cambio de prompt se decide con ese dato.
- **Aceptación:** informe en `docs/bench/` con la proporción por motor y
  ejemplos.

### T-14 · Varias voces: validación y decisión de activarla (P2, M)

- **Alcance**, el único ticket de varias voces del ciclo:
  - Un vídeo real de dos hablantes, distinto de la entrevista ya probada.
  - Doblaje con `--multi-speaker` y sesión de escucha con T-11.
  - Decidir si se activa por defecto.
  - Revisar los defectos registrados (G-009, G-012) **sin subirlos de P2**.
  - No se amplía la función.
- **Aceptación:** una decisión escrita en `v2-plan.md`, con los datos de la
  sesión.
- **Depende de:** T-11.

## Fase 4 · Mantenibilidad, UX y acceso

### T-15 · Test de extremo a extremo sin red ni GPU (P2, M)

- **Alcance:**
  - Un vídeo sintético generado con ffmpeg (tono y color), subtítulos VTT
    locales, traducción falsa y una voz falsa que escribe wavs.
  - `pipeline.dub` llega hasta `output.mp4`, la versión guardada y la
    exportación.
  - Cubre también la CLI (`typer.testing.CliRunner`).
- **Aceptación:**
  - Pasa en la CI en menos de 30 s.
  - `pipeline.py` y `cli.py` quedan cubiertos por encima del 70 %.

### T-16 · Modo edge sin separación comprobado en macOS (P2, S)

- **Alcance:** un job de CI en `macos-latest`, sin los extras `separate` ni
  `clone`, que pase el test de T-15 en modo edge (sin separación).
- **Aceptación:** el job pasa y falla si una importación de torch se cuela en
  ese camino.
- **Depende de:** T-15.

### T-17 · ruff y mypy en la CI (P2, S)

- **Alcance:**
  - Configurar ruff y mypy en `pyproject.toml` y corregir los 15 avisos de ruff.
  - mypy empieza en modo informativo o con una lista de excepciones, y la lista
    se va reduciendo.
- **Aceptación:** la CI falla con avisos nuevos de ruff, y mypy no crece.

### T-18 · Tests mínimos de frontend (P2, M)

- **Alcance:** Vitest para la lógica pura:
  - Progreso y ETA de `job.tsx`.
  - Las diferencias de `Compare.tsx`.
  - `issueText`.
  - Los estados de la barra de retoque.
  - Sin e2e de navegador en este ciclo.
- **Aceptación:** `npm test` en la CI.

### T-19 · Interfaz en español y controles visibles (P2, M)

- **Alcance:**
  - El idioma por defecto sigue al navegador (`navigator.language`), con el
    español como opción.
  - Los errores de la API llevan un código traducible, y la web muestra el texto
    técnico solo como detalle.
  - "+ glosario" y "otra toma" llevan una pista visible: icono atenuado en lugar
    de opacidad 0.
  - Estado de carga reconocible en lugar de "…".
- **Aceptación:**
  - Con el navegador en español no aparece texto en inglés salvo en el log
    técnico.
  - Revisión manual de cada página.

### T-20 · Acceso desde la LAN con autenticación (P2, M)

- **Alcance:**
  - Un `opendub web --host 0.0.0.0` (o `--lan`) que exige autenticación simple:
    un token generado y mostrado en el terminal, que va en la URL y luego en una
    cookie; o usuario y contraseña locales.
  - `allowed_hosts` se amplía solo en ese modo.
  - Sin modo abierto sin autenticación.
- **Aceptación:**
  - Tests de que sin token todo devuelve 401, salvo la página de entrada.
  - El modo local sigue igual.

### T-21 · Actualizar `docs/architecture.md` (P2, S)

- **Alcance:** incluir varias voces, retoque, exportación, estilo y glosario.
  Revisar cada diagrama contra el código actual.

### T-22 · Biblioteca sin releer cada versión (P3, S)

- **Alcance:** caché en memoria por `mtime` de los `tts.json` y `overflow.log`
  de cada versión en `videos.outputs`, o un resumen escrito al archivar la
  versión.

### T-23 · Dividir `tts.py` (P3, M)

- **Alcance:**
  - Sacar las voces por hablante, la reparación y el retoque a módulos propios.
  - Agrupar los parámetros que viajan juntos en un contexto.
  - Sin cambios de comportamiento.
- **Depende de:** T-15, como red de seguridad.

### T-24 · Separación sin cargar todo el audio (P3, M)

- **Alcance:** separar por trozos con solape y guardar los stems en streaming.
  Con 60 min de máximo no es urgente.

### T-25 · Servicio systemd opcional (P3, S)

- **Alcance:** una unidad de usuario documentada (`systemctl --user`) para que
  `opendub web` arranque solo. Opcional según P6.
