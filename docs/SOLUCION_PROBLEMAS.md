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
| Credencial inválida o Windows no puede descifrar | Usa la misma cuenta y entorno de Windows que creó el archivo. Si necesitas reconfigurar, ejecuta `configure --replace`. |
| No existe la configuración | Ejecuta `configure`. Para una ruta alternativa usa `--credentials RUTA` antes del subcomando. |
| MAC no corresponde al L20 | Verifica la reserva DHCP y la MAC en el router. La IP podría pertenecer ahora a otro equipo. Corrige la configuración; no sustituyas la MAC a ciegas. |
| No se pudo comprobar ARP | Comprueba que PC y L20 estén en la misma subred directa, sin aislamiento Wi-Fi, red de invitados, VPN o VLAN que los separe. |
| No se valida el descifrado | Revisa `device_id`, clave local vigente y que el dispositivo utilice realmente Tuya 3.3. Si se volvió a emparejar, obtén de nuevo sus datos. |

El `device_id` es el identificador del dispositivo y la `local_key` es su clave local. No introduzcas el Access ID o Access Secret del proyecto de Tuya en su lugar. Para problemas al obtenerlos consulta el [asistente oficial del proyecto TinyTuya](https://github.com/jasonacox/tinytuya/blob/v1.20.0/README.md#setup-wizard---getting-local-keys).

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
