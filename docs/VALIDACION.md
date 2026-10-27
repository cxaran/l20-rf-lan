# Evidencia y límites de validación

## Instalación de origen

La persona operadora de la instalación que motivó este proyecto informó que el portón abría y cerraba mediante LAN, aunque la respuesta era intermitente. Después indicó que funcionaba muy bien al solicitar cuatro repeticiones por orden. «Cuatro» describe el parámetro de repetición, no una cantidad de ensayos satisfactorios. No se midieron el número de intentos ni una tasa de éxito.

La observación respalda cualitativamente el funcionamiento del conjunto concreto de emisor, firmware, código capturado, control y receptor utilizado allí. Es un resultado declarado por la persona usuaria; no procede de un sensor de posición ni de una medición independiente del software. No establece que cuatro repeticiones sea el valor adecuado para otro receptor.

El repositorio se prepara para que otra persona configure su propio destino. No incluye la IP, MAC, credenciales ni capturas operativas de esa instalación. La generalización no supone una nueva validación física en otro L20.

## Comprobación del software

El conjunto actual de 100 pruebas automatizadas pasa en Windows con Python 3.11: 35 del transporte RF, 11 de la aplicación, 18 de la consola, 5 del almacenamiento de credenciales, 14 del asistente y 17 de su integración. El entorno se preparó con `Instalar.ps1`, cuya instalación se comprobó desde un entorno limpio.

Las pruebas del repositorio emplean datos sintéticos, conexiones al dispositivo simuladas y almacenamiento temporal. Cubren componentes como validación de códigos, cifrado DPAPI, formato de trama, lectura fragmentada, errores, persistencia, revisiones, API local y prevención de reenvíos dentro de una sesión.

Desde la carpeta del proyecto, con las dependencias instaladas:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

La prueba de interoperabilidad de tramas contrasta partes del formato con TinyTuya. No acredita compatibilidad de todos los campos RF ni sustituye la aceptación por un equipo físico. El modo `web --demo` permite revisar el flujo de interfaz con un ejemplo sintético sin abrir una conexión al L20.

Se comprobó además en el navegador el flujo de demostración: capturar, guardar, editar JSON, validar y solicitar una prueba con cuatro repeticiones. El historial registró una orden `NOT_SENT` con motivo `DEMO`, sin observación física. La siguiente imagen muestra ese resultado sintético:

![Demostración de la interfaz: cuatro repeticiones solicitadas, orden no enviada e historial sin observación física](demostracion.jpg)

Al preparar esta adaptación genérica no se han realizado nuevas capturas ni transmisiones físicas. Una prueba automatizada aprobada demuestra el comportamiento cubierto por esa prueba, no apertura o cierre del portón.

## Alcance del asistente de configuración

El asistente propio incorpora obtención desde Tuya Cloud, importación de un archivo existente y entrada manual. La revisión de esta ampliación no realiza autenticación con una cuenta Cloud real ni nuevas pruebas físicas del L20. La compatibilidad con permisos, servicios y datos de una cuenta concreta debe comprobarse en esa cuenta.

Puedes ensayar el recorrido sintético localmente:

```powershell
.\.venv\Scripts\python.exe .\l20.py setup --demo
```

Ese modo no consulta Tuya, no contacta con el L20 y no guarda credenciales. Permite revisar el diálogo sin introducir secretos reales. No acredita una obtención exitosa de claves desde la nube.

Las pruebas verifican selección por índice con ID enmascarado, entrada oculta de secretos, validación del destino y perfil LAN, confirmación antes del guardado DPAPI, ausencia de archivos Cloud nuevos en texto claro y conservación del JSON importado sin cambios. También cubren cancelación, rechazo de JSON ambiguos, preservación de una configuración anterior ante fallos y tratamiento seguro de errores o tiempos de espera del proceso Cloud. Origen y destino no pueden representar el mismo archivo, incluso mediante un hardlink y aunque se indique `--replace`.

Se ejecutaron además procesos reales de consola: el lanzador PowerShell en modo demostración y una importación con selección entre dos dispositivos sintéticos. El archivo importado quedó intacto y el destino DPAPI contenía solo los seis campos LAN esperados. El canal del proceso Cloud se comprobó con un SDK simulado, sin red. Ninguna de estas comprobaciones utiliza una cuenta Tuya real. Las capturas de interfaz anteriores documentan la web de demostración, no una sesión Cloud.

## Verificación de otra instalación

Para evaluar tu propio equipo, configura sus datos y captura un botón identificable. Guarda el código antes de probarlo. Inicia una única transmisión manual, con una repetición, mientras puedas observar el equipo. Anota si respondió físicamente y conserva el resultado LAN por separado. Si el resultado es incierto, observa primero lo ocurrido antes de solicitar otra transmisión.

La interfaz permite registrar observaciones físicas en el historial de ensayos. Son declaraciones de la persona operadora y pueden corregirse; el software no descubre por sí mismo que el portón abrió o cerró.

## Lo que permanece sin demostrar

- Compatibilidad con todos los equipos comercializados como L20, otros DP o protocolos Tuya distintos de 3.3.
- Correspondencia entre cada reporte de aprendizaje y una pulsación RF nueva.
- Reproducción de controles con código variable, o identificación fiable de ese mecanismo a partir de un contenedor.
- Cobertura del hardware para cualquier frecuencia que un código pueda describir.
- Relación entre ACK, cantidad de repeticiones y éxito físico en otro receptor.
- Tiempos mecánicos de apertura/cierre: las métricas disponibles describen fases de comunicación y software.

Las referencias de [PROTOCOLO](PROTOCOLO.md) explican las decisiones técnicas. La compatibilidad final de otra instalación requiere su propia comprobación física.
