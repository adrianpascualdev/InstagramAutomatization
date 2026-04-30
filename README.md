# Instagram Scheduler para Render + Cloudinary

Panel web para programar vídeos/Reels de Instagram usando:

- Render Free Web Service
- Cloudinary Free para alojar los vídeos con URL pública
- Instagram Graph API oficial
- cron-job.org gratis para ejecutar el publicador periódicamente

## Importante sobre “todo gratis”

Render Free Web Services pueden dormirse tras inactividad. Por eso este proyecto NO depende de un scheduler interno permanente: usa `/api/cron`, que puedes llamar gratis desde cron-job.org cada 1-5 minutos. Render se despierta con esa llamada y procesa publicaciones vencidas.

Render Cron Jobs oficiales son de pago. Cloudinary tiene plan Free, mientras no superes sus límites.

## Requisitos

1. Cuenta Instagram Business o Creator.
2. Instagram vinculada a una página de Facebook.
3. App en Meta Developers con permisos de publicación.
4. Token válido con permiso `instagram_content_publish`.
5. Cuenta gratis de Cloudinary.
6. Cuenta gratis de Render.
7. Cuenta gratis de cron-job.org.

## Variables de entorno en Render

Configura estas variables:

```env
ADMIN_PASSWORD=una_contraseña_para_tu_panel
CRON_SECRET=un_texto_largo_secreto
IG_USER_ID=tu_instagram_business_account_id
IG_ACCESS_TOKEN=tu_token_de_meta
CLOUDINARY_CLOUD_NAME=tu_cloud_name
CLOUDINARY_API_KEY=tu_api_key
CLOUDINARY_API_SECRET=tu_api_secret
TZ=Europe/Madrid
```

Opcional recomendado si usas Render Postgres:

```env
DATABASE_URL=postgresql://...
```

Si no pones `DATABASE_URL`, usará SQLite. Para pruebas vale, pero en Render es mejor usar Postgres para no perder datos en redeploys.

## Deploy en Render

1. Sube este proyecto a GitHub.
2. En Render: New → Web Service.
3. Conecta tu repo.
4. Build command:

```bash
pip install -r requirements.txt
```

5. Start command:

```bash
gunicorn app:app --workers 1 --threads 8 --timeout 120
```

6. Añade las variables de entorno.
7. Deploy.

## Configurar cron-job.org

Crea un cron job que llame cada minuto o cada 5 minutos a:

```text
https://TU-APP.onrender.com/api/cron?secret=TU_CRON_SECRET
```

Ese endpoint revisa posts vencidos, crea el contenedor de Instagram, espera a que Meta termine de procesar el vídeo y lo publica en una llamada posterior.

## Uso

1. Abre tu URL de Render.
2. Entra con `ADMIN_PASSWORD`.
3. Sube un vídeo.
4. Escribe caption.
5. Elige fecha/hora.
6. El cron lo publicará automáticamente cuando toque.

## Notas

- Instagram necesita que el vídeo esté en una URL pública HTTPS. Cloudinary resuelve eso.
- El vídeo puede tardar en procesarse en Meta; por eso el estado puede pasar por `processing` antes de `published`.
- No uses usuario/contraseña de Instagram. Esta app usa el método oficial con token.
# InstagramAutomatization
