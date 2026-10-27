# Evidencia y límites de validación

## Instalación de origen

La persona operadora de la instalación que motivó este proyecto informó que el portón abría y cerraba mediante LAN, aunque la respuesta era intermitente. Después indicó que funcionaba muy bien al solicitar cuatro repeticiones por orden. «Cuatro» describe el parámetro de repetición, no una cantidad de ensayos satisfactorios. No se midieron el número de intentos ni una tasa de éxito.

La observación respalda cualitativamente el funcionamiento del conjunto concreto de emisor, firmware, código capturado, control y receptor utilizado allí. Es un resultado declarado por la persona usuaria; no procede de un sensor de posición ni de una medición independiente del software. No establece que cuatro repeticiones sea el valor adecuado para otro receptor.

El repositorio se prepara para que otra persona configure su propio destino. No incluye la IP, MAC, credenciales ni capturas operativas de esa instalación. La generalización no supone una nueva validación física en otro L20.

## Comprobación del software

Se ejecutaron 64 pruebas automatizadas en un entorno virtual nuevo con Python 3.11: 35 del transporte RF, 11 de la aplicación y 18 de la consola. Se comprobó también `Instalar.ps1` en ese entorno limpio.

Las pruebas del repositorio emplean datos sintéticos, conexiones al dispositivo simuladas y almacenamiento temporal. Cubren componentes como validación de códigos, cifrado DPAPI, formato de trama, lectura fragmentada, errores, persistencia, revisiones, API local y prevención de reenvíos dentro de una sesión.

Desde la carpeta del proyecto, con las dependencias instaladas:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

La prueba de interoperabilidad de tramas contrasta partes del formato con TinyTuya. No acredita compatibilidad de todos los campos RF ni sustituye la aceptación por un equipo físico. El modo `web --demo` permite revisar el flujo de interfaz con un ejemplo sintético sin abrir una conexión al L20.

Se comprobó además en el navegador el flujo de demostración: capturar, guardar, editar JSON, validar y solicitar una prueba con cuatro repeticiones. El historial registró una orden `NOT_SENT` con motivo `DEMO`, sin observación física. La siguiente imagen muestra ese resultado sintético:

![Demostración de la interfaz: cuatro repeticiones solicitadas, orden no enviada e historial sin observación física](demostracion.jpg)

Al preparar esta adaptación genérica no se han realizado nuevas capturas ni transmisiones físicas. Una prueba automatizada aprobada demuestra el comportamiento cubierto por esa prueba, no apertura o cierre del portón.

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
