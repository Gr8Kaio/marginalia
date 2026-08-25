# Marginalia

PWA para tomar apuntes por materia en la facu. Markdown con vista previa, fotos del
pizarrón, buscador global y sincronización opcional entre el celu y la notebook.

**En vivo:** https://gr8kaio.github.io/marginalia/

## Cómo funciona

Todo vive en **IndexedDB**, en el dispositivo. La app abre y escribe sin señal —
en un aula el wifi no existe, así que offline no es un extra, es la base. La
sincronización es una capa encima: si está apagada, la app funciona igual.

- **Materias** con color propio; el color arrastra a todos los apuntes de esa cátedra.
- **Markdown** con parser propio (sin librerías, sin CDN): títulos, listas, listas
  anidadas, tareas `- [ ]`, citas, tablas, bloques de código, `**negrita**`,
  `*cursiva*`, `~~tachado~~`, `==resaltado==` y links.
- **Fotos del pizarrón**: el botón de cámara abre la cámara directo en el celu.
  Cada foto se reescala a 1600 px y se guarda como JPEG q0.72 (~150–300 KB) antes
  de tocar el disco. También se pueden pegar con Ctrl+V.
- **Buscador** sobre título y cuerpo de todos los apuntes, insensible a acentos
  (`analisis` encuentra `Análisis`), con el término resaltado en el resultado.
- **Autoguardado** a los 700 ms de dejar de escribir, más un flush al salir de la
  pestaña y al cerrarla. No hay botón de guardar porque no hace falta.
- Tema claro y oscuro; sigue al sistema y se puede forzar con el botón del sol.

### Atajos

| Tecla | Acción |
| --- | --- |
| `Ctrl/Cmd + B` | Negrita |
| `Ctrl/Cmd + I` | Cursiva |
| `Ctrl/Cmd + E` | Alternar Escribir / Leer (el mismo botón de la barra) |
| `Ctrl/Cmd + S` | Forzar guardado |
| `Esc` | Cerrar hoja o foto ampliada |

Escribir y leer son **un solo botón**, que nombra a dónde vas: dice *Leer* mientras
escribís y *Escribir* mientras leés. Leyendo desaparece la barra de markdown, que
ahí no hace nada.

En pantallas de 1000 px o más el editor se parte en dos: escribís a la izquierda,
la vista previa se actualiza a la derecha.

## Sincronizar entre dispositivos

Opcional. Sin esto la app anda perfecto, pero los apuntes se quedan en un solo
lugar. Usa **Supabase** (plan gratis: 500 MB de base + 1 GB de archivos, de sobra
para varios años de fotos de pizarrón).

### 1. Crear el proyecto

En [supabase.com](https://supabase.com) → *New project*. Anotá la contraseña de la
base aunque no la vayas a usar acá.

### 2. Crear las tablas

*SQL Editor* → pegar y correr:

```sql
create table subjects (
  id text primary key,
  user_id uuid not null references auth.users on delete cascade,
  name text not null default '',
  hue int not null default 210,
  deleted int not null default 0,
  created_at timestamptz default now(),
  updated_at timestamptz not null default now()
);

create table notes (
  id text primary key,
  user_id uuid not null references auth.users on delete cascade,
  subject_id text,
  title text not null default '',
  body text not null default '',
  pinned int not null default 0,
  deleted int not null default 0,
  created_at timestamptz default now(),
  updated_at timestamptz not null default now()
);

create table images (
  id text primary key,
  user_id uuid not null references auth.users on delete cascade,
  note_id text,
  path text,
  deleted int not null default 0,
  updated_at timestamptz not null default now()
);

-- updated_at es la hora del dispositivo que escribió (resuelve conflictos).
-- pushed_at es la hora del servidor al recibir la fila (marca de agua del pull).
-- Tienen que ser dos columnas distintas: un apunte de ayer que recién hoy sube
-- desde el celu llega con updated_at viejo, y si el pull filtrara por eso el
-- otro dispositivo no lo bajaría nunca.
alter table subjects add column pushed_at timestamptz not null default now();
alter table notes    add column pushed_at timestamptz not null default now();
alter table images   add column pushed_at timestamptz not null default now();

create or replace function touch_pushed_at() returns trigger as $$
begin new.pushed_at = now(); return new; end;
$$ language plpgsql;

create trigger pushed_at_subjects before insert or update on subjects
  for each row execute function touch_pushed_at();
create trigger pushed_at_notes before insert or update on notes
  for each row execute function touch_pushed_at();
create trigger pushed_at_images before insert or update on images
  for each row execute function touch_pushed_at();

create index on notes    (user_id, pushed_at);
create index on subjects (user_id, pushed_at);
create index on images   (user_id, pushed_at);

-- Cada quien ve y toca sólo lo suyo. Esto es lo que protege los datos:
-- la anon key es pública por diseño, RLS es la cerradura real.
alter table subjects enable row level security;
alter table notes    enable row level security;
alter table images   enable row level security;

create policy "own subjects" on subjects for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own notes" on notes for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own images" on images for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);
```

### 3. Crear el bucket de fotos

*Storage* → *New bucket* → nombre exacto **`marginalia-img`**, dejarlo **privado**.
Después, otra vez en *SQL Editor*:

```sql
create policy "own files read" on storage.objects for select
  using (bucket_id = 'marginalia-img' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "own files write" on storage.objects for insert
  with check (bucket_id = 'marginalia-img' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "own files update" on storage.objects for update
  using (bucket_id = 'marginalia-img' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "own files delete" on storage.objects for delete
  using (bucket_id = 'marginalia-img' and (storage.foldername(name))[1] = auth.uid()::text);
```

### 4. Conectar la app

*Project Settings → API Keys* tiene los dos valores. En Marginalia: ⚙️ → pegar
**Project URL** y la **clave pública** (`sb_publishable_…` en los proyectos nuevos,
o la vieja `anon` que arranca con `eyJ…`) → email y contraseña → **Crear cuenta**.

⚠️ La otra clave — *secret* / `service_role` — **nunca** va acá: saltea RLS y
quedaría a la vista de cualquiera que abra la app.

Supabase manda un mail de confirmación. Confirmás una vez, volvés y hacés *Iniciar
sesión*. (Si preferís saltear ese paso: *Authentication → Providers → Email* →
apagar *Confirm email*.)

En el segundo dispositivo repetís sólo el paso 4 con la misma cuenta.

### Cómo resuelve conflictos

Last-write-wins por `updated_at`, con tombstones (`deleted = 1`) para que los
borrados también viajen. Si editás el mismo apunte en dos lados sin sincronizar en
el medio, gana el que se guardó último. Para apuntes de clase es el comportamiento
correcto: el riesgo real no es el conflicto, es perder lo que escribiste.

Las dos columnas de tiempo cumplen roles distintos y no son intercambiables.
`updated_at` viene del dispositivo y decide **quién gana**. `pushed_at` lo pone el
servidor y decide **qué falta bajar**: cada dispositivo guarda la última marca que
vio y pide `pushed_at >= esa marca`, con 60 segundos de margen para tolerar relojes
desfasados. Volver a bajar una fila que ya se tenía no cuesta nada — el merge la
descarta comparando `updated_at`.

Las fotos suben una sola vez a `marginalia-img/<user-id>/<image-id>.jpg` y después
sólo viaja la fila de metadatos.

## El widget del escritorio (Windows)

La misma app, encogida en una ventanita sin bordes que se queda arriba de todo:
escribís algo al vuelo, lo guardás, y aparece en el celu como cualquier otro
apunte. Abajo tiene el buscador de siempre y arriba los últimos apuntes tocados.

No es una segunda app: es `index.html?widget=1` adentro de un WebView2. Los
datos, el login, el sync y el editor son exactamente el mismo código. Lo único
que agrega `desktop/widget.py` es lo que una página web no puede hacer sola en
Windows — quedarse encima, un atajo global, un icono en la bandeja y una
posición que sobrevive al reinicio.

```powershell
powershell -ExecutionPolicy Bypass -File desktop\instalar.ps1
```

Eso instala `pywebview`, `pystray` y `pillow`, arma el icono y deja dos accesos
directos: uno en el Escritorio y otro en el arranque de Windows (`-SinInicio` si
no lo querés al prender la PC, `-Desinstalar` para sacar los dos).

| | |
| --- | --- |
| **Ctrl+Alt+N** | mostrar u ocultar el widget desde cualquier lado |
| **Ctrl+Enter** | guardar lo que escribiste |
| **⚓** | anclar al escritorio (ver abajo) |
| **−** | colapsar: queda sólo la barra del título |
| **×** | guardarlo en la bandeja (no cierra nada) |
| **↗** | abrir la app entera en el navegador |

### El ancla

Por defecto el widget flota arriba de todo. Un click en el ancla lo manda al
**fondo del orden de ventanas**: deja de tapar cosas, sale de Alt+Tab, y Win+D lo
deja donde está en vez de minimizarlo (eso último es gracias al estilo
*tool window*). Otro click lo suelta. Se sigue usando igual que siempre: lo
clickeás, escribís, guardás; cuando pasás a otra ventana, vuelve al fondo solo.

Ese "vuelve solo" es un hook de `EVENT_SYSTEM_FOREGROUND`: cada vez que otra
ventana pasa al frente, la nuestra se rehunde. Sin eso el anclaje duraría hasta el
primer click, porque usar el widget lo activa y lo sube — que es justo lo que uno
quiere *mientras* escribe.

**Lo que no es.** El primer intento fue colgar la ventana del escritorio con
`SetParent` al `Progman`, como los fondos animados: se veía perfecto, pero Windows
no le manda ni un `mousedown` ni una tecla a lo que vive en esa capa, y forzar el
foco tampoco alcanza (probado, no supuesto). Un widget de notas donde no se puede
escribir no sirve, así que quedó el camino de arriba.

El ancla también está en el menú del icono de la bandeja.

La primera línea de lo que escribís es el título y el resto el cuerpo. Se guarda
en la materia del desplegable, que arranca en *Inbox* y se acuerda de la última
que usaste.

**La primera vez hay que iniciar sesión desde el engranaje.** El widget tiene su
propio perfil de navegador (`%LOCALAPPDATA%\Marginalia\webview`), así que para el
sync es un dispositivo más: entra con la misma cuenta y baja todo.

Lo que se puede tocar sin abrir el código está en
`%LOCALAPPDATA%\Marginalia\widget.json` — la URL que carga, el atajo, si va
siempre encima, y el tamaño y la posición de la ventana:

```json
{ "url": "https://gr8kaio.github.io/marginalia/?widget=1",
  "hotkey": "ctrl+alt+n", "on_top": true,
  "x": 1506, "y": 132, "width": 340, "height": 560 }
```

Hay un solo widget por vez: abrir el acceso directo cuando ya está andando no
levanta otro, hace aparecer el que había. (Dos instancias no molestan por la
ventana repetida sino por el atajo, que se lo queda el que llegó primero.) Como
los accesos directos abren con `pythonw.exe`, que no tiene consola, lo que pasa
queda anotado en `%LOCALAPPDATA%\Marginalia\widget.log`.

Para probar cambios sin publicarlos, `py desktop\widget.py --local` levanta el
`index.html` de al lado en `127.0.0.1:8731` (siempre el mismo puerto: si cambiara,
sería otro origen y otra base de datos en cada arranque).

## El nombre

*Marginalia* son las notas que los lectores escriben en los márgenes de un libro —
lo que se te ocurre mientras alguien más habla. Que es exactamente lo que es esto.

## Copias de seguridad

⚙️ → *Exportar* baja un `.json` con materias, apuntes y fotos en base64. *Importar*
lo mezcla con lo que ya haya (gana la versión más nueva de cada cosa, nunca pisa a
ciegas). Conviene exportar cada tanto aunque tengas sync activo.

## Desarrollo

Un solo archivo, sin build, sin dependencias.

```bash
python -m http.server 8000    # el service worker necesita http, no file://
```

`sw.js` cachea el shell y deja pasar todo lo de Supabase directo a la red. **Al
publicar un cambio hay que subir `CACHE` en `sw.js` y `VERSION` en `index.html`**,
si no los dispositivos siguen sirviendo la versión vieja desde el cache.
