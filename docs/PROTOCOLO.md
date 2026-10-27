# Protocolo y compatibilidad

Este documento describe el transporte implementado en `rf_device.py`. El alcance es una variante RF Tuya 3.3 con órdenes en DP201. No es un controlador universal para cualquier producto denominado L20 ni para todos los dispositivos que soporta TinyTuya.

## Red y almacenamiento

La PC establece una conexión TCP al destino configurado, puerto 6668. Antes de conectar, consulta por ARP la MAC de esa IP y exige que coincida con la configurada. Esto requiere estar en la misma subred de capa 2; una conexión enrutada, otra VLAN o una VPN no equivale a acceso directo aunque exista una ruta IP.

La IP y MAC proceden de la configuración local, junto con `device_id` y `local_key`. Se guardan cifradas con Windows DPAPI. La clave local debe representar 16 bytes. Los códigos RF de la biblioteca también se cifran con DPAPI; Base64 es una representación de datos y no ofrece cifrado.

El navegador conecta con el servidor HTTP en `127.0.0.1`. La conexión al L20 sale de Python, no del navegador. Abrir la página, listar, leer configuración o validar no inicia comunicación con el L20. Las acciones explícitas de captura y envío abren la conexión LAN.

## Trama Tuya 3.3

Las órdenes usan una trama `55AA`, secuencia, comando `7`, longitud, carga, CRC32 y sufijo `AA55`. La carga lleva el encabezado de versión 3.3 y JSON cifrado mediante AES-128-ECB con relleno, usando la clave local. En el JSON exterior, `dps["201"]` contiene una cadena JSON con la orden RF.

Las respuestas incluyen código de retorno. El lector conserva fragmentos de TCP, valida longitud, CRC y sufijo y limita el tamaño de trama. El descifrado se realiza antes de interpretar los DP. Los formatos generales se pueden contrastar con [header.py](https://github.com/jasonacox/tinytuya/blob/v1.20.0/tinytuya/core/header.py), [message_helper.py](https://github.com/jasonacox/tinytuya/blob/v1.20.0/tinytuya/core/message_helper.py) y el [codificador de TinyTuya](https://github.com/jasonacox/tinytuya/blob/v1.20.0/tinytuya/core/XenonDevice.py).

## Aprendizaje y envío

| Acción | Contenido de la orden RF |
| --- | --- |
| Iniciar aprendizaje | `control: rf_study`, `rf_type: sub_2g`, `study_feq: "0"` o `"433.92"`, `ver: "2"` |
| Terminar aprendizaje | `control: rfstudy_exit`, mismo tipo, frecuencia y versión |
| Transmitir captura | `control: rfstudy_send`, `rf_type: sub_2g`, `feq: 0`, `mode: 0`, `rate: 0`, `ver: "2"`, `key1` |
| Contenido de `key1` | Código Base64 completo, `times` entre 1 y 6, `delay: 0`, `intervals: 0` |

El envío usa `feq: 0`; no sustituye ese campo por la frecuencia textual usada para aprender. Se conserva la frecuencia del contenedor aprendido. Esta implementación no añade `ver` dentro de `key1`; conserva el esquema empleado en la instalación original. El [módulo RF de TinyTuya 1.20.0](https://github.com/jasonacox/tinytuya/blob/v1.20.0/tinytuya/Contrib/RFRemoteControlDevice.py) constituye una referencia relacionada e inyecta ese campo adicional. No se afirma identidad completa entre ambos emisores.

Durante el aprendizaje se busca primero un contenedor válido en DP202 y después en DP2. Ese segundo caso es una lectura alternativa; las órdenes siguen saliendo por DP201. No equivale a implementar la variante completa que TinyTuya distingue con DP1–13.

Al finalizar la captura, por éxito, cancelación o error, se intenta enviar la salida de aprendizaje si se había intentado iniciar. Que el socket acepte esa escritura no confirma que el equipo haya salido del modo aprendizaje. Un reporte recibido tampoco prueba por sí solo que sea una pulsación nueva.

## Formato admitido

El código RF es Base64 de un objeto JSON UTF-8. El validador admite la versión `2`, una sola señal (`num: 1`), `data0` en Base64 y `lv` con un único nivel `0` o `1`. Si aparecen `study_feq` o `feq`, deben ser cero o una frecuencia numérica finita entre 250 y 1000 MHz. Este rango de validación no acredita el rango RF del hardware.

Se rechazan claves JSON duplicadas, datos incompletos, señales adicionales `data1`, `data2`, etc., anidación excesiva y entradas que excedan los límites del módulo. No se implementa análisis de pulsos, detección de protocolo del control ni identificación de código variable.

## Interpretar una transmisión

| Resultado | Interpretación |
| --- | --- |
| `NOT_SENT` | No se intentó escribir la orden al socket del L20. |
| `ACKNOWLEDGED` | Llegó una respuesta aceptada para la secuencia y comando enviados. |
| `DEVICE_REJECTED` | El L20 devolvió un rechazo; no demuestra movimiento físico. |
| `UNCERTAIN` | Se intentó escribir la orden, pero no se pudo confirmar el resultado. Puede haber llegado al equipo. |

Se intenta una sola escritura de la orden de transmisión. `times` representa repeticiones pedidas al dispositivo dentro de esa orden; no son reintentos del transporte. No se abre automáticamente otra conexión para reenviar una prueba incierta.

Ni un ACK ni los tiempos de ARP, conexión, escritura y respuesta miden la latencia mecánica del portón. La confirmación física la declara la persona operadora. La reproducción de códigos variables, la compatibilidad de otras frecuencias y otras variantes de firmware requieren evidencia específica que este repositorio no aporta.
