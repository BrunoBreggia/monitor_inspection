# Monitoreo de actividad de Servidores del sinc(i)

Instructivo para la instalación de un sistema de monitoreo continuo de actividad de los servidores (CPU, RAM y GPUs) del instituto. Se detalla cómo funciona el script diseñado a tal efecto y cómo ejecutarlo con las debidas precauciones.

**Script:** [`monitor.py`](https://github.com/BrunoBreggia/monitor_inspection/blob/main/monitor.py)

## Función
Ejecuta un proceso de monitoreo permanente de las siguientes variables de funcionamiento del servidor:
* **Actividad de CPU** (100% - idle%): obtenida del comando mpstat
* **Temperatura del CPU** (°C): obtenida del comando sensors
* **RAM en uso** (Mb, ram total - ram libre): obtenida del comando free
* Datos de cada una de las **GPU** que se detecten en dicho servidor, obtenidos con el comando nvidia-smi:
  * **Actividad del GPU** (%)
  * **Temperatura de GPU** (°C)
  * **Memoria de GPU usada** (Mb)
  * **Potencia en uso de la GPU** (W)

## Formato
Se guarda un archivo csv (en ruta especificada) con la siguiente estructura
* **Primera fila de metadatos:** contiene hostname, fabricante del cpu, RAM total en MB, cantidad de gpus en la unidad, y parámetros de ejecución del proceso de monitoreo (explicados más adelante).

* **Segunda fila:** cabecera de las columnas 

`['Timestamp', 'CPU_Util(%)', 'CPU_Temp(C)', 'RAM_Used(MB)', 'GPU0_Util(%)', 'GPU0_Temp(C)', 'GPU0_Power(W)', 'GPU0_Mem(MiB)', 'GPU1_Util(%)', 'GPU1_Temp(C)', 'GPU1_Power(W)', 'GPU1_Mem(MiB)', 'GPU2_Util(%)', 'GPU2_Temp(C)', 'GPU2_Power(W)', 'GPU2_Mem(MiB)', ...]`

* **Cuerpo:** cada fila es un registro para un timestamp diferente

## Parseo de datos
Instructivo en el presente [jupyter notebook](https://github.com/BrunoBreggia/monitor_inspection/blob/main/read_logs.ipynb)

## Requisitos
Ejecutar con python. No requiere paquetes de python fuera del estándar. Poseer usuario root del servidor. Instalar via Linux los siguientes programas: sysstat y lm-sensors (ver comandos a continuación).

Correr los siguientes comandos con paciencia
```
$ sudo apt update
$ sudo apt upgrade
```

Si no tienes el comando `mpstat`…
```
$ sudo apt install sysstat
$ mpstat
```

Si no tienes el comando `sensors`…
```
$ sudo apt install lm-sensors
$ sudo sensors-detect # (aceptar opciones por defecto para configurar los sensores)
$ sensors
```

Si se tiene GPUs funcionales, se asume que se encuentra funcional el programa `nvidia-smi`. De caso contrario, se considerará que no hay GPUs en la unidad.

## Procedimiento
Con permiso de root, copiar el script en un directorio ubicado en `/usr/bin/monitor_inspection` en el servidor que se quiere monitorear. Ubicado en ese directorio, correr:

```
$ sudo python monitor.py -i
```

Probar con `python` o `python3` según cómo esté instalado en el servidor.

## Parámetros del comando
A continuación los parámetros configurables del proceso, con sus valores por omisión:

* **Latencia** (`-f` `--latency`): 5

  Frecuencia de medición (en segundos) de las variables del servidor 

  ```
  $ python monitor.py -f 5
  ```

* **Periodo de promediación** (`-n` `--avg-time`): 1

  Periodo (en minutos) en el cual se promedian todas las mediciones realizadas y se loguea el dato en archivo de registro

  ```
  $ python monitor.py -n 1
  ```

* **Máxima permanencia de datos** (`-s` `--max-storage`): 365

  Capacidad máxima del registro (en días). Los datos más antiguos que este umbral se van eliminando sistemáticamente, de forma tal de evitar almacenamiento infinito

  ```
  $ python monitor.py -s 365
  ```

* **Directorio de log** (`-d` `--log-directory`): /DATA/monitor_logs

  Directorio donde se guardará el archivo con el registro. El nombre del archivo será: `monitor_hostname_20260428_171908.csv`

  Donde 20260428_171908 es el timestamp del instante de creación del registro, para garantizar unicidad del nombre y evitar que se pise con registros creados en otro instante.

  ```
  $ python monitor.py -d /DATA/monitor_logs
  ```

* **Instalación** (`-i` `--install`): 

  Este parámetro lanza un proceso que corre en segundo plano (un servicio o “daemon”) con capacidad de reiniciarse ante un reboot del servidor. El servicio se levanta con el nombre de **monitor-inspection**. 
  
  El proceso se vuelve a levantar a los 5 segundos de reinicio de la máquina, y empieza a loguear en un nuevo registro con los mismos parámetros de medición fijados en la última invocación. Nunca sobreescribe archivos anteriores, fijarse en el timestamp del nombre de archivo para localizar el último vigente.

  **ACLARACIÓN:** Sin este parámetro el proceso correrá íntegramente en la terminal en la que se ejecutó el script (al cerrar la terminal se terminará el proceso).

  Una vez instalado por esta vía, se puede verificar el estado del servicio mediante el siguiente comando:

  ```
  $ sudo systemctl status monitor-inspection
  ```

  Para matar el servicio, correr el comando:

  ```
  $ sudo systemctl stop monitor-inspection
  ```



