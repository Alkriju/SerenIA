# Licencias de terceros — SerenIA

Última revisión: 2026-11-17 (hecha con `pip-licenses` y `pip-audit`; repetir en cada actualización de dependencias).

## Código propio
El código de SerenIA, sus textos (recursos, conocimiento del datalake, juegos), los íconos (SVG dibujados en el propio `index.html`) y los sonidos (sintetizados con WebAudio en el navegador) son obra propia del equipo: no incluyen imágenes, audios, logos ni íconos de terceros.

## Fuente tipográfica
| Recurso | Licencia | Dónde |
|---|---|---|
| Plus Jakarta Sans © 2020 The Plus Jakarta Sans Project Authors | SIL Open Font License 1.1 (permite uso comercial y redistribución con el aviso) | `frontend/fonts/` (texto completo en `frontend/fonts/OFL.txt`) |

Se sirve desde el propio servidor (no desde Google Fonts), así no se envía la IP de los visitantes a terceros.

## Dependencias de Python (`requirements.txt`)
Todas con licencias permisivas (MIT, BSD, Apache-2.0, ISC, PSF), salvo estas dos, que se usan **sin modificar** y cumplen sus condiciones:
- **psycopg2-binary — LGPL**: se usa como librería externa sin modificarla; el usuario puede reemplazarla (está declarada en `requirements.txt`). No obliga a abrir el código de SerenIA.
- **certifi — MPL 2.0**: se usa sin modificar; el código fuente de certifi está disponible públicamente (https://github.com/certifi/python-certifi).

| Name                 | Version     | License                                             | URL                                                                                |
|----------------------|-------------|-----------------------------------------------------|------------------------------------------------------------------------------------|
| requests             | 2.34.2      | Apache Software License                             | https://github.com/psf/requests                                                    |
| s3transfer           | 0.19.3      | Apache Software License                             | https://github.com/boto/s3transfer                                                 |
| python-dateutil      | 2.9.0.post0 | Apache Software License; BSD License                | https://github.com/dateutil/dateutil                                               |
| boto3                | 1.44.5      | Apache-2.0                                          | https://github.com/boto/boto3                                                      |
| botocore             | 1.44.5      | Apache-2.0                                          | https://github.com/boto/botocore                                                   |
| opentelemetry-api    | 1.45.2      | Apache-2.0                                          | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-api |
| pymongo              | 4.20.0      | Apache-2.0                                          | https://www.mongodb.org                                                            |
| cryptography         | 50.0.2      | Apache-2.0 OR BSD-3-Clause                          | https://github.com/pyca/cryptography                                               |
| httpx                | 0.28.1      | BSD License                                         | https://github.com/encode/httpx                                                    |
| click                | 8.5.1       | BSD-3-Clause                                        | https://github.com/pallets/click/                                                  |
| httpcore             | 1.0.9       | BSD-3-Clause                                        | https://www.encode.io/httpcore/                                                    |
| idna                 | 3.20        | BSD-3-Clause                                        | https://github.com/kjd/idna                                                        |
| pycparser            | 3.12        | BSD-3-Clause                                        | https://github.com/eliben/pycparser                                                |
| starlette            | 1.10.0      | BSD-3-Clause                                        | https://github.com/Kludex/starlette                                                |
| uvicorn              | 0.54.0      | BSD-3-Clause                                        | https://uvicorn.dev/                                                               |
| psycopg2-binary      | 2.9.13      | GNU Library or Lesser General Public License (LGPL) | https://psycopg.org/                                                               |
| dnspython            | 2.9.2       | ISC                                                 | https://www.dnspython.org                                                          |
| PyJWT                | 2.15.1      | MIT                                                 | https://github.com/jpadilla/pyjwt                                                  |
| annotated-doc        | 0.0.6       | MIT                                                 | https://github.com/fastapi/annotated-doc                                           |
| annotated-types      | 0.8.0       | MIT                                                 | https://github.com/annotated-types/annotated-types                                 |
| anyio                | 4.16.0      | MIT                                                 | https://anyio.readthedocs.io/en/stable/versionhistory.html                         |
| argon2-cffi          | 25.1.0      | MIT                                                 | https://github.com/hynek/argon2-cffi/blob/main/CHANGELOG.md                        |
| argon2-cffi-bindings | 26.2.0      | MIT                                                 | https://github.com/hynek/argon2-cffi-bindings/blob/main/CHANGELOG.md               |
| charset-normalizer   | 3.5.2       | MIT                                                 | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md               |
| fastapi              | 0.163.2     | MIT                                                 | https://github.com/fastapi/fastapi                                                 |
| pydantic             | 2.14.3      | MIT                                                 | https://github.com/pydantic/pydantic                                               |
| pydantic_core        | 2.50.4      | MIT                                                 | https://github.com/pydantic                                                        |
| typing-inspection    | 0.4.5       | MIT                                                 | https://github.com/pydantic/typing-inspection                                      |
| urllib3              | 2.8.0       | MIT                                                 | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst                           |
| h11                  | 0.16.0      | MIT License                                         | https://github.com/python-hyper/h11                                                |
| jmespath             | 1.1.0       | MIT License                                         | https://github.com/jmespath/jmespath.py                                            |
| msal                 | 1.39.0      | MIT License                                         | https://github.com/AzureAD/microsoft-authentication-library-for-python             |
| six                  | 1.17.0      | MIT License                                         | https://github.com/benjaminp/six                                                   |
| cffi                 | 2.1.1       | MIT-0                                               | https://cffi.readthedocs.io/en/latest/whatsnew.html                                |
| certifi              | 2026.10.23  | Mozilla Public License 2.0 (MPL 2.0)                | https://github.com/certifi/python-certifi                                          |
| typing_extensions    | 4.16.0      | PSF-2.0                                             | https://github.com/python/typing_extensions                                        |

## Imágenes de contenedores (infraestructura)
| Componente | Licencia | Qué implica para SerenIA |
|---|---|---|
| nginx | BSD-2-Clause | Sin restricciones. |
| Caddy | Apache-2.0 | Sin restricciones. |
| MongoDB 7 | SSPL | Se usa como base de datos interna. La SSPL solo exige abrir el código si se ofrece MongoDB **como servicio a terceros**; no es el caso. |
| SeaweedFS (`chrislusf/seaweedfs`) | Apache-2.0 | Datalake S3 **solo para desarrollo local**; sustituye a MinIO (archivado, AGPL). Sin restricciones. |
| PostgreSQL 16 | PostgreSQL License (permisiva) | Base SQL local; sustituye a CockroachDB (licencia propietaria). Sin restricciones. |

## Cómo mantener esto al día
1. `pip install -r requirements.in && pip freeze > requirements.txt` para actualizar.
2. `pip-audit -r requirements.txt` — debe decir "No known vulnerabilities found".
3. `pip-licenses --format=markdown` y revisar que no entre ninguna licencia incompatible.


## Servicios en la nube (despliegue en Vercel)
Estos servicios no se distribuyen con el código; se contratan bajo sus propios términos. **Revisa que el plan gratuito permita tu uso:**
| Servicio | Plan | Nota |
|---|---|---|
| Vercel | Hobby | Los términos de Vercel limitan Hobby a uso **personal y no comercial**. Un proyecto académico encaja; un servicio público de una empresa necesita plan Pro. |
| Neon | Free | PostgreSQL gestionado. |
| MongoDB Atlas | M0 (gratis) | Gestionado por MongoDB, Inc.; el aviso SSPL no aplica al usarlo como servicio contratado. |
| Cloudflare R2 | Gratis (10 GB) | Almacenamiento S3. Pide tarjeta/método de pago para activar R2 (no cobra dentro del nivel gratis). |
| GitHub | Free | Código y Actions. |
