# Solución de problemas

## Instalación o inicio

| Síntoma | Qué revisar |
| --- | --- |
| Python no se encuentra | Instala Python 3.10 o superior y verifica `py -3 --version`. Sigue las alternativas de [USO](USO.md#instalar) si no puedes ejecutar el script. |
| PowerShell bloquea `Instalar.ps1` | Ejecuta `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Instalar.ps1` para permitir ese proceso, o usa la instalación manual de la guía. |
| Falta `tinytuya` o un módulo de cifrado | Ejecuta `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` y usa ese mismo intérprete para iniciar el proyecto. |
| Puerto web ocupado | Cierra la instancia anterior o usa `l20.py web --port 58746`. Abre la dirección que imprima el programa. |
| La página informa sesión cambiada | Recarga la página del servidor actual. Cada inicio crea un token de sesión distinto. Conserva o guarda primero cualquier edición pendiente si todavía es posible. |
| Solicitud externa rechazada | Abre la URL local indicada, con `127.0.0.1` o `localhost` y el puerto correcto. El servidor no ofrece acceso por la IP de la PC para otros equipos. |

## Credenciales y destino

`info` y el estado «Credencial lista» solo comprueban la lectura local de la configuración. No comprueban que el L20 esté conectado.

| Mensaje o problema | Acción |
| --- | --- |
| Credencial inválida o Windows no puede descifrar | Usa la misma cuenta y entorno de Windows que creó el archivo. Si necesitas reconfigurar, ejecuta `setup --replace`. |
| No existe la configuración | Ejecuta `setup` o abre `IniciarAsistente.cmd`. Para una ruta alternativa usa `--credentials RUTA` antes del subcomando. |
| MAC no corresponde al L20 | Verifica la reserva DHCP y la MAC en el router. La IP podría pertenecer ahora a otro equipo. Corrige la configuración; no sustituyas la MAC a ciegas. |
| No se pudo comprobar ARP | Comprueba que PC y L20 estén en la misma subred directa, sin aislamiento Wi-Fi, red de invitados, VPN o VLAN que los separe. |
| No se valida el descifrado | Revisa `device_id`, clave local vigente y que el dispositivo utilice realmente Tuya 3.3. Si se volvió a emparejar, obtén de nuevo sus datos. |

El `device_id` es el identificador del dispositivo y la `local_key` es su clave local. Access ID y Access Secret identifican y autentican el proyecto de Tuya Cloud; pertenecen a la opción Cloud del asistente, no a la configuración LAN. Consulta la [guía del asistente integrado](USO.md#asistente-de-configuración).

## Asistente y Tuya Cloud

| Síntoma | Qué revisar |
| --- | --- |
| No se escribe nada al introducir un secreto | Es normal: Access ID, Access Secret y los identificadores o claves solicitados con entrada oculta no muestran caracteres en pantalla. No pases esos valores como argumentos. |
| Autenticación o firma inválida | Comprueba que Access ID y Access Secret pertenezcan al mismo proyecto y estén completos. No uses la contraseña de la aplicación ni la `local_key` en esos campos. |
| Permiso denegado | Verifica cuenta vinculada, servicios suscritos y autorización de las APIs para ese proyecto. Ver el L20 en el portal no acredita todos los permisos de consulta. |
| Servicio o periodo de prueba vencido | Revisa el estado del plan de IoT Core, sus cuotas y servicios en el portal. Las condiciones dependen de la cuenta; el asistente no renueva ni compra planes. |
| No se pudo obtener la lista Cloud dentro del plazo | La consulta tiene un límite de 20 segundos. El diagnóstico también agrupa rechazos de Tuya sin exponer su respuesta completa: revisa Internet, región, permisos y vinculación antes de iniciar otra consulta manual. No se guarda una configuración cuando falla la obtención. |
| No aparece el L20 en la selección | Revisa que vinculaste la misma cuenta de la aplicación y que la región Cloud corresponda al centro de datos donde ves el equipo. Se requiere un registro con identificador y clave local válidos. |
| Región no admitida | Usa uno de los códigos `cn`, `us`, `us-e`, `eu`, `eu-w`, `in` o `sg`. Selecciona el que corresponda a tu cuenta, sin inferirlo solo por tu ubicación. |
| El archivo importado no produce dispositivos válidos | Revisa que sea JSON de dispositivos con campos `id`/`key` o `device_id`/`local_key`. Un archivo que solo contiene claves API Cloud no equivale a un archivo de dispositivos. |
| La configuración ya existe | Si quieres sustituirla, inicia `setup --replace` y confirma el nuevo guardado. Para conservarla, cancela o usa otra ruta global de credenciales. |
| El origen y el destino deben ser distintos | Conserva el JSON importado como origen y elige otro archivo para la configuración DPAPI. `--replace` tampoco permite sobrescribir la fuente ni un alias del mismo archivo. |
| Tras la demostración sigue sin configurar | `setup --demo` no guarda credenciales. Inicia `setup` sin `--demo` para configurar tu equipo. |
| Se canceló la confirmación de guardado | La respuesta predeterminada es `N`. Solo se guarda cuando confirmas con `s`. |
| El asistente guardó, pero la web sigue «Sin configurar» | Cierra el servidor web con `Ctrl+C` y vuelve a abrir `Iniciar.cmd` para que lea la credencial nueva. |
| Se intenta usar `--demo` con `--from-file` | Son recorridos distintos. Ejecuta la demostración sola; para importar tu archivo, omite `--demo`. |

Para vinculación y región consulta [Link Devices de Tuya](https://developer.tuya.com/en/docs/iot/link-devices?id=Ka471nu1sfmkl); para permisos, [Manage API Services](https://developer.tuya.com/en/docs/iot/applying-for-api-group-permissions?id=Ka6vf012u6q76). Los nombres de menús y servicios pueden variar según el portal y las APIs de tu proyecto.

Los errores del asistente se presentan sin volcar tokens ni respuestas Cloud completas. Para pedir ayuda comparte el mensaje de diagnóstico, sin pegar claves, identificadores completos ni el JSON importado. No es necesario ejecutar el wizard externo de TinyTuya para usar este asistente.

Si una importación termina bien, el JSON de origen continúa en texto claro y no se modifica. La copia cifrada DPAPI no protege retroactivamente ese archivo. Por otro lado, un permiso Cloud vencido no impide por sí mismo usar una `local_key` LAN ya guardada y todavía válida; si vuelves a emparejar el equipo, revisa de nuevo sus credenciales.

## Captura

Si termina la escucha sin código, comprueba la alimentación del control y pulsa el botón cerca del L20 durante la ventana activa. Prueba frecuencia automática o 433.92 MHz según el control y las capacidades de tu hardware. Solo esas dos opciones están expuestas por este proyecto.

Un código válido pero inesperado puede ser un reporte anterior. Asigna nombres que identifiquen el botón y comprueba cada captura antes de reutilizarla. El programa no puede acreditar frescura RF a partir del reporte LAN.

Si el equipo queda aprendiendo tras una desconexión, revisa su estado en la aplicación del fabricante y termina el aprendizaje desde allí. El proyecto intenta enviar `rfstudy_exit`, pero no puede garantizar que llegue cuando falla la conexión.

## Envío y resultado físico

- Ante `NOT_SENT`, corrige el problema indicado antes de iniciar otra acción manual.
- Ante `UNCERTAIN`, comprueba físicamente el portón: la orden puede haberse ejecutado aunque no llegue el ACK. No se reenvía automáticamente.
- Ante `ACKNOWLEDGED` sin respuesta física, revisa que la captura corresponda al botón, frecuencia y receptor esperados. El ACK confirma una respuesta LAN del L20.
- Ante `DEVICE_REJECTED`, revisa el formato y la compatibilidad del esquema RF de tu variante. Que otra variante L20 funcione no prueba que esta acepte DP201.

Una a seis repeticiones son parámetros de una orden RF. No hay un valor universal. Comienza por una y realiza cualquier ajuste como prueba manual observada. El historial de tiempos mide software y red; no mide el movimiento del mecanismo.

## Biblioteca e historial

Si una captura cambió en otra ventana, vuelve a seleccionarla antes de guardar. Las revisiones evitan reemplazar silenciosamente una versión más reciente. Usa una sola instancia para evitar operaciones concurrentes desde procesos distintos.

Si Windows no puede leer una captura cifrada, conserva el archivo original y comprueba cuenta y entorno. Los archivos ilegibles se reportan; no se reconstruyen ni se eliminan automáticamente. Una exportación anterior en texto claro puede importarse mediante `save`.

Si `export` indica que el destino existe, elige otro nombre: la exportación no sobrescribe archivos existentes. Un fallo al guardar el historial no demuestra que haya fallado la transmisión; comprueba el resultado físico antes de repetirla.

En demostración, la transmisión se informa como no enviada y no hay observación física válida. Inicia la web sin `--demo` para usar una configuración real.
