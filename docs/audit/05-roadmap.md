# Auditoría 3 · Roadmap, segunda ronda

Plan de trabajo a partir de `main` del 2026-10-26 (`da69d80`). Toma como base:
- lo que quedó pendiente al ejecutar el primer roadmap
  ([04-estado.md](04-estado.md#pendiente));
- el backlog de la auditoría de competencia
  ([03-competencia.md](03-competencia.md#7-decisiones-del-propietario-2026-10-25));
- la escucha comparativa que era su requisito de entrada
  ([§8](03-competencia.md#8-escucha-comparativa-2026-10-25)).

El [primer roadmap](03-roadmap.md) (T-01 a T-25) está hecho; esta ronda sigue la
numeración desde T-26.

Antes de redactarlo se comprobó en el código que lo pendiente sigue abierto:
- el error de una fase llega a la web como texto en inglés (`JobManager._work` guarda
  `str(e)`, que se muestra con `job_failed`);
- la traducción solo tiene los backends `cli` y `api` (`translate._ask`);
- la lista de mypy tiene 36 errores (`mypy-baseline.txt`).

## Decisiones de partida

Estas decisiones son del propietario, todas del 2026-10-25:

- **Producto:** herramienta personal. El repositorio es público con MIT, pero sin
  soporte, instaladores ni compatibilidades.
  - El criterio del roadmap es la **calidad y el control** del doblaje de contenido
    técnico y educativo al español.
  - Se descarta lo que solo amplía (sincronización labial, más idiomas, equipos, API,
    SaaS).
  - Fuente: [03-competencia.md §5 y §7](03-competencia.md#5-recomendación).
- **La premisa está validada, con límites.** En la escucha a ciegas OpenDub sacó 3,7
  y fue preferido en 9 de 10 fragmentos. La réplica del enfoque de acelerar sacó 2,9 y
  ElevenLabs 2,0.
  - Límites: dos vídeos cortos de una voz y un solo oyente.
  - Por eso el roadmap sigue priorizando la calidad del lazo, no la edición.
- **Traducción:** dejar de depender de la suscripción de Claude con un backend local en
  Ollama (Gemma 3 27B o Qwen3-30B-A3B), validado contra Sonnet. Mientras tanto,
  `--backend api` está documentado.
- **Uso de vídeos y voces de terceros:** uso personal; no publicar doblajes con voces
  clonadas. Ya está en el README.
- **Siguen vigentes** las de la primera ronda: Chatterbox V3 por defecto; solo español;
  el Mac solo con edge-tts; la LAN siempre con autenticación.

**Leyenda:**
- Prioridad: **P1** (este ciclo), **P2** (después), **P3** (opcional).
- Tamaño: **S** (horas), **M** (una o dos sesiones), **L** (varias).

## Resumen

| Fase | Ticket | Prioridad | Tamaño | Origen |
|---|---|---|---|---|
| 1 · Medir lo que falta | T-26 Escucha comparativa en un vídeo largo con música y en uno de varias voces | P1 | M | §8 de la auditoría 2 |
| | T-27 Fidelidad de la traducción completa | P1 | S | G-005 |
| 2 · Traducir sin depender de la suscripción | T-28 Backend de traducción en Ollama (hecho) | P1 | L | Decisión 3 |
| | T-29 Revisar la traducción antes de sintetizar (hecho) | P2 | M | Backlog 10 |
| 3 · Calidad de voz | T-30 Clonar con la voz de cada frase (hecho: empate) | P2 | M | Backlog 11 |
| | T-31 Decidir el motor *Automático* (resuelto por T-38) | P3 | M | G-016 |
| 4 · Mantenimiento | T-32 Errores de fase con código, en español (hecho) | P2 | M | G-010 |
| | T-33 Reducir la lista de mypy (hecho) | P2 | S | G-024 |
| | T-34 Subtítulos con hablante (ASS y WebVTT) (hecho) | P3 | S | Backlog 12 |
| | T-35 LAN: redes de confianza y token persistente opcional (hecho) | P3 | S | Pendiente 6 |
| 1 · Medir lo que falta (nuevo) | T-36 Llenar el hueco cuando sobra (hecho: no se oye) | P1 | M | T-26 (§9 de la auditoría 2) |
| | T-37 Seguir el ritmo de quien habla (hecho: empate) | P1 | M | T-36 (§10 de la auditoría 2) |
| | T-38 El motor en una conversación (hecho) | P1 | M | T-37 (§11 de la auditoría 2) |

**Sin ticket, por ser decisiones del propietario:**
- Usuarios: se revisa tras T-26.
- ~~`--cookies-from-browser` ante el bloqueo de YouTube (G-001).~~ Hecho: opción documentada.
- Retirar o conservar el afinado es-ES en la CLI.
- Activar varias voces por defecto también en la CLI: se decide tras la parte de
  varias voces de T-26.

**Orden sugerido:**
1. Todos los tickets están hechos (T-31 lo resolvió T-38). Quedan las decisiones del
   propietario de arriba.
2. T-27 antes que T-28: su juez de fidelidad es lo que valida Ollama frente a Sonnet.
3. T-32 y T-33 cuando haya un hueco: no dependen de nada.

---

## Fase 1 · Medir lo que falta

### T-26 · Escucha comparativa en un vídeo largo con música y en uno de varias voces (P1, M)

- **Por qué:** el resultado del §8 sale de dos vídeos cortos de una sola voz. La
  decisión sobre usuarios, y la de activar varias voces en la CLI, necesitan saber si
  se sostiene donde OpenDub hace más trabajo.
- **Alcance:**
  - Dos sesiones con `docs/bench/listening`, las mismas tres fuentes y una nota global:
    - uno de los vídeos del corpus de 10–20 min con música (`VD6xJq8NguY`);
    - el pódcast de dos voces (`R4zlpwwEpnY`).
  - **Cómo caber en el plan gratuito de ElevenLabs** (unos 2.000 créditos por minuto y
    10.000 al mes):
    - doblar solo tramos de 2–3 min con `start_time`/`end_time` de su API;
    - limitar la sesión a esos tramos.
    - Hace falta que `elevenlabs_dub.py` acepte el tramo y que `session.py` elija
      fragmentos dentro de él.
  - **Réplica del enfoque de acelerar:**
    - En el pódcast tiene que usar una voz por hablante, igual que Subtitle Edit con
      *Find voices in video and clone*. Si no, la comparación castiga a la réplica por
      algo que el programa real sí hace.
    - Si esto no sale sencillo, se compara solo con ElevenLabs y se deja dicho.
- **Aceptación:**
  - Notas y preferencias guardadas en `results/`.
  - Una sección en `03-competencia.md` con el resultado y sus límites.
  - La decisión del propietario sobre usuarios, escrita.
- **Coste:** los créditos gratuitos de ElevenLabs de un mes; si no bastan, 1 $ por
  Starter.

### T-27 · Fidelidad de la traducción completa (P1, S)

- **Por qué:** T-13 midió lo que se pierde al **acortar**, pero no si la traducción
  completa dice lo que dice el original (resto de G-005). T-28 necesita esta medida para
  comparar un modelo local con Sonnet.
- **Alcance:**
  - Un juez con la rúbrica fija de `shortening.py`, aplicado a original frente a
    traducción: sentido conservado, matizado o perdido; terminología técnica correcta o
    no.
  - Muestra: todas las frases de los vídeos cortos y unas 60 de cada vídeo largo del
    corpus.
  - Solo medir: no cambia el prompt.
  - El modelo juez no debe ser el que tradujo; si es el mismo, se dice como límite.
- **Aceptación:**
  - `docs/bench/fidelity.py` y sus resultados por vídeo y por modelo traductor, sin
    frases, como `shortening.py`.
  - Una sección en `docs/bench/README.md`.

### T-36 · Llenar el hueco cuando sobra (P1, M)

- **Origen:** T-26
  ([03-competencia.md §9](03-competencia.md#9-escucha-comparativa-en-vídeos-más-difíciles-t-26-2026-10-26)).
  En el pódcast, el clon de una voz rápida acaba sus frases antes que el original y deja
  silencios en mitad de la conversación. Ahí OpenDub perdió frente a la réplica de
  acelerar.
- **Medida que falta:** cuánto del tiempo de habla del original llena la voz doblada.
  - Va por vídeo y por hablante en `dub_metrics.py`, junto a la deriva.
  - En el tramo del pódcast: el hablante A llena el 97 % y la hablante B el 77 %.
- **Opciones, a decidir con esa medida y una escucha:**
  1. **En la traducción:** pedir una longitud objetivo cercana al presupuesto (por
     ejemplo, el 85–100 %) y no solo un máximo, cuando el hablante habla más despacio
     que su clon.
  2. **En la voz:** permitir una ralentización ligera (`atempo` hasta 0,9) a un clip que
     cubra menos del 80 % de su hueco.
  3. **Las dos**, la 1 primero, por ser la que suena más natural.
- **Aceptación:**
  - En el pódcast, la voz B llena al menos el 90 % sin pasar del hueco.
  - Una sesión a ciegas frente a la versión actual en los tramos de T-26.
  - Los vídeos que ya llenaban (la música, la voz A) no empeoran en `dub_metrics.py`.
- **Antes de** decidir varias voces por defecto en la CLI.
- **Resultado (2026-10-26, [§10](03-competencia.md#10-llenar-el-hueco-y-lo-que-de-verdad-falla-en-el-pódcast-t-36-2026-10-26)):**
  - Queda la opción 2, decidida donde la mezcla colocará cada clip (`tts.fill_gaps`,
    `--min-tempo 0.9` por defecto). La 1 no llenaba y metía relleno.
  - B llena el 89 % (el 84 % en el tramo de la escucha). No llega al 90 %.
  - La música no empeora.
  - A ciegas no se distingue (igual en 14 de 15). La aceptación no se cumple: el hueco
    no era lo que se oía.

### T-37 · Seguir el ritmo de quien habla (P1, M)

- **Origen:** T-36 ([03-competencia.md §10](03-competencia.md#10-llenar-el-hueco-y-lo-que-de-verdad-falla-en-el-pódcast-t-36-2026-10-26)).
  En el pódcast «la traducción no acompaña a la persona que habla»:
  - las frases largas se cortan a los 12 s, a mitad de frase;
  - cada clip cierra la entonación donde se corta;
  - la voz no hace las pausas que hace el original.
- **Prueba:** cortar las frases largas por las pausas y comas del propio hablante, en
  trozos de hasta 6–7 s, en lugar de a los 12 s. Volver a traducir y doblar el pódcast.
- **Aceptación:**
  - Una sesión a ciegas frente a la versión actual en el tramo del pódcast, con la
    versión nueva preferida.
  - Ni el vídeo con música ni la fidelidad (T-27) empeoran.
- **Resultado (2026-10-26, [§11](03-competencia.md#11-cortar-las-frases-por-las-pausas-de-quien-habla-t-37-2026-10-26)):**
  empate (2,25 frente a 2,50, preferida 2 frente a 3). Mejora donde corta en una pausa
  real y empeora donde corta una coma sin pausa. Queda desactivado en el código
  (`split_pauses`).

### T-38 · El motor en una conversación (P1, M)

- **Origen:** T-37. Ni llenar el hueco ni cortar por las pausas mueven el pódcast de un
  2; queda la voz.
- **Prueba:** doblar el pódcast con IndexTTS-2.5 y con CosyVoice 3 (las frases de
  siempre, cada motor con su propia traducción a su ritmo) y una sesión a ciegas de tres
  frente a Chatterbox en el tramo de T-26.
- **Aceptación:** si un motor gana con claridad en conversación, decidir con T-31 cómo
  se elige (por tipo de vídeo, por voz o a mano). Si ninguno gana, el pódcast queda en
  el límite de los motores locales y se escribe.
- **Resultado (2026-10-26, [§12](03-competencia.md#12-el-motor-en-una-conversación-t-38-2026-10-26)):**
  CosyVoice gana la conversación (4,2 frente a 3,0 y 2,7) y Chatterbox la narración por
  poco (4,0 frente a 3,5). *Automático* pasa a ser CosyVoice con varias voces y
  Chatterbox con una, y es el motor por defecto (decisión del propietario).

## Fase 2 · Traducir sin depender de la suscripción

### T-28 · Backend de traducción en Ollama (P1, L)

- **Alcance:**
  - Un tercer backend, `--backend ollama`, con el mismo prompt y el mismo esquema JSON
    (la salida estructurada de Ollama). Lo usan la traducción, el acortado y la
    reescritura de la cadena de reservas.
  - Modelo configurable. Candidatos del propietario: Gemma 3 27B y Qwen3-30B-A3B.
- **Riesgo a resolver primero: la memoria.**
  - En la biblioteca de Ollama, Gemma 3 27B ocupa **17 GB** y Qwen3-30B-A3B **19 GB**,
    ambos en Q4_K_M (consultado el 2026-10-26). Ninguno cabe entero en los 16 GB de la
    5080: parte irá a la RAM, con 32 GB disponibles.
  - Qwen3-30B-A3B es de mezcla de expertos, con 3B activos, y suele tolerar mejor esa
    descarga a CPU.
  - Hay que medir la velocidad real en tokens por segundo con un bloque de 30 frases.
    Si es inaceptable, se añaden a la prueba modelos que caben: Gemma 3 12B (8,2 GB)
    o Qwen3 14B (9,3 GB).
- **Riesgo 2: competir por la GPU.**
  - La traducción ya corre dentro de `gpu.hold`.
  - Ollama mantiene el modelo cargado unos minutos tras usarlo. Hay que pedirle que lo
    descargue (`keep_alive: 0`) antes de soltar la GPU; si no, la fase de voz se queda
    sin memoria.
  - Va con test.
- **Validación contra Sonnet** en el corpus, como pidió el propietario:
  - métricas de longitud y encaje: frases por encima de su presupuesto, acortadas, que
    no caben, deriva (`dub_metrics.py`);
  - fidelidad con el juez de T-27;
  - tiempo por vídeo.
  - Si lo anterior no lo descarta, una escucha corta.
- **Aceptación:**
  - Con el backend elegido, los cortos y un largo se doblan sin errores.
  - El resultado frente a Sonnet queda escrito en `docs/bench/`.
  - El README explica cómo instalarlo y su coste en memoria.
  - Si ningún modelo local alcanza a Sonnet, se dice así y la API queda como
    alternativa.
- **Depende de:** T-27.

- **Resultado (2026-10-26, [docs/bench/README.md](../bench/README.md#local-translators)):**
  - `--backend ollama` traduce y acorta con el mismo prompt y esquema, y descarga el
    modelo de la GPU al acabar cada fase (también si falla), con test.
  - **Gemma 3 27B, descartado:** no cabe en la GPU (23 % en RAM), tarda doce veces más,
    traduce un 10 % más largo de lo que cabe y falló un bloque del pódcast.
  - **Qwen3.6-35B-A3B** (el que ya tenía el propietario, en lugar de Qwen3-30B-A3B, por
    espacio en disco): casi tan rápido como Sonnet; fidelidad 87 % frente a 96 %
    (7 frases pierden el sentido frente a 2, de 281); el doble de frases muy por encima
    del presupuesto. Doblado: los cortos sin errores (una frase que no cabe) y el vídeo
    con música con 168 s de voz a destiempo frente a 46 s.
  - Queda como modelo por defecto de `--backend ollama`; **Sonnet sigue siendo el
    traductor por defecto**. La web sigue con Claude (elegir backend en la web, si hace
    falta, va aparte).

### T-29 · Revisar la traducción antes de sintetizar (P2, M)

- **Por qué:** en un vídeo largo, una traducción mal orientada (un término, el
  registro) cuesta toda la fase de voz antes de verse. HeyGen y Vozo dejan revisar
  antes.
- **Alcance:**
  - Una opción por trabajo, «parar tras traducir», en la web y en la CLI (`--review`).
  - El trabajo queda en un estado «a revisar», se edita en el editor de siempre y se
    continúa desde la voz.
  - Sin cambios en la caché: la fase de voz ya parte de `translation.json`.
- **Aceptación:**
  - Un test de que la voz no empieza hasta continuar.
  - Una prueba en la web con un vídeo real.
- **Resultado (2026-10-26):**
  - `opendub dub --review` y, en la web, «Revisar la traducción antes» en el formulario.
    El trabajo para tras traducir (`pipeline.ReviewPending`) y queda «A revisar».
  - En la página del vídeo, un aviso con «Continuar el doblaje» y, al editar,
    «Guardar y continuar». Mientras se revisa no se ofrece regenerar sobre el doblaje
    anterior: la voz se hace entera, desde la traducción editada.
  - Test de extremo a extremo: la voz no empieza hasta continuar y dice la frase
    editada. Probado en la web con `rwF-X5STYks`: se paró, se corrigió una frase, se
    continuó sin volver a traducir y la versión nueva la dice corregida.

## Fase 3 · Calidad de voz

### T-30 · Clonar con la voz de cada frase (experimental, P2, M)

- **Por qué:** hoy cada hablante se clona de una sola referencia de 10–15 s. Subtitle
  Edit y VoiceStudio ofrecen usar como referencia la voz original de cada frase. Puede
  dar más expresividad (entonación de pregunta, énfasis) y sirve de respaldo donde la
  diarización se equivoca.
- **Riesgo:** con fragmentos cortos o con ruido, la clonación es menos estable. Por eso
  hay que medirlo, no suponerlo.
- **Alcance:**
  - Un modo experimental, `--clone-ref per-sentence`: usa la voz separada de la frase
    si dura lo bastante y está limpia, y si no, la referencia del hablante.
  - Tiene que pasar el mismo control de calidad y las mismas reservas.
- **Aceptación:**
  - Una sesión a ciegas frente al modo actual en el corpus, con la herramienta que ya
    existe.
  - Solo pasa a ser el modo por defecto si gana.
- **Depende de:** nada. Mejor después de T-26, que puede cambiar la prioridad.
- **Resultado (2026-10-26, [§13](03-competencia.md#13-clonar-con-la-voz-de-cada-frase-t-30-2026-10-26)):**
  `--ref-per-sentence` en `dub`, `tts` y `retouch`. A ciegas, empate en narración (3,50
  frente a 3,50) y ventaja pequeña en conversación (3,71 frente a 3,43). No gana con
  claridad: queda experimental, desactivado por defecto.

### T-31 · Decidir el motor *Automático* (P3, M)

- **Alcance:**
  - Doblar el corpus con IndexTTS y con Chatterbox, pasar `dub_metrics.py` y hacer una
    sesión a ciegas.
  - Decidir si el umbral de 165 Hz se sostiene, se cambia o se retira *Automático*.
- **Aceptación:** la decisión escrita en `v2-plan.md`, con sus datos (resto de G-016).

- **Resuelto (2026-10-26) por T-38:** *Automático* ya no mira el tono de la referencia:
  CosyVoice con varias voces, Chatterbox con una, y es el motor por defecto. Lo que
  queda de G-016 es confirmarlo con más vídeos.

## Fase 4 · Mantenimiento

### T-32 · Errores de fase con código, en español (P2, M)

- **Alcance:**
  - Los fallos de fase más comunes llevan código y parámetros, como los errores de la
    API con `fail()`, y la web los muestra traducidos con el texto técnico como detalle.
  - Los fallos son: bloqueo de YouTube, sin red, Claude u Ollama inalcanzable, motor o
    diarizador no instalado, y clips borrados.
  - En la CLI siguen saliendo en inglés.
- **Aceptación:**
  - Un test por código.
  - Con el navegador en español, un fallo provocado (red cortada) se lee en español.
- **Cierra:** G-010.
- **Resultado (2026-10-26):**
  - `errors.PhaseError`, un `SystemExit` con el mismo mensaje en inglés para la CLI y,
    además, código y parámetros: `youtube_blocked`, `youtube_unreachable`,
    `claude_unreachable`, `ollama_unreachable`, `engine_missing`, `diarizer_missing` y
    `clips_deleted`, lanzados donde ocurren.
  - El trabajo de la web los guarda (`job.json`, su evento de estado y el resumen del
    vídeo) y la página los dice en su idioma, con el texto en inglés como detalle.
  - Un test por código, en su sitio real, y otro de la web.
  - Probado con un segundo servidor sin salida a internet (un proxy inexistente): con
    la página en español, «Falló: No hay conexión con YouTube. ¿Hay internet?».

### T-33 · Reducir la lista de mypy (P2, S)

- **Alcance:** los 36 errores, por módulos. La mayoría son `Path | None` pasados donde
  se espera `Path` (las referencias de voz) y tipos de `**dict` en `web/jobs.py`. Cada
  corrección con su test si cambia el comportamiento.
- **Aceptación:** `mypy-baseline.txt` vacío, o con los que queden justificados uno a
  uno.
- **Cierra:** G-024.
- **Resultado (2026-10-26):** `mypy-baseline.txt` vacío. Casi todo eran anotaciones; donde
  la corrección toca el comportamiento hay test: una voz clonada siempre tiene referencia
  (`Voice.cloned_ref`), una entrada rara del manifiesto no cuenta como hecha, un modelo
  que solo devuelve la voz falla claro, y el volumen de la página va al fondo sobre el
  que se mezcla. Las tuberías del proceso de un motor se guardan al arrancarlo.

### T-34 · Subtítulos con hablante (P3, S)

- **Alcance:**
  - Exportar SRT y ASS con el hablante: `Actor` en ASS, `<v Nombre>` en WebVTT.
  - Importar una traducción corregida fuera, en esos formatos.
  - Sirve para corregir con un editor de subtítulos cuando el de la web se queda corto.
- **Aceptación:** ida y vuelta sin perder tiempos, textos ni hablantes, con test.
- **Resultado (2026-10-26):** `subs-export` (ASS con *Actor*, WebVTT con `<v Nombre>`, SRT
  sin hablante) y `subs-import`, y lo mismo en la página del vídeo. Una línea por frase
  con los tiempos del original; al importar, los textos entran como ediciones a mano y
  los nombres como hablantes, y un fichero que no encaja no guarda nada. Test de ida y
  vuelta en WebVTT y ASS (los tiempos de ASS, a la centésima del formato).

### T-35 · LAN: redes de confianza y token persistente opcional (P3, S)

- **Alcance:**
  - El README avisa de que `--lan` sirve HTTP y es para redes de confianza.
  - `--lan-token-file` guarda el token en `~/.config/opendub` para que el servicio
    systemd no lo cambie en cada arranque.
- **Aceptación:**
  - Con el token persistente, un enlace sigue valiendo tras reiniciar.
  - Sin la opción, todo funciona como hoy.
- **Resultado (2026-10-26):**
  - El README avisa de que `--lan` es HTTP sin cifrar, solo para redes de confianza, y
    recomienda una VPN para llegar desde fuera.
  - `--lan --keep-token` (un interruptor en lugar de `--lan-token-file`) guarda el
    token en `~/.config/opendub/lan-token` con permisos 600; borrarlo revoca los
    enlaces.
  - Tests: el token sigue igual tras reiniciar y sin la opción cambia en cada arranque.

---

## Lo que este roadmap no hace, y por qué

- **Sincronización labial, más idiomas, instaladores, Windows o Apple Silicon con
  clonación, equipos, API o SaaS:** quedan fuera por la decisión de producto (§5 de la
  auditoría 2).
- **Volver a abrir la elección de motor:** Chatterbox V3 se eligió de oído dos veces.
  T-31 solo decide *Automático*.
- **Una «réplica» que sustituya al programa real de Subtitle Edit:** T-26 reutiliza la
  réplica con sus límites declarados. Si algún día hace falta el programa real, habrá
  que manejar su interfaz a mano.
