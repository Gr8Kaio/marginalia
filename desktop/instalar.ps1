<#
  Deja el widget de Marginalia listo para usar.

  Instala lo que falte, arma el icono, y crea dos accesos directos: uno en el
  Escritorio y otro en la carpeta de Inicio para que el widget aparezca solo
  cuando prendes la PC. Apunta a pythonw.exe a proposito -- con python.exe
  quedaria una ventana negra de consola abierta al lado del widget.

      powershell -ExecutionPolicy Bypass -File desktop\instalar.ps1
      ... -SinInicio      no lo agrega al arranque de Windows
      ... -Desinstalar    saca los accesos directos (no toca tus apuntes)
#>
param(
    [switch]$SinInicio,
    [switch]$Desinstalar
)

$ErrorActionPreference = "Stop"
$repo    = Split-Path -Parent $PSScriptRoot
$script  = Join-Path $PSScriptRoot "widget.py"
$icono   = Join-Path $PSScriptRoot "marginalia.ico"
$escrit  = Join-Path ([Environment]::GetFolderPath("Desktop")) "Marginalia.lnk"
$inicio  = Join-Path ([Environment]::GetFolderPath("Startup")) "Marginalia.lnk"

if ($Desinstalar) {
    foreach ($lnk in @($escrit, $inicio)) {
        if (Test-Path $lnk) { Remove-Item $lnk -Force; "borrado: $lnk" }
    }
    "Listo. Los apuntes y la sesion siguen donde estaban ($env:LOCALAPPDATA\Marginalia)."
    return
}

# --- python y dependencias ---------------------------------------------------
$pythonw = & py -c "import sys, os; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))"
if (-not (Test-Path $pythonw)) { throw "No encontre pythonw.exe (busque en $pythonw)" }
"python:  $pythonw"

"instalando dependencias..."
& py -m pip install --quiet --user --disable-pip-version-check pywebview pystray pillow
if ($LASTEXITCODE -ne 0) { throw "pip fallo" }

# --- icono -------------------------------------------------------------------
$png = Join-Path $repo "apple-touch-icon.png"
if (Test-Path $png) {
    $gen = "from PIL import Image; im = Image.open(r'$png'); " +
           "im.save(r'$icono', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
    & py -c $gen
    if ($?) { "icono:   $icono" }
}

# --- accesos directos --------------------------------------------------------
function Nuevo-Acceso($ruta, $argumentos) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($ruta)
    $lnk.TargetPath       = $pythonw
    $lnk.Arguments        = '"' + $script + '" ' + $argumentos
    $lnk.WorkingDirectory = $repo
    $lnk.Description      = "Marginalia: apuntes a mano en el escritorio"
    if (Test-Path $icono) { $lnk.IconLocation = $icono }
    $lnk.Save()
    "acceso:  $ruta"
}

Nuevo-Acceso $escrit ""

if ($SinInicio) {
    if (Test-Path $inicio) { Remove-Item $inicio -Force; "saque el del arranque" }
} else {
    Nuevo-Acceso $inicio ""
}

""
"Listo. Abrilo desde el Escritorio, o con el atajo Ctrl+Alt+N una vez que este andando."
"La primera vez entra con tu cuenta desde el engranaje para que sincronice con el celu."
