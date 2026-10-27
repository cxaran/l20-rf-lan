# Guía de uso

Ejecuta los comandos desde la carpeta del proyecto en PowerShell. Todos usan el Python del entorno virtual, sin necesidad de activarlo. Usa una sola instancia del programa: cierra la web con `Ctrl+C` antes de configurar o ejecutar `capture` o `send` desde otra consola. La exclusión de operaciones dentro de una instancia no coordina procesos distintos.

## Preparar el equipo y las credenciales

1. Configura el L20 con la aplicación que corresponda a su variante. Comprueba en su documentación la banda Wi-Fi admitida; algunos equipos requieren 2.4 GHz. La PC puede estar conectada por Ethernet o por otra banda del mismo router siempre que alcance directamente al L20 en la misma subred.
2. Consulta en el router la IP y la MAC del L20. Reserva su IP mediante DHCP para que no cambie al reiniciar. Comprueba que el router permita comunicación entre clientes; una red de invitados o una VLAN separada puede impedirla.
3. Elige cómo proporcionar `device_id` y `local_key`: obtenerlos con el asistente desde tu proyecto de Tuya Cloud, importarlos desde un archivo existente o introducirlos manualmente. No confundas la clave local del dispositivo con las claves API del proyecto de Tuya.

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

## Asistente de configuración

Con la instalación terminada, abre:

```powershell
.\IniciarAsistente.cmd
```

Equivale a ejecutar el asistente integrado del proyecto:

```powershell
.\.venv\Scripts\python.exe .\l20.py setup
```

El menú permite elegir **1. Obtener desde Tuya Cloud**, **2. Importar devices.json** o **3. Introducir manualmente**. La consulta Cloud es opcional. Importar e introducir manualmente no requieren acceso a Tuya.

El lanzador también acepta opciones de PowerShell: `-Demo`, `-Replace`, `-FromFile RUTA` y `-CredentialFile RUTA`. Por ejemplo, para importar en un archivo DPAPI alternativo:

```powershell
.\IniciarAsistente.cmd -FromFile .private\devices.json -CredentialFile .private\otro-l20.dpapi
```

Si la web estaba abierta, ciérrala antes de ejecutar el asistente. Cuando termines, abre de nuevo `Iniciar.cmd`: la aplicación lee el estado de la credencial al arrancar.

### Distinguir los datos

| Dato | De dónde procede y para qué se usa |
| --- | --- |
| Access ID / Client ID | Identifica el proyecto de Tuya Cloud; permite autenticar la consulta de configuración junto con su Access Secret. |
| Access Secret / Client Secret | Secreto API del proyecto. Se pide oculto y se utiliza solo en memoria durante la opción Cloud. No es la clave LAN. |
| Región y Device ID de referencia | Dirigen la consulta Cloud hacia el centro de datos y los dispositivos vinculados. El ID de referencia se pide oculto. |
| `device_id` | Identificador del L20 seleccionado. Se guarda dentro de la configuración LAN cifrada. |
| `local_key` | Clave local del L20, de 16 bytes, utilizada para cifrar la comunicación LAN. Se guarda con DPAPI. |
| IPv4 privada y MAC | Dirección y MAC de tu L20, consultadas en el router. Se guardan en la misma configuración para fijar el destino local. |

Los campos de la nube no se añaden a la configuración LAN. No se imprimen claves ni respuestas Cloud completas. El asistente no ejecuta el wizard externo de TinyTuya ni crea sus volcados de credenciales en texto claro.

### Opción 1: obtener desde Tuya Cloud

Primero prepara el proyecto en la plataforma de Tuya:

1. Entra en [Tuya Developer Platform](https://platform.tuya.com/) con tu cuenta de desarrollo. Crea un proyecto con **Development Method: Smart Home**. Según la versión del portal, la gestión aparece en **Cloud > Cloud Project > Project Management** o en **Cloud > Development**. Consulta [Request Tuya Cloud API Key](https://developer.tuya.com/en/docs/developer/apply-cloud-api-key?id=Kff30z8sv62ah).
2. Elige un centro de datos que atienda la región de la cuenta de tu aplicación. No lo deduzcas únicamente por la ubicación de la PC: debes poder ver allí tus dispositivos vinculados.
3. En el proyecto, abre **Devices > Link App Account** —también puede llamarse **Link Tuya App Account**— y pulsa **Add App Account**. Si aparece, elige **Tuya App Account Authorization**. Escanea el QR con la misma aplicación y cuenta donde emparejaste el L20, confirma la autorización y verifica que aparezca en **All Devices**. Sigue [Link Devices](https://developer.tuya.com/en/docs/iot/link-devices?id=Ka471nu1sfmkl) para las variantes de vinculación y centro de datos.
4. Suscribe los servicios API requeridos y autoriza **ese proyecto** para usarlos. Son dos comprobaciones distintas: disponer del servicio no acredita que el proyecto tenga acceso. La pantalla puede estar en **Cloud Services** o **Service API > Go to Authorize**, como explica [Manage API Services](https://developer.tuya.com/en/docs/iot/applying-for-api-group-permissions?id=Ka6vf012u6q76).
5. Verifica el estado de **IoT Core** y de los servicios necesarios para consultar tus dispositivos. Los nombres dependen del portal y de las APIs: [TinyTuya 1.20.0](https://github.com/jasonacox/tinytuya/blob/v1.20.0/README.md#setup-wizard---getting-local-keys) menciona **IoT Core** y **Authorization**; la guía de Tuya de 2026 incluye **Smart Home Basic Service** junto con IoT Core, entre otros servicios de su ejemplo. Usa las indicaciones de tu proyecto y de la API que deniegue acceso; no hay una lista única garantizada para cualquier cuenta.
6. En **Overview / Authorization Key** localiza **Access ID / Client ID** y **Access Secret / Client Secret**. En **All Devices** localiza el Device ID del L20 para usarlo como referencia. No compartas esos valores ni los pegues en comandos.

En el asistente, elige la opción **1**. Introduce Access ID, Access Secret y Device ID de referencia cuando los solicite; los tres tienen entrada oculta. Indica la región Cloud correspondiente. Los códigos admitidos son `cn`, `us`, `us-e`, `eu`, `eu-w`, `in` y `sg`.

La consulta Cloud tiene un plazo de 20 segundos. Si no se completa o Tuya rechaza la consulta, se muestra un diagnóstico general para revisar región, permisos y vinculación, sin imprimir la respuesta ni tokens. En ese caso no se guarda una configuración.

Tras la consulta, selecciona el dispositivo por su **número de lista**; los identificadores se presentan enmascarados. El asistente conserva las claves recibidas en memoria, solicita la IPv4 privada y MAC del router y valida el perfil LAN admitido, Tuya 3.3 / TCP 6668. Antes de escribir pregunta si quieres guardar: responde `s` para confirmar; la respuesta predeterminada `N` cancela el guardado.

La confirmación guarda únicamente los datos LAN cifrados con DPAPI. No prueba la conexión ni envía RF. La obtención depende de que Tuya permita acceder a la información de ese dispositivo, con sus permisos y servicios vigentes. Si el proyecto no puede obtener una clave local válida, utiliza importación o entrada manual con los datos que ya tengas.

### Opción 2: importar un archivo existente

Elige **2** e indica la ruta de un JSON existente. También puedes ir directamente a la importación:

```powershell
.\.venv\Scripts\python.exe .\l20.py setup --from-file .private\devices.json
```

El archivo debe contener una lista de dispositivos o un objeto con una lista en el campo `devices`. Los registros admiten `id` y `key`, o sus equivalentes `device_id` y `local_key`. Selecciona el dispositivo por índice, incluso si la lista contiene uno solo. Después introduce la IP privada y MAC del L20 y confirma el guardado cifrado.

La importación lee el archivo sin modificarlo y no consulta Tuya Cloud. El archivo de origen **sigue en texto claro**; crear la copia DPAPI no lo cifra ni lo elimina. Conserva los archivos importados fuera del contenido público del repositorio. Se excluyen de Git los nombres conocidos `tinytuya.json`, `devices.json`, `tuya-raw.json` y `snapshot.json`. Esas exclusiones no cifran archivos, no retiran archivos ya versionados y no cubren necesariamente cualquier nombre personalizado.

### Opción 3: introducir manualmente

Elige **3** si ya conoces `device_id` y `local_key`. Se solicitan con entrada oculta. Completa IP privada y MAC y confirma el guardado, sin contactar con Tuya ni con el L20.

El comando manual anterior sigue disponible:

```powershell
.\.venv\Scripts\python.exe .\l20.py configure
```

`configure` pide los cuatro datos y los guarda localmente. Para recorrer las tres fuentes y confirmar antes de guardar, usa `setup`.

### Ensayar, sustituir y comprobar

Puedes recorrer una configuración sintética sin claves reales, red ni escritura de credenciales:

```powershell
.\.venv\Scripts\python.exe .\l20.py setup --demo
```

La demostración del asistente no escribe archivos ni modifica una configuración existente. No la combines con `--from-file`: utiliza únicamente sus datos sintéticos. Es distinta de `web --demo`, que abre la interfaz web con biblioteca de demostración.

Para sustituir una configuración existente de forma explícita:

```powershell
.\.venv\Scripts\python.exe .\l20.py setup --replace
```

Comprueba después la lectura local:

```powershell
.\.venv\Scripts\python.exe .\l20.py info
```

`info` no usa la nube ni prueba la conexión al L20. Que pueda descifrar la configuración no demuestra que la IP, MAC o claves permitan controlar el equipo.

`--credentials` y `--data` son opciones globales y van **antes** del subcomando. Por ejemplo, para mantener otra configuración y otra biblioteca:

```powershell
.\.venv\Scripts\python.exe .\l20.py --credentials .private\otro-l20.dpapi --data datos-otro\capturas setup
```

Usa los mismos parámetros globales en los comandos posteriores de ese equipo. Los directorios predeterminados se resuelven respecto de la carpeta del proyecto.

Solo la opción Cloud de `setup` contacta explícitamente con Tuya durante la preparación. Las operaciones de captura y envío contactan con el L20 por LAN; listar, validar, importar e inspeccionar configuración no lo hacen. No necesitas mantener abierta una sesión Cloud para usar una credencial LAN ya guardada.

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

Copiar los archivos DPAPI a otra PC o cuenta no garantiza poder descifrarlos. Para migrar una captura, expórtala desde el entorno original e impórtala en el nuevo; configura de nuevo el destino mediante `setup` o `configure`. Evita incluir configuración, bibliotecas, exportaciones e historial operativo en un repositorio público. Los JSON previos importados mantienen su contenido sin cifrar en origen; el asistente no guarda Access ID, Access Secret ni volcados Cloud en disco.
