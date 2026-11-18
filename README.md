> **Despliegue gratuito en la nube: lee `DESPLIEGUE.md`.**

# Apoyo Estudiantil (microservicios)
1. `cp .env.example .env` y pon ANTHROPIC_API_KEY. 2. `docker compose up --build`. 3. http://localhost:8000
## Microsoft Entra ID + Authenticator (para DEV_AUTH=0)
1. Entra > App registrations > New. Redirect URI (Web): `${BASE_URL}/api/auth/callback`.
2. Crea un client secret. Copia tenant id, client id y secret a `.env` (MS_TENANT, MS_CLIENT_ID, MS_SECRET). EMAIL_DOMAIN = dominio institucional.
3. Entra > Protection > Conditional Access: exige MFA (método Microsoft Authenticator) para esta app.
4. Pon DEV_AUTH=0. El servicio auth rechaza tokens sin MFA o de otro dominio.
## Datos sensibles
Habeas data (Ley 1581): consentimiento, política de tratamiento, cifrado en reposo y acceso restringido antes de producción.

## IA multi-proveedor (rotación de API keys)
En `.env` pon varias keys separadas por coma; la app las rota sola y salta las que se agoten (429) o fallen:
- `GEMINI_API_KEYS=key1,key2,key3` (Google AI Studio, una por cuenta) · `GEMINI_MODEL`
- `GITHUB_MODELS_TOKENS=ghp_...` (token con permiso *models*) · `GITHUB_MODEL`
- `COHERE_API_KEYS=...` · `COHERE_MODEL`
- `ANTHROPIC_API_KEY` es opcional (último respaldo). Orden: `LLM_ORDER=gemini,github,cohere,anthropic`.
Cada respuesta empieza por una key distinta para repartir el gasto. Estado: `GET /api/chat/status` (sin mostrar keys).
Tareas internas (clasificar emociones, resumir memoria) usan primero GitHub/Cohere (`ETL_LLM_ORDER`, `MEMORY_LLM_ORDER`) para cuidar la cuota de Gemini.
Cambios de `.env`: `docker compose up -d --build chat etl auth frontend`.

## Memoria total y datalake
- Todo cae primero al datalake (S3) en crudo, particionado: `raw/<tipo>/<usuario>/<ts>.json` (chat de ambos lados, voz/chat, decisiones, encuestas, juegos, resúmenes de memoria). El ETL lo pasa a `processed/` y lo carga en MongoDB (historial, perfil, conocimiento, memoria) y PostgreSQL (encuestas, emociones, juegos). Lo que falle va a `failed/`.
- Cada respuesta de la IA lee: resumen de memoria a largo plazo + perfil + últimas encuestas y alertas + emociones + juegos + recuerdos relacionados buscados en TODO el historial + conocimiento psicológico + últimos 30 mensajes.
- Cada ~14 mensajes nuevos se actualiza el resumen del estudiante (nada se borra: el historial completo sigue guardado).

## Voz
Pestaña "Voz con IA": usa el reconocimiento de voz del navegador (Chrome/Edge/Safari) y responde con la voz del sistema; funciona con cualquier proveedor. Si el navegador no tiene reconocimiento, graba audio y lo transcribe con Gemini.

## IA separada por servicio
- `.env.chat` (copia de `.env.chat.example`): Gemini, OpenAI/GPT y Groq, solo para el chat y su memoria.
- `.env.etl` (copia de `.env.etl.example`): Qwen y DeepSeek, solo para el ETL.
- Varias keys por proveedor separadas por coma; se rotan solas si una se agota.
- Cambias de keys con `docker compose up -d --force-recreate chat etl`.

## Novedades v2
- **Juegos → datalake → ETL:** cada partida (juego, tiempo, si la completó y **lo que el estudiante escribe** en las cajas de texto) cae en `raw/game/<usuario>/…`. El ETL (Qwen/DeepSeek) lo estructura (emoción, problemas, datos personales) y lo guarda en PostgreSQL (`game_plays`, `emotion_log`) y MongoDB (`game_responses`, `profiles`). El catálogo está en `services/games/games.json`.
- **Sonidos:** efectos generados con WebAudio (sin archivos), botón 🔊/🔇 en cada juego. Respiración con cuenta regresiva y sonido de inhalar/sostener/exhalar.
- **Voces:** 3 de mujer (Aoede, Sulafat, Leda) y 3 de hombre (Achird, Puck, Iapetus) con Gemini TTS, elegibles en *Personalizar* (usa las keys de Gemini de `.env.chat`). Por defecto solo Gemini TTS (y la voz del navegador si Gemini falla). Respaldo opcional con OpenAI TTS: `TTS_ORDER=gemini,openai`. Groq no tiene voz en español.
- **Personalización de la IA:** voz, tono (amigo/calmado/motivador/formal), largo, nombre e intereses por usuario (`/api/chat/prefs`), más adaptación automática según emociones, juegos y encuestas.
- **Encuestas:** `shared/questions.json` (diagnóstica inicial 33 preguntas, parciales 13, check-in 6). Puntajes por dimensión calculados en el ETL. Periodos: `EXAM_WEEKS` y `EXAM_LEAD_DAYS`. Verifica en `/api/survey/schedule`.
- **Conocimiento:** 47 archivos `.json` en `services/seed/knowledge/` (30 temas, 16 técnicas, recursos). Se suben al datalake con `docker compose run --rm seed`. Recursos de la app: `frontend/recursos.json`.
- **Bóveda por usuario:** toda lectura/escritura en MongoDB, PostgreSQL y el datalake S3 está acotada al correo de la sesión (JWT); el prompt de la IA le prohíbe mezclar datos. Antes de desplegar: cambia `JWT_SECRET`, usa HTTPS y `COOKIE_SECURE=1`.

## Novedades v3
- **Juegos interactivos nuevos:** Planea tu parcial (temas, dificultad, plan de bloques y temporizador), Balanza de pensamientos, Círculo de control, Escáner corporal (con guía) y Jardín de gratitud. Todo lo que escribes/eliges se guarda en el datalake para el ETL.
- **Sonido:** motor nuevo (campanas, soplidos de aire, burbujas) más fuerte y con compresor.
- **Técnicas:** cada una con ilustración animada, pasos que se marcan, ejemplo y botón "Practicar ahora" (abre el juego que la practica) o "Practicar con SerenIA".
- **Menos espera en la voz:** contexto en paralelo, el juego sugerido se pide aparte, la voz se pide por frases y la combinación de TTS que funciona se recuerda.

## Seguridad y cumplimiento (v4)
Lee **SECURITY.md**: pasos para publicar con HTTPS, tabla de cumplimiento punto por punto y lo que debes decidir tú. Pruebas: `pip install pytest mongomock -r requirements.txt && pytest -q tests`.
