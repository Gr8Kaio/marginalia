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
| `Ctrl/Cmd + E` | Alternar Escribir / Leer |
| `Ctrl/Cmd + S` | Forzar guardado |
| `Esc` | Cerrar hoja o foto ampliada |

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

create index on notes (user_id, updated_at);
create index on subjects (user_id, updated_at);
create index on images (user_id, updated_at);

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

*Project Settings → API* tiene los dos valores. En Marginalia: ⚙️ → pegar **Project
URL** y **anon public key** → email y contraseña → **Crear cuenta**.

Supabase manda un mail de confirmación. Confirmás una vez, volvés y hacés *Iniciar
sesión*. (Si preferís saltear ese paso: *Authentication → Providers → Email* →
apagar *Confirm email*.)

En el segundo dispositivo repetís sólo el paso 4 con la misma cuenta.

### Cómo resuelve conflictos

Last-write-wins por `updated_at`, con tombstones (`deleted = 1`) para que los
borrados también viajen. Si editás el mismo apunte en dos lados sin sincronizar en
el medio, gana el que se guardó último. Para apuntes de clase es el comportamiento
correcto: el riesgo real no es el conflicto, es perder lo que escribiste.

Las fotos suben una sola vez a `marginalia-img/<user-id>/<image-id>.jpg` y después
sólo viaja la fila de metadatos.

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
