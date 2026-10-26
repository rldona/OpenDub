# Auditoría 2 · Competencia y posicionamiento

Comparativa de OpenDub con las alternativas que existen a 25 de octubre de 2026 y una
recomendación de posicionamiento. Lo que OpenDub hace hoy está verificado en
[01-producto.md](01-producto.md), [02-ingenieria.md](02-ingenieria.md) y
[04-estado.md](04-estado.md); aquí no se repite.

## Método

- **Fuentes primarias**, todas consultadas el **2026-10-25** salvo que se indique otra
  fecha:
  - documentación oficial, páginas de precios y términos;
  - repositorios con su `LICENSE`;
  - la API de GitHub para estrellas y fechas;
  - fichas de modelos en Hugging Face.
- **Afirmaciones del fabricante:** las de marketing («calidad de estudio», «perfectly
  aligned») se citan como afirmaciones, no como hechos.
- **Datos no verificados:** lo que no se pudo comprobar figura como **no encontrado**.
- **Comprobaciones a mano:**
  - Tres datos que pesan en la recomendación: el precio de la API de doblaje de
    ElevenLabs, que los doblajes automáticos de YouTube no se pueden editar y que Rask
    solo clona en español de España.
  - La documentación de doblaje de Subtitle Edit.
  - Los metadatos de los cinco repositorios más cercanos.
- **Páginas que no se pudieron leer:**
  - Precios de Dubverse (HTTP 500).
  - Precios de VEED y de Azure (cargan por JavaScript).
  - Ayuda de CapCut (404).
- **Lo que no se hizo:** pruebas de calidad propias con estos productos. Comparar cómo
  suenan exigiría doblar los mismos vídeos con cada uno; queda como validación pendiente
  (§6).

## 1. El mapa en una tabla

Los usuarios no son los mismos. La pregunta que separa a las alternativas es **de quién
es el vídeo y quién paga por minuto**.

| Categoría | Ejemplos | Para quién | Modelo | Coste marginal por minuto |
|---|---|---|---|---|
| Doblaje comercial (SaaS) | ElevenLabs, HeyGen, Rask, Vozo, CAMB.AI, Dubverse | Creadores y empresas con **su propio** contenido | Nube; API en varios | Desde ~0,3 $ (HeyGen, a tarifa Speed) hasta 2,20–3 $ (ElevenLabs v2, Rask) |
| Plataforma de vídeo | Doblaje automático de YouTube | El creador del canal, en sus propios vídeos | Gratis dentro de YouTube Studio | 0 $, sin control |
| Editores con doblaje | Descript, Kapwing, VEED, CapCut | Creadores que editan por texto o para redes sociales | SaaS por suscripción con tope de minutos | Incluido hasta el tope (Kapwing Pro: 50 min/mes) |
| Editor de subtítulos con doblaje local | **Subtitle Edit 5.x** | Subtituladores; cualquier usuario de escritorio | Escritorio, gratis, MIT | GPU propia |
| Pipelines open source | pyVideoTrans, VideoLingo, VoiceStudio, Mazinger, SoniTranslate… | Usuarios técnicos que traducen vídeos de terceros o propios | Local, con APIs opcionales | GPU propia más la API de traducción |
| Piezas sueltas | Clonación (Cartesia, ElevenLabs TTS), sincronización labial (sync.so, LatentSync, MuseTalk) | Integradores | API o modelo local | 0,03–0,08 $/min de voz; 2,4–8 $/min de sincronización labial |
| **OpenDub** | — | **Una persona que quiere ver en español vídeos de YouTube de otros** | Local, MIT | GPU propia más la suscripción de Claude |

## 2. Alternativas relevantes

### 2.1 Doblaje comercial

**ElevenLabs Dubbing**
- **Versiones:**
  - Dubbing v2 es la versión por defecto y sigue marcada como *alpha*.
  - El Dubbing Studio v1 está «in maintenance mode» y solo recibe correcciones
    críticas.
  - Fuente: [docs/capabilities/dubbing](https://elevenlabs.io/docs/capabilities/dubbing).
- **Idiomas y voces:**
  - v2 anuncia más de 90 idiomas, con español es-ES, es-MX, es-AR y es-CL por separado.
  - Detecta hasta 32 hablantes y clona a cada uno, con una intensidad de clonación
    ajustable de 0 a 10.
  - Conserva el fondo original.
- **Edición:**
  - El Studio v1 permite editar la transcripción y la traducción por hablante,
    reasignar clips y regenerar un clip.
  - En la API, editar y regenerar es solo para Enterprise.
  - No se encontró glosario.
- **Sincronización:** el mecanismo no está documentado; el fabricante afirma que el
  resultado sale «perfectly aligned». No hay sincronización labial en Dubbing.
- **Exportación:**
  - El Studio exporta MP4, AAC, AAF, SRT y un WAV por hablante.
  - v2 entrega un audio sin pérdidas.
  - El vídeo es «a high-quality preview, not a production master».
- **Límites:** v2 admite 180 min y 1 GB en la aplicación; el Studio, 45 min.
- **Precio:**
  - La API v2 empieza en **2,20 $ por minuto de origen**
    ([dubbing-api](https://elevenlabs.io/dubbing-api), comprobado).
  - En la aplicación cuesta 2.000–10.000 créditos por minuto, y los créditos son
    compartidos entre productos ([pricing](https://elevenlabs.io/pricing)).
  - El plan gratuito pone marca de agua.
- **Datos:** según la [política de privacidad](https://elevenlabs.io/privacy-policy)
  (actualizada el 2026-10-09), entradas y salidas se usan «to research, build, train
  and improve our AI models». Se puede desactivar en «Data use», pero solo afecta al
  entrenamiento posterior.

**Doblaje automático de YouTube**
- **Para quién:** lo activa el creador sobre sus propios vídeos; un espectador no puede
  doblar el vídeo de otro.
- **Idiomas:** 27, y 8 con «Expressive Speech», español incluido, sin variantes
  ([blog, 2026-02-04](https://blog.youtube/news-and-events/youtube-auto-dubbing-expressive-speech/)).
- **Control:** «**You cannot edit automatic dubs**»; como mucho se corrige el idioma de
  origen y se regenera (comprobado).
- **Límites y extras:** solo vídeos de hasta 120 min. La sincronización labial es
  experimental, en piloto.
- **Doblaje propio:** un canal con funciones avanzadas puede subir su propio audio
  doblado como pista
  ([answer/13338784](https://support.google.com/youtube/answer/13338784)).
- Fuente: [answer/15569972](https://support.google.com/youtube/answer/15569972).

**HeyGen Video Translate**
- **Idiomas:** más de 175 en planes de pago, con variantes del español por separado.
  Acepta enlaces de YouTube.
- **Voz:** clona al hablante por defecto, y en la revisión se puede elegir una voz por
  pista.
- **Revisión (Proofread):** solo desde el plan Pro y solo antes del render final. Se
  edita el texto de cada segmento, se reasignan hablantes y se ajustan los tiempos.
- **Motores y sincronización labial** (créditos por minuto):

  | Motor | Sincronización labial | Créditos/min |
  |---|---|---|
  | Audio Only | no | 4 |
  | Speed | sí | 6 |
  | Precision | sí, la mejor | 10 |

- **Fondo:** la música se conserva; «Sound effects … are always removed».
- **Límites:** 30 min por vídeo en Creator y Pro, 60 en Business.
- **Precio:** Creator cuesta 29 $/mes por 600 créditos, unos 100 min a tarifa Speed
  ([pricing](https://www.heygen.com/pricing)).
- **Exportación:** el audio suelto solo en Enterprise.
- **Datos:** la [política](https://www.heygen.com/privacy) (2026-10-15) permite
  entrenar con las entradas, con exclusión por correo; contradice el «not used to
  train» de su FAQ.
- Fuente principal: [artículo de ayuda](https://help.heygen.com/en/articles/10029081-how-to-get-started-with-video-translation).

**Rask AI**
- **Idiomas:** más de 130, con 22 variantes del español, pero **solo el español de
  España admite clonación**; el resto usa voces prediseñadas
  ([ayuda](https://help.rask.ai/hc/to-which-languages-can-i-translate-my-video),
  comprobado).
- **Traducción:** «Dubbing 2.0» (página del 2026-10-13) reescribe la frase para que
  quepa, igual que hace OpenDub, en lugar de acelerar la voz como la versión 1.0
  ([meaning-first](https://help.rask.ai/hc/what-is-meaning-first-translation-approach)).
- **Edición:** editor línea a línea, glosarios y diccionario, prompts de traducción e
  historial de versiones.
- **Sincronización labial:** en beta; consume 3 min de cuota por cada minuto de vídeo.
- **Precio:** Creator cuesta 39 $/mes por 25 min; el minuto extra sale a 3 $
  ([pricing](https://www.rask.ai/pricing)).
- **Datos:** la política (2024-10-09) no dice nada sobre entrenar con los datos del
  usuario.

**Otros comerciales**
- **Vozo:** clonación automática, revisión antes de doblar y glosario que fija traducción
  y pronunciación. Creator cuesta 29 $/mes por unos 50 min
  ([pricing](https://www.vozo.ai/pricing)).
- **CAMB.AI:**
  - API de doblaje de extremo a extremo y doblaje en directo; acepta URL de YouTube.
  - Publica en código abierto sus modelos de voz MARS5 y MARS6.
  - Los minutos incluidos son pocos: el plan de 20 $ trae 4 min.
  - Fuentes: [docs](https://docs.camb.ai/), [pricing](https://www.camb.ai/pricing).
- **Dubverse:**
  - Orientado a India.
  - Ajusta el tiempo acelerando el audio o alargando el vídeo.
  - La sincronización labial cuesta 50 créditos por minuto.
  - Su página de precios devolvía HTTP 500.
  - Fuentes:
    [ajuste](https://help.dubverse.ai/en/articles/7870364-how-to-choose-optimization-settings-for-better-video-sync),
    [sincronización labial](https://help.dubverse.ai/en/articles/12381188-introducing-lipsync-in-dubverse).
- **Papercup:** ya no existe como producto. RWS compró su propiedad intelectual el
  2025-06-26 ([RWS](https://www.rws.com/about/news/2025/rws-acquires-papercups-ip)).

### 2.2 Editores con doblaje

- **Descript:**
  - «Dub speech» asigna **voces de stock** a cada hablante. La clonación es solo de tu
    propia voz.
  - «Match timing» reformula la frase para que quepa.
  - Revisar y regenerar es solo para Business.
  - Retraducir sobrescribe las ediciones manuales.
  - Hobbyist cuesta 16–24 $/mes.
  - Fuentes: [dubbing](https://help.descript.com/repurpose/dubbing),
    [pricing](https://www.descript.com/pricing).
- **Kapwing:**
  - Doblaje en más de 40 idiomas, con 50 min al mes en Pro (16 $/mes).
  - Clonación y sincronización labial solo en Business.
  - Fuente: [pricing](https://www.kapwing.com/pricing).
- **VEED y CapCut:**
  - Traducción de subtítulos y doblaje dentro del editor.
  - Precios no encontrados (VEED) y ayuda inaccesible (CapCut).

### 2.3 El competidor directo: Subtitle Edit 5.x

Este es **el hallazgo más importante**.
[Subtitle Edit](https://github.com/SubtitleEdit/subtitleedit) es un editor de subtítulos
de escritorio para Windows, macOS y Linux.
- **Proyecto:** MIT; 14,7k estrellas; versión v5.3.0 del 2026-10-14; commit del
  2026-10-25. Ya incluye un doblaje local que se solapa mucho con OpenDub.
- **Motores locales de voz:** Chatterbox, IndexTTS 2.5, CosyVoice3, Qwen3-TTS, VoxCPM2,
  Piper, Kokoro y otros. También ofrece en la nube ElevenLabs, Azure, Google y edge-tts.
  Son los mismos motores que eligió OpenDub
  ([texto a voz](https://subtitleedit.github.io/subtitleedit/features/text-to-speech.html),
  comprobado).
- **Funciones de doblaje:**
  - «Remove original speech» separa las voces con Mel-Band RoFormer o HTDemucs y
    conserva la música y los efectos.
  - «Find voices in video and clone» detecta a los hablantes; se pueden renombrar o
    fusionar, y clona a cada uno.
  - «Set up cast» asigna una voz por personaje.
  - «Clone from video (voice of each line)» usa como referencia la voz original de cada
    línea.
- **Ajuste de tiempo:** solo **acelera** la voz al tiempo de cada subtítulo; no reescribe
  la frase para que quepa.
- **Revisión:** una tabla línea a línea con regeneración.
- **Traducción:**
  - Motores: Claude, OpenAI, Gemini, DeepL, Google y LLM locales (Ollama, LM Studio,
    llama.cpp, NLLB).
  - Los LLM locales traducen por lotes con contexto, sinopsis y glosario.
  - Fuente: [auto-translate](https://subtitleedit.github.io/subtitleedit/features/auto-translate.html).
- **Límites:**
  - Su detección de hablantes por defecto (MOSS Diarize) solo cubre inglés y chino.
  - No se vio descarga desde YouTube, ni comparación de versiones, ni comprobación de
    inteligibilidad con reserva.

### 2.4 Pipelines open source

Los datos de estrellas, fechas y licencias salen de la API de GitHub y de los ficheros
`LICENSE`. Los cuatro primeros proyectos de la tabla se volvieron a comprobar a mano.

| Proyecto | Licencia | Estrellas · último commit | Interfaz | Clonación | Varias voces | Ajuste al tiempo | Edición |
|---|---|---|---|---|---|---|---|
| [pyVideoTrans](https://github.com/jianchang512/pyvideotrans) | GPL-3.0 | 19,5k · 2026-10-23 | Escritorio, CLI, web; `.exe` para Windows | F5-TTS, CosyVoice, IndexTTS, GPT-SoVITS, Chatterbox… | Sí (según el README) | Acelerar el audio, ralentizar el vídeo o ambos; **no reescribe** | Revisión por etapas |
| [VideoLingo](https://github.com/Huanshere/VideoLingo) | Apache-2.0 | 18,9k · 2026-09-30 | Streamlit; `.bat` | GPT-SoVITS, F5-TTS, Fish… | **No** (lo dice su README) | `atempo`; el recorte con LLM está comentado en el código | Pausar por etapas |
| [VoiceStudio](https://github.com/debpalash/VoiceStudio) | AGPL-3.0 con CLA y versión «Pro» de pago | 86,6k (repositorio creado en 2026-04; cifra no verificable como orgánica) · 2026-10-25 | Electron, API, MCP | CosyVoice 3, IndexTTS 2.5, OmniVoice… | Sí | Concise / Smart Fit / Stretch / Lip sync; reescritura con un agente (Claude Code o Codex) | Editor de segmentos, regenerar solo lo cambiado |
| [Mazinger Dubber](https://github.com/bakrianoo/mazinger) | MIT | 471 · 2026-10-01 | Gradio, CLI, Colab | Qwen3-TTS, OmniVoice, Chatterbox | No documentado | Por tramos de voz; reescribe con un LLM lo que exige más de 1,15× | Editor por trozos, redoblar solo lo cambiado |
| [SoniTranslate](https://github.com/R3gm/SoniTranslate) | Apache-2.0 | 1,4k · última versión 2024-05 | Gradio, Colab | XTTS, OpenVoice | pyannote, hasta 12 | Aceleración | Editar el subtítulo traducido |
| [Voice-Pro](https://github.com/abus-aikorea/voice-pro) | GPL-3.0 | 13,4k · 2026-07-13 («development … not possible for the time being») | Gradio; solo Windows verificado | F5-TTS, CosyVoice | No | Manual | — |
| [open-dubbing](https://github.com/Softcatala/open-dubbing) | Apache-2.0 | 436 · 2025-07-08 | CLI | No (voces por género) | pyannote | Velocidad | Editar un JSON |
| [OpenCreator (antes KrillinAI)](https://github.com/krillinai/OpenCreator) | Apache-2.0 | 13,9k · 2026-10-25 | Escritorio; motor basado en Codex | Solo en la nube | No documentado | No documentado | Línea de tiempo de subtítulos |

Descartados:
- Linly-Dubbing: sin commits desde 2025-03.
- ViDubb: pequeño y parado.
- SmartSub: se centra en subtítulos.
- youtube-auto-dub: mismo nicho que OpenDub, pero mucho más fino.

### 2.5 Piezas: clonación y sincronización labial

- **Licencias de los modelos de voz:**
  - Chatterbox (MIT) y CosyVoice 3 (Apache-2.0) permiten uso comercial.
  - IndexTTS-2.5 lleva la licencia de bilibili: comercial por debajo de 100 M de
    usuarios activos.
  - Prohíben o restringen el uso comercial: los pesos oficiales de F5-TTS
    (CC-BY-NC-4.0), XTTS-v2 (Coqui Public Model License, no comercial) y Fish Speech
    (licencia comunitaria con umbral de ingresos).
  - **Las elecciones de OpenDub son de las más limpias del mercado open source.**
- **Clonación en la nube** para un usuario sin GPU:
  - [Cartesia](https://cartesia.ai/pricing): ~750–800 créditos por minuto, desde
    5 $/mes. Clona desde 10 s y habla español.
  - [ElevenLabs TTS](https://elevenlabs.io/pricing/api): 0,08 $ por 1.000 caracteres,
    ~0,08 $/min.
  - Azure Personal Voice y Google Instant Custom Voice exigen alta aprobada y una
    grabación de consentimiento del hablante: no sirven para el hablante de un vídeo de
    YouTube.
  - PlayHT cerró: según fuentes de terceros, Meta compró el equipo en 2025 y el servicio
    terminó el 31 de diciembre.
- **Sincronización labial:**
  - [sync.so](https://sync.so/pricing): lipsync-2 a 0,04–0,05 $/s (~2,4–3 $/min); el
    plan Hobbyist limita a 1 min por vídeo.
  - [LatentSync](https://github.com/bytedance/LatentSync): Apache-2.0, 18 GB de VRAM en
    la v1.6, sin actividad desde 2025-06.
  - [MuseTalk](https://github.com/TMElyralab/MuseTalk): código MIT, pesos comerciales;
    cara a 256 px con temblor reconocido por los autores.
  - [Wav2Lip](https://github.com/Rudrabha/Wav2Lip): «any form of commercial use is
    strictly prohibited».
  - Todos funcionan con un rostro de frente.

## 3. Matriz

### 3.1 Lo que OpenDub ya hace como los demás

- Clona la voz del hablante y conserva la música de fondo, igual que ElevenLabs, HeyGen,
  Rask, Subtitle Edit y VoiceStudio.
- Detecta varios hablantes con una voz cada uno (ElevenLabs, HeyGen, Subtitle Edit,
  pyVideoTrans).
- Permite editar la traducción, regenerar una frase y usar glosario (ElevenLabs Studio
  v1, HeyGen Pro, Rask, Vozo, VoiceStudio, Mazinger).
- Exporta SRT y pistas separadas, como ElevenLabs Studio y HeyGen; el audio suelto, en
  HeyGen, solo en Enterprise.

### 3.2 Lo que hace mejor o distinto

- **Ajustar reescribiendo, no acelerando.** OpenDub traduce cada frase con el límite de
  caracteres que permite su hueco, mide el ritmo de la voz clonada y vuelve a pedir una
  versión más corta si no cabe.
  - Solo lo documentan Rask «Dubbing 2.0», Descript «Match timing», Mazinger y
    VoiceStudio.
  - Subtitle Edit, pyVideoTrans, VideoLingo, Dubverse y Vozo aceleran la voz o alteran
    el vídeo.
- **Control de calidad de la voz.** whisper comprueba que cada clip se entiende, y si
  falla hay una cadena de reserva (otra semilla → frase más corta → referencia fija →
  voz de stock del mismo sexo). No se encontró nada equivalente en ninguna alternativa.
- **Calidad medida, no anunciada.** Escucha a ciegas con su script, métricas del
  doblaje final y pérdida de sentido al acortar. Nadie publica algo comparable; la
  calidad de los demás es afirmación de marketing.
- **Español con criterio propio.**
  - El motor se eligió de oído (V3 frente al afinado es-ES).
  - Hay variante, tuteo o usted, y concordancia de género por hablante.
  - Rask, por ejemplo, solo clona en es-ES.
- **El espectador, no el creador.** Dobla vídeos de otros para verlos uno mismo.
  - YouTube no deja hacerlo, y no permite editar sus doblajes.
  - Los SaaS cobran cada minuto (2,20 $/min en ElevenLabs v2, ~3 $/min extra en Rask)
    y están pensados para contenido propio.
- **Privacidad.** Audio, vídeo y voces clonadas no salen de la máquina; solo el texto va
  a Claude. ElevenLabs y HeyGen entrenan por defecto con las entradas del usuario.
- **Licencias limpias.** MIT y motores que permiten uso comercial, frente a GPL o AGPL
  con CLA en los pipelines grandes y pesos no comerciales en otros.

### 3.3 Lo que la competencia hace y OpenDub no

- Sincronización labial (HeyGen, Rask, Vozo, Descript, Kapwing, piloto de YouTube).
- Muchos idiomas de destino y varios a la vez (de 27 a más de 175).
- Variantes del español elegibles para la voz clonada (ElevenLabs v2: es-ES, es-MX,
  es-AR, es-CL).
- Revisar la traducción **antes** de sintetizar (HeyGen Proofread, Vozo «Proofread
  Before Dubbing»).
- Clonar con la voz de cada línea como referencia (Subtitle Edit, VoiceStudio).
- Importar y exportar subtítulos con hablante (actor en ASS, `<v>` en WebVTT), para
  trabajar con otras herramientas (Subtitle Edit).
- Instaladores de un clic, Windows y Apple Silicon (pyVideoTrans, VideoLingo,
  VoiceStudio, Subtitle Edit).
- Traducción sin conexión o con otros proveedores (NLLB, Ollama, DeepL).
- Equipos, API, webhooks, formatos de entrega (AAF, MXF, SCORM) y doblaje en directo.

### 3.4 Lo que no merece la pena implementar

- **Sincronización labial.**
  - Sirve para un rostro de frente.
  - En local cuesta 8–18 GB de VRAM, que compiten con los motores de voz, y deja
    artefactos reconocidos por sus autores. Por API son 2,4–8 $/min.
  - Para ver tutoriales y charlas técnicas aporta poco: la mayor parte de la pantalla es
    código, diapositivas o manos.
- **Muchos idiomas.** Multiplica la evaluación: cada idioma necesita su propia escucha y
  su propio criterio de voz y estilo. La ventaja de OpenDub está en haber afinado uno.
- **Equipos, API pública, cuentas, SaaS.** Infraestructura y soporte continuos; ver §4.3.
- **Formatos de entrega profesional (AAF, MXF, SCORM) y doblaje en directo.** Son de otro
  usuario.
- **Clonación en la nube como motor principal.** Rompería la privacidad y el coste cero
  por minuto, que son parte de la diferencia. Como reserva opcional para quien no tenga
  GPU sí tiene sentido; ver §6.

### 3.5 Dónde puede haber una ventaja real

Hay ventaja en la combinación de tres cosas:
- el **lazo de calidad**: traducción ajustada al hueco, acortado, comprobación de
  inteligibilidad, reservas y escucha a ciegas;
- el **control fino después del doblaje**: retoques por frase, versiones comparables,
  hablantes corregibles;
- el **coste cero por minuto en la máquina propia**.

Subtitle Edit tiene los motores, pero no el lazo de calidad. Los SaaS tienen el pulido,
pero cobran por minuto y no dejan doblar lo ajeno. VoiceStudio es lo más parecido, pero
su propia documentación reconoce que el resultado real con varios hablantes «remain[s]
unverified», y es un producto de empresa con licencia AGPL y versión de pago.

## 4. Posicionamiento

### 4.1 La mejor herramienta local-first para creadores técnicos

- **Usuarios:** creadores y desarrolladores con GPU NVIDIA que quieren doblar sus vídeos
  o los de otros.
- **Diferenciación:** débil frente a Subtitle Edit, que ya es gratis, multiplataforma,
  con los mismos motores y más de diez años de base de usuarios, y frente a
  pyVideoTrans o VideoLingo, con 19k estrellas y paquetes para Windows.
- **Esfuerzo técnico:**
  - Alto: instaladores, Windows, Apple Silicon, otros proveedores de traducción, más
    idiomas.
  - Todo eso es lo contrario de la decisión sobre el Mac y de «solo español».
- **Coste operativo:** incidencias y soporte de instalación en máquinas ajenas, que es lo
  que más pesa con un solo desarrollador.
- **Riesgo:** competir en amplitud con proyectos con equipo, o con un editor maduro que
  ya añadió el doblaje.
- **Implicaciones para el roadmap:** empaquetado y portabilidad pasarían por delante de
  la calidad.

### 4.2 La mejor calidad y control para contenido educativo y técnico doblado al español

- **Usuarios:** quien consume o produce tutoriales, charlas y cursos en inglés y los
  quiere en español con buena calidad: términos técnicos bien traducidos, sincronía,
  voz natural.
- **Diferenciación:** fuerte. El lazo de calidad medido, el glosario y el estilo, los
  retoques y la elección de motor por escucha no los tiene nadie junto.
- **Esfuerzo técnico:** moderado y en la línea actual:
  - revisión antes de sintetizar;
  - fidelidad de la traducción medida;
  - interoperabilidad de subtítulos;
  - más vídeos en el corpus de escucha.
- **Coste operativo:** bajo si sigue siendo local y sin promesa de soporte.
- **Riesgos:**
  - Que el público sea pequeño: no hay datos de cuánta gente busca esto.
  - Que los SaaS acorten distancia, porque Rask ya reescribe para ajustar.
  - La dependencia de una suscripción de Claude.
- **Implicaciones para el roadmap:** calidad y control primero; amplitud nunca.

### 4.3 Plataforma general de localización de vídeo

- **Usuarios:** empresas y creadores con volumen.
- **Diferenciación:** ninguna frente a ElevenLabs, HeyGen o Rask, que tienen equipos,
  más de 90 idiomas, sincronización labial y API.
- **Esfuerzo técnico:** muy alto (multiusuario, cola en servidor, facturación,
  almacenamiento, cumplimiento).
- **Coste operativo:** GPU en la nube por minuto doblado, soporte continuo y
  responsabilidad legal por clonar voces de terceros a escala.
- **Riesgo:** inviable para una persona a tiempo parcial.
- **Implicaciones para el roadmap:** lo reescribiría entero.

### 4.4 Herramienta personal excelente, sin pretensión de distribución

Es el estado actual.
- **Usuarios:** el propietario y quien quiera clonar el repo, sin promesa de soporte.
- **Diferenciación:** no hace falta; el criterio es que funcione muy bien para un uso
  concreto.
- **Esfuerzo técnico:** el que el propietario decida.
- **Coste operativo:** casi nulo.
- **Riesgos:**
  - Ninguno de mercado.
  - El riesgo es de foco: añadir funciones porque otros las tienen.
- **Implicaciones para el roadmap:** solo lo que mejora la experiencia propia.

## 5. Recomendación

**La 4 como forma y la 2 como criterio.** Es decir, una herramienta personal,
sin distribución ni soporte, cuya regla para el roadmap sea la calidad y el control del
doblaje de contenido técnico y educativo al español.

En la práctica:
- **Sí entra:**
  - lo que mejora el lazo de calidad;
  - lo que ahorra trabajo al revisar un vídeo largo;
  - lo que permite medir.
- **No entra:**
  - lo que solo amplía (idiomas, plataformas, equipos, sincronización labial);
  - lo que crea obligaciones con terceros (instaladores, soporte, servicio).
- El repositorio sigue público y con MIT como referencia; publicar no implica mantener.

**El intercambio:**
- Se renuncia a usuarios y visibilidad. Un pyVideoTrans o un Subtitle Edit llegan a
  mucha más gente.
- A cambio, OpenDub conserva lo que de verdad tiene: la combinación de lazo de calidad,
  control después del doblaje y coste cero, que nadie ofrece junta.
- No se mete en una carrera de amplitud que no puede ganar una sola persona a tiempo
  parcial.
- La opción 1 tiene sentido solo si el propietario quiere usuarios. Aun así sería mejor
  vía colaboración (exportar o importar con Subtitle Edit) que compitiendo con él.

**Lo que la evidencia no permite afirmar:**
- **Que el doblaje de OpenDub suene mejor que el de ElevenLabs, HeyGen o Subtitle Edit.**
  No se ha comparado de oído. El lazo de calidad es una ventaja de proceso, no de
  resultado demostrado.
- **Que exista un público para la opción 2 fuera del propietario.** No hay datos.

## 6. Qué habría que validar antes de afirmar más

1. **Comparativa de oído contra uno o dos competidores.**
   - Qué: los mismos 2–3 vídeos del corpus doblados con ElevenLabs v2 (el plan gratuito
     pone marca de agua; ~2,20 $/min por API) y con Subtitle Edit usando Chatterbox,
     enfrentados a OpenDub en una sesión de `docs/bench/listening`.
   - Coste: una tarde y unos pocos dólares.
   - Responde a: si el lazo de calidad se oye.
2. **Si interesa a alguien más.** Solo si el propietario contempla las opciones 1 o 2:
   enseñarlo a 3–5 personas que vean contenido técnico en inglés y ver si lo usarían con
   su propia GPU.
3. **El riesgo de la traducción.**
   - Si la suscripción de Claude por CLI deja de servir para este uso, el pipeline se
     para.
   - El backend de API ya existe (`--backend api`).
   - Falta comprobar en los términos actuales que el uso por CLI es aceptable y tener
     medido el coste por vídeo con la API.

## 7. Decisiones del propietario (2026-10-25)

1. **Usuarios: no por ahora.**
   - El repositorio sigue público con MIT; quien quiera puede usarlo.
   - No se asumen soporte, instaladores ni compatibilidades.
   - Se revisa tras la escucha comparativa del punto 2:
     - si OpenDub no suena mejor que Subtitle Edit, buscar usuarios no tiene sentido;
     - si suena mejor, habrá un argumento real.
2. **Escucha comparativa: requisito de entrada de la ejecución 3.**
   - Qué: 2–3 vídeos del corpus, OpenDub frente a Subtitle Edit y frente a ElevenLabs,
     a ciegas, con el script de sesión que ya existe (`docs/bench/listening`).
   - Por qué: es el único dato que valida la premisa del producto.
   - Si el lazo de calidad no se oye, el roadmap cambia: más calidad de voz y menos
     herramientas de edición.
3. **Dependencia de la suscripción de Claude.**
   - Se resuelve con un backend local en Ollama (Gemma 3 27B o Qwen3-30B-A3B).
   - Se valida contra Sonnet en el corpus con las métricas de longitud que ya existen.
   - Mientras tanto, la API (`--backend api`) queda documentada como camino alternativo
     en el README.
4. **Vídeos y voces de terceros.**
   - La postura completa queda diferida mientras no haya distribución.
   - Ya está escrita en el README: uso personal, y no publicar doblajes con voces
     clonadas de terceros.

## 8. Escucha comparativa (2026-10-25)

Es el requisito de entrada de la ejecución 3 (§7.2). Sesión `vs-others` de
`docs/bench/listening`:
- **Material:** 10 fragmentos de 10–15 s de los dos vídeos cortos del corpus
  (`17kBVfGjI8c`, voz masculina; `rwF-X5STYks`, voz femenina).
- **Escucha:** tres doblajes por fragmento en orden aleatorio, igualados en sonoridad.
- **Notas:** una nota global de 1 a 5 y una preferencia, sin saber cuál era cuál hasta
  el final.

| Fuente | Cómo se hizo | Nota media | Preferido |
|---|---|---|---|
| **OpenDub** | Su doblaje normal con Chatterbox V3: traducción ajustada al hueco, acortado, comprobación con whisper, aceleración de 1,25× como máximo | **3,7** | **9 de 10** |
| Réplica del enfoque de Subtitle Edit y pyVideoTrans | Misma traducción de Claude pero sin límite de longitud (`translate_srt.py`), misma voz Chatterbox V3 y misma referencia, cada línea acelerada hasta su subtítulo sin tope (mediana 1,14× y 1,31×, máximo 1,69×), sin acortar ni comprobar (`speedup_dub.py`) | 2,9 | 1 de 10 |
| ElevenLabs Dubbing v2 | Su doblaje real con el plan gratuito, inglés → español, hablantes automáticos; en la sesión, su audio con la imagen original (`elevenlabs_dub.py`) | 2,0 | 0 de 10 |

**Lectura:**
- **El lazo de calidad se oye.**
  - Con la misma voz y el mismo traductor, ajustar la traducción al hueco gana a
    acelerar.
  - La réplica solo empató o ganó donde casi no tuvo que acelerar: el fragmento
    f04 empató a 4, y en f08 ganó con 4 frente a 3.
- **ElevenLabs sacó un 2 en los diez fragmentos.** Antes de darlo por bueno se descartó
  un fallo técnico de la preparación:
  - su voz habla cuando habla el original, con 0,3 s de adelanto, parecido a la voz
    original;
  - conserva la música;
  - es español de principio a fin.
  - Así que la nota es el juicio de cómo suena, no un error de sincronía.

**Límites, que impiden generalizar:**
- **Muestra pequeña:** dos vídeos cortos de una sola voz, 10 fragmentos y un solo
  oyente, que es el propietario.
- **La segunda fuente es una réplica, no Subtitle Edit.** Reproduce el enfoque que
  documentan Subtitle Edit y pyVideoTrans con piezas de OpenDub. Sus programas pueden
  diferir en detalles: recorte de silencios, tope de velocidad, mezcla. No se pudo usar
  el programa real porque exige manejar su interfaz gráfica, y no se instaló
  pyVideoTrans por no ejecutar código de terceros.
- **ElevenLabs:** se probó su plan gratuito con Dubbing v2, que sigue en *alpha*, sin
  editar nada.
- **Sin datos de vídeos largos, con música o con varias voces.**

**Consecuencia:** se cumple la condición del §7.1, «si suena mejor, tendrás un
argumento real», con estos límites. Volver a plantear si se buscan usuarios es decisión
del propietario. La ejecución 3 puede empezar.

## 9. Escucha comparativa en vídeos más difíciles (T-26, 2026-10-26)

**Montaje:**
- Sesión `vs-others-long` con las mismas tres fuentes, una nota global y la
  preferencia.
- Dos tramos de 150 s, porque ElevenLabs solo se dobló en esos tramos:
  - `VD6xJq8NguY`, 263–413 s: voz continua con música, 8 fragmentos;
  - el pódcast `R4zlpwwEpnY`, 484–634 s: los dos presentadores con 10 cambios de turno,
    8 fragmentos.
- La réplica del enfoque de acelerar dio a cada línea la voz de su hablante, como hace
  Subtitle Edit con *Find voices in video and clone*. ElevenLabs usó su propia detección
  de hablantes.

| Vídeo | OpenDub | Réplica de acelerar | ElevenLabs | Preferido |
|---|---|---|---|---|
| `VD6xJq8NguY` (música) | **3,38** | 2,38 | 2,75 | OpenDub 5, réplica 2, igual 1 |
| `R4zlpwwEpnY` (dos voces) | 2,75 | **3,12** | 2,75 | **réplica 4**, OpenDub 3, ElevenLabs 1 |
| Los dos | 3,06 | 2,75 | 2,75 | OpenDub 8, réplica 6, ElevenLabs 1, igual 1 |

**Lectura:**
- **Con música y voz continua, OpenDub gana con claridad**, como en los vídeos cortos.
- **En el pódcast pierde frente a la réplica.** La causa está medida y no es el enfoque,
  sino un defecto concreto:
  - El clon de la presentadora (B) habla a 17,8 caracteres/s. La presentadora original
    habla a 15,6 caracteres/s (en inglés).
  - Su ritmo estaba bien calibrado: 18,2 caracteres/s. Pero OpenDub solo limita la
    longitud por arriba: nada pide a la traducción llenar el hueco y la voz nunca se
    ralentiza.
  - Resultado: sus frases acaban antes. En el tramo, la voz de OpenDub llena el 80 % del
    tiempo que habla el original, la réplica el 86 % y en el vídeo con música OpenDub el
    95 %. 14 de los 22 clips cubren menos del 80 % de su hueco y dejan silencios en mitad
    de la conversación.
  - Los fragmentos en que OpenDub sacó un 2 (f11–f13) son los de ella.
  - La voz del presentador (A) llena el 97 % y no tiene el problema.
  - La réplica, con la misma voz B, rellena más porque su traducción literal es un 14 %
    más larga.
- **ElevenLabs** queda en 2,75 en los dos vídeos: mejor que en los cortos (2,0), por
  debajo de OpenDub con música e igual que OpenDub en el pódcast.

**Consecuencias:**
- La premisa se sostiene donde hay que comprimir (música, ritmo continuo).
- Falta la otra mitad del ajuste: **llenar el hueco cuando sobra**. Pasa al roadmap como
  T-36. La decisión sobre varias voces por defecto en la CLI espera a ese arreglo, porque
  en el pódcast el defecto pesa más que el hecho de tener varias voces.

**Límites:** como en el §8, un solo oyente, dos tramos de 150 s y una réplica en lugar
del programa real. Además, el defecto del pódcast se diagnosticó **después** de oír, a
partir de las notas.

## 10. Llenar el hueco y lo que de verdad falla en el pódcast (T-36, 2026-10-26)

**Qué se probó** para llenar el hueco que dejaba la voz B (§9):
1. **Pedir a la traducción una longitud mínima** (`min_chars`, el 85 % de lo que cabe en
   la duración del original). Se descartó:
   - B pasó del 82 % al 83 %; el modelo apenas alarga y, donde alarga, mete relleno
     («erupción activa», «tanto volcanismo»).
   - A, con frases más largas, acumuló voz a destiempo (de 0,8 s a 10,2 s).
   - El español de B ya ocupa casi lo mismo que el inglés (8.438 frente a 8.698
     caracteres): el hueco viene de la voz, no del texto.
2. **Ralentizar la voz hasta 0,9 clip a clip.** Llenaba (B al 89,5 %), pero en el vídeo
   con música la voz a destiempo pasó de 46 s a 284 s: al alargar los clips cortos se
   come el margen que absorbía los retrasos de los anteriores.
3. **Ralentizar sabiendo dónde sonará cada clip** (`tts.fill_gaps`, lo que queda): solo
   si el clip acaba bastante antes que su frase original, nunca por debajo de 0,9 y sin
   pasar del inicio del siguiente.

| | Antes | Después |
|---|---|---|
| Pódcast, B llena (vídeo entero / tramo de la escucha) | 82 % / 76 % | 89 % / 84 % |
| Pódcast, clips de B bajo el 80 % | 33 | 12 |
| Música, llena · clips bajo el 80 % | 96 % · 13 | 97 % · 3 |
| Música, voz a destiempo | 46 s | 46 s |
| CER de whisper (pódcast / música) | 2,2 % / 1,1 % | 3,1 % / 1,3 % |

**Escucha a ciegas** (`fill-gaps`, antes frente a después, los tramos del §9, 15
fragmentos): **no se distingue**. Igual en 14, la versión nueva preferida en 1; música
3,25 frente a 3,50; pódcast 2,29 en las dos.

> Una primera sesión se descartó: las versiones nuevas se mezclaron desde la CLI sin
> `--separate` y llevaban la voz original por debajo.

**Lectura:**
- La medida del §9 era cierta, pero **no era lo que hace sonar mal el pódcast**. El
  cambio se queda (activado por defecto) porque mejora las medidas sin empeorar nada, no
  porque se oiga.
- Lo que describe el oyente: «la traducción no acompaña a la persona que habla, se nota
  sintético». Los datos apuntan a **cómo se cortan las frases**:
  - OpenDub agrupa en frases de hasta 12 s; B habla con frases largas encadenadas, así
    que se cortan a los 12 s, a mitad de frase (85 de los 185 fragmentos del vídeo
    acaban sin cerrar la frase).
  - Cada fragmento es un clip independiente: la voz cierra la entonación donde se corta
    y vuelve a empezar.
  - B hace dos o tres pausas dentro de esos 12 s; el clip doblado lo dice todo seguido y
    calla.
  - La réplica, que ganó en el pódcast, coloca cada línea de subtítulo donde empieza:
    35 trozos de 6 s como mucho en el tramo, frente a los 21 de OpenDub.
- Pasa al roadmap como **T-37**. Lo que tenga de sintético la propia voz de Chatterbox
  no lo arregla eso: si tras T-37 sigue sonando así, el límite es el motor.

**Límites:** un oyente; el diagnóstico de T-37 vuelve a salir después de oír.

## Anexo · Fuentes

Todas consultadas el 2026-10-25; entre paréntesis, la fecha propia de la página cuando la
tiene.

- **ElevenLabs:**
  - [Dubbing docs](https://elevenlabs.io/docs/capabilities/dubbing)
  - [Dubbing API](https://elevenlabs.io/dubbing-api)
  - [Precios](https://elevenlabs.io/pricing)
  - [Precios de la API](https://elevenlabs.io/pricing/api)
  - [Privacidad](https://elevenlabs.io/privacy-policy) (2026-10-09)
  - [Términos](https://elevenlabs.io/terms-of-use) (2026-10-09)
  - [Clonación instantánea](https://elevenlabs.io/docs/product-guides/voices/voice-cloning/instant-voice-cloning)
  - [Clonación profesional](https://elevenlabs.io/docs/product-guides/voices/voice-cloning/professional-voice-cloning)
- **YouTube:**
  - [Doblaje automático](https://support.google.com/youtube/answer/15569972)
  - [Pistas de audio propias](https://support.google.com/youtube/answer/13338784)
  - [Blog](https://blog.youtube/news-and-events/youtube-auto-dubbing-expressive-speech/) (2026-02-04)
- **HeyGen:**
  - [Precios](https://www.heygen.com/pricing)
  - [Primeros pasos](https://help.heygen.com/en/articles/10029081-how-to-get-started-with-video-translation)
  - [Proofread](https://help.heygen.com/en/articles/10024431-how-to-use-proofreading-for-video-translation)
  - [Idiomas](https://help.heygen.com/en/articles/11391941-video-translation-languages-we-support)
  - [Privacidad](https://www.heygen.com/privacy) (2026-10-15)
- **Rask:**
  - [Precios](https://www.rask.ai/pricing)
  - [Idiomas](https://help.rask.ai/hc/to-which-languages-can-i-translate-my-video)
  - [Dubbing 2.0](https://help.rask.ai/hc/what-is-meaning-first-translation-approach) (2026-10-13)
  - [Límites de subida](https://help.rask.ai/hc/upload-requirements-formats-file-size-and-maximum-video-length)
  - [Privacidad](https://www.rask.ai/privacy-policy) (2024-10-09)
- **Otros comerciales:**
  - Vozo: [docs](https://www.vozo.ai/docs/translate_dub/get_started), [precios](https://www.vozo.ai/pricing)
  - CAMB.AI: [docs](https://docs.camb.ai/), [precios](https://www.camb.ai/pricing), [open source](https://docs.camb.ai/open-source.md)
  - Dubverse: [ajuste](https://help.dubverse.ai/en/articles/7870364-how-to-choose-optimization-settings-for-better-video-sync) (2024-05-13), [sincronización labial](https://help.dubverse.ai/en/articles/12381188-introducing-lipsync-in-dubverse) (2025-09-30), [créditos](https://help.dubverse.ai/en/articles/9382695-how-dubverse-credits-work)
  - [RWS · Papercup](https://www.rws.com/about/news/2025/rws-acquires-papercups-ip) (2025-06-26)
- **Editores:**
  - Descript: [dubbing](https://help.descript.com/repurpose/dubbing), [translate](https://help.descript.com/repurpose/translate-overview), [precios](https://www.descript.com/pricing)
  - [Kapwing · precios](https://www.kapwing.com/pricing)
  - [VEED · precios](https://www.veed.io/pricing)
  - Subtitle Edit: [repositorio](https://github.com/SubtitleEdit/subtitleedit), [texto a voz](https://subtitleedit.github.io/subtitleedit/features/text-to-speech.html), [traducción](https://subtitleedit.github.io/subtitleedit/features/auto-translate.html)
- **Open source:**
  - [pyVideoTrans](https://github.com/jianchang512/pyvideotrans)
  - [VideoLingo](https://github.com/Huanshere/VideoLingo)
  - [VoiceStudio](https://github.com/debpalash/VoiceStudio)
  - [Mazinger](https://github.com/bakrianoo/mazinger)
  - [SoniTranslate](https://github.com/R3gm/SoniTranslate)
  - [Voice-Pro](https://github.com/abus-aikorea/voice-pro)
  - [open-dubbing](https://github.com/Softcatala/open-dubbing)
  - [OpenCreator](https://github.com/krillinai/OpenCreator)
- **Modelos:**
  - [Chatterbox](https://github.com/resemble-ai/chatterbox)
  - [IndexTTS](https://github.com/index-tts/index-tts)
  - [CosyVoice](https://github.com/FunAudioLLM/CosyVoice)
  - [F5-TTS](https://github.com/SWivid/F5-TTS)
  - [XTTS-v2](https://huggingface.co/coqui/XTTS-v2)
  - [Fish Speech](https://github.com/fishaudio/fish-speech)
  - [LatentSync](https://github.com/bytedance/LatentSync)
  - [MuseTalk](https://github.com/TMElyralab/MuseTalk)
  - [Wav2Lip](https://github.com/Rudrabha/Wav2Lip)
- **Voz y sincronización labial en la nube:**
  - [Cartesia](https://cartesia.ai/pricing)
  - [sync.so](https://sync.so/pricing)
  - [Azure Personal Voice](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/personal-voice-overview) (2026-09-09)
  - [Google Instant Custom Voice](https://docs.cloud.google.com/text-to-speech/docs/chirp3-instant-custom-voice) (2026-10-22)
