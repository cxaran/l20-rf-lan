# Guía de uso

Ejecuta los comandos desde la carpeta del proyecto en PowerShell. Todos usan el Python del entorno virtual, sin necesidad de activarlo. Usa una sola instancia del programa: cierra la web con `Ctrl+C` antes de ejecutar `capture` o `send` desde otra consola. La exclusión de operaciones dentro de una instancia no coordina procesos distintos.

## Preparar el equipo y las credenciales

1. Configura el L20 con la aplicación que corresponda a su variante. Comprueba en su documentación la banda Wi-Fi admitida; algunos equipos requieren 2.4 GHz. La PC puede estar conectada por Ethernet o por otra banda del mismo router siempre que alcance directamente al L20 en la misma subred.
2. Consulta en el router la IP y la MAC del L20. Reserva su IP mediante DHCP para que no cambie al reiniciar. Comprueba que el router permita comunicación entre clientes; una red de invitados o una VLAN separada puede impedirla.
3. Obtén el `device_id` y la `local_key` del equipo fuera de esta aplicación. No confundas la clave local del dispositivo con la clave API del proyecto de Tuya.

Una ruta documentada es el [Setup Wizard de TinyTuya 1.20.0](https://github.com/jasonacox/tinytuya/blob/v1.20.0/README.md#setup-wizard---getting-local-keys): vincula la cuenta de la aplicación a un proyecto de Tuya IoT, autoriza los servicios correspondientes y ejecuta el asistente. Este obtiene los campos `id` y `key` para los dispositivos vinculados. Sigue la guía original para región, permisos y cambios del portal.

Si necesitas ese asistente, ejecútalo dentro de una carpeta privada después de instalar el proyecto:

```powershell
New-Item -ItemType Directory -Force .private | Out-Null
Push-Location .private
..\.venv\Scripts\python.exe -m tinytuya wizard
Pop-Location
```

El asistente se comunica con servicios de Tuya y puede crear archivos de configuración y dispositivos en texto claro. Es una herramienta independiente de este proyecto. No publiques esos archivos. El funcionamiento LAN posterior de este proyecto usa la credencial local guardada; no llama al asistente ni solicita claves API de la nube.

## Instalar

Con Python 3.10 o superior instalado:

```powershell
.\Instalar.ps1
```

El instalador prepara `.venv` e instala las dependencias de `requirements.txt`, que fija TinyTuya 1.20.0. Si la política de PowerShell bloquea su ejecución, puedes invocarlo con una excepción limitada a ese proceso, sin cambiar la política permanente:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Instalar.ps1
```

También puedes instalar manualmente:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Comprueba que el intérprete elegido sea 3.10 o posterior con `py -3 --version`.

## Configurar

```powershell
.\.venv\Scripts\python.exe .\l20.py configure
.\.venv\Scripts\python.exe .\l20.py info
```

Introduce la IP y MAC del L20 y sus credenciales. `device_id` y `local_key` no se muestran al escribirlos. La configuración se cifra con DPAPI; no se prueba la conexión al guardar ni al ejecutar `info`. El protocolo de este proyecto es fijo: Tuya 3.3, TCP 6668.

Para sustituir una configuración existente de forma explícita:

```powershell
.\.venv\Scripts\python.exe .\l20.py configure --replace
```

`--credentials` y `--data` son opciones globales y van **antes** del subcomando. Por ejemplo, para mantener otra configuración y otra biblioteca:

```powershell
.\.venv\Scripts\python.exe .\l20.py --credentials .private\otro-l20.dpapi --data datos-otro\capturas configure
```

Usa los mismos parámetros globales en los comandos posteriores de ese equipo. Los directorios predeterminados se resuelven respecto de la carpeta del proyecto.

## Usar la interfaz web

```powershell
.\Iniciar.cmd
```

También puedes iniciarla directamente, elegir puerto o impedir que abra el navegador:

```powershell
.\.venv\Scripts\python.exe .\l20.py web --port 58745 --no-browser
```

Abre la dirección local que imprime la consola. El estado de credencial lista indica que Windows pudo leer la configuración; no es una comprobación de conectividad con el L20.

1. Elige frecuencia automática o 433.92 MHz y pulsa **Capturar**. Durante la escucha, pulsa el botón del control cerca del L20.
2. Cuando llegue un código, asigna nombre y notas y pulsa **Guardar captura**. Recibir una captura no la guarda automáticamente en la biblioteca de la web.
3. Selecciona una captura guardada para editarla. Puedes alternar entre Base64 y JSON y validar el formato antes de guardar. Validar no transmite.
4. Para una prueba física, elige entre una y seis repeticiones y pulsa **Probar código**. Se transmite el código que aparece en el editor, incluso si sus cambios aún no están guardados.
5. Revisa el resultado y registra en el historial si funcionó físicamente. La observación la declara la persona operadora; el programa no tiene un sensor de posición del portón.

El modo `web --demo` utiliza datos sintéticos y almacenamiento de demostración. No requiere credenciales y no conecta con el L20. La web real usa HTTP solo dentro de la PC, en la interfaz de loopback. No debe publicarse mediante un proxy como servicio remoto.

## Capturar desde consola

Detén la web antes de iniciar una operación de consola:

```powershell
.\.venv\Scripts\python.exe .\l20.py capture --name "Botón principal" --frequency 0 --seconds 30
.\.venv\Scripts\python.exe .\l20.py list
```

`--frequency` acepta `0` —automática— o `433.92`; la escucha admite de 1 a 120 segundos. A diferencia de la web, el comando `capture` guarda el código recibido directamente en la biblioteca cifrada con el nombre indicado. Conserva el identificador que devuelve. Un reporte válido recibido durante aprendizaje puede contener datos anteriores; comprueba que corresponda al botón esperado.

## Exportar, editar, validar e importar

Sustituye el identificador por uno mostrado por `list`:

```powershell
$id = "ID_DE_LA_CAPTURA"
.\.venv\Scripts\python.exe .\l20.py export $id --output .private\codigo.txt
.\.venv\Scripts\python.exe .\l20.py validate --file .private\codigo.txt
```

`export` crea un archivo nuevo de texto sin cifrar y no sobrescribe uno existente. El contenido RF puede servir para accionar el equipo: trátalo como información sensible. Puedes editarlo con un editor de texto. `validate` acepta Base64 o un objeto JSON RF v2 y comprueba el formato localmente.

Para guardar una captura nueva a partir de ese archivo:

```powershell
.\.venv\Scripts\python.exe .\l20.py save --name "Botón importado" --file .private\codigo.txt
```

Para editar el registro existente en lugar de crear otro:

```powershell
.\.venv\Scripts\python.exe .\l20.py save --id $id --name "Botón principal revisado" --file .private\codigo.txt
```

Guardar o validar un archivo no transmite RF. La opción `save --notes "Texto de las notas"` permite cambiar también las notas; si la omites al editar, se conservan las anteriores. La web ofrece esos mismos campos en el editor. Un cambio del código elimina la confirmación física asociada a la versión anterior de esa captura.

## Transmitir

```powershell
.\.venv\Scripts\python.exe .\l20.py send $id
.\.venv\Scripts\python.exe .\l20.py send $id --times 2
```

Cada ejecución es una acción manual nueva. El valor predeterminado es una repetición y se admiten de una a seis dentro de la orden enviada al L20. No hay reintentos automáticos por fallo o falta de respuesta. Ante `UNCERTAIN`, observa el resultado antes de volver a ejecutar el comando. La cantidad de repeticiones adecuada depende de tu control y receptor; el software no puede deducirla de una confirmación TCP.

## Archivos y traslado

La configuración se guarda en `.private/l20.dpapi`; cada captura se guarda como un archivo `.dpapi` en `datos/capturas/`. La web conserva además un historial local de ensayos en la carpeta de datos. No contiene una medición independiente del movimiento físico.

Copiar los archivos DPAPI a otra PC o cuenta no garantiza poder descifrarlos. Para migrar una captura, expórtala desde el entorno original e impórtala en el nuevo; vuelve a introducir las credenciales mediante `configure`. Evita incluir configuración, bibliotecas, exportaciones e historial operativo en un repositorio público.
