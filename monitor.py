#!/usr/bin/env python3
"""
Version 3.0 - 2026/05/06
Leer instructivo de instalación correspondiente para usar de manera adecuada en los servidores del sinc(i).

En resumen, usar asi:
$ python3 monitor_v3.py

Valores por defecto:
$ python3 monitor_v3.py [--latency 5] [--avg-time 1] [--max-storage 365] [--log-directory /DATA/logs]

Usar el argumento -i (más sudo) para que quede corriendo en segundo plano (un daemon con alias monitor-inspection), 
con reinicio automático ante reboot del equipo
$ sudo python3 monitor_v3.py -i

En tal caso, puedes controlar su estado y matar el daemon con los siguientes comandos:

Verificar si está corriendo:
$ sudo systemctl status monitor-inspection

Matar el daemon:
$ sudo systemctl stop monitor-inspection
"""

import sys
import argparse
import time
import csv
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

##########################################################################################
# Configuracion del parser
##########################################################################################
# Initialize the parser
parser = argparse.ArgumentParser(description="Herramienta de monitoreo de actividad de servidores del sinc(i)")
# Add an optional argument (flag)
parser.add_argument("-f", "--latency", type=int, default=5, help="Defines measurement latency (sec), to be averaged every x steps (x=n*60/p, where n is the avg-time). DEFAULT: 5 sec")
parser.add_argument("-n", "--avg-time", type=int, default=1, help="Defines period of time (min) to average the measurements with latency p. DEFAULT: 1 min")
parser.add_argument("-s", "--max-storage", type=int, default=365, help="Defines maximum amount of days to save server data. DAFAULT: 365 days")
parser.add_argument("-d", "--log-directory", type=str, default="/DATA/monitor_logs", help="Defines the directory to save log files. DEFAULT: ./logs")
parser.add_argument("-i", "--install", action="store_true", help="Launches the process as a daemon, with automatic restart at reboot")
# To check process > $ sudo systemctl status monitor-inspection
# To kill  process > $ sudo systemctl stop monitor-inspection
# Parse the arguments
args = parser.parse_args()

##########################################################################################
# Funciones para extraer info de la pc via comandos linux
##########################################################################################
def get_hostname():
    """
    Gets the hostname of the server using the 'hostname' command. Returns 'unknown' if an error occurs.
    """
    try:
        result = subprocess.run(["hostname"], capture_output=True, text=True)
        hostname = result.stdout.strip()
    except Exception:
        hostname = "unknown"
    return hostname

def get_cpu_manufacturer():
    """
    Returns the cpu manufacturer
    """
    try:
        cpu = subprocess.run(['lscpu'], capture_output=True, text=True)
        for line in cpu.stdout.split('\n'):
            if 'ID' in line:
                manufacturer = line.split()[-1]
                break 
    except Exception:
        manufacturer = "-"
    return manufacturer

def detect_gpus():
    """
    Detects number of GPUs in the system using nvidia-smi. Returns 0 if not found or error occurs.
    """
    try:
        result = subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True)
        if result.returncode == 0:
            return len(result.stdout.strip().split('\n'))
    except FileNotFoundError:
        pass
    return 0

def get_total_ram_Gib():
    """
    Gets total RAM in GiB using the 'free -h' command. Returns 0 if an error occurs.
    """
    try:
        result = subprocess.run(["free", "-h"], capture_output=True, text=True)
        info = result.stdout.strip().split("\n")[1].split()[1]
        info = info.replace("Gi", "")  # Remove 'Gi' from the string
        total_ram_gb = float(info)
    except Exception:
        total_ram_gb = 0.0
    return total_ram_gb

def get_cpu_stats():
    """
    Returns a 3-tuple with: 
        * CPU utilization percentage, 
        * CPU temperature in Celsius, and 
        * RAM consumption in MiB.
    If any error occurs during data retrieval, the corresponding value will be set to 0.
    """
    # Get CPU utilization percentage
    try:
        util = subprocess.run(['mpstat'], capture_output=True, text=True)
        for line in util.stdout.split('\n'):
            try:
                content = line.strip().split()
                cpu_util = 100.0 - float(content[-1].replace(',', '.')) # %idle is last column
                break
            except (ValueError, IndexError):
                continue
        else:
            cpu_util = 0.0
    except Exception:
        cpu_util = 0.0
    
    cpu_util = round(cpu_util, 2)

    # Get CPU temperature in Celsius
    try:
        temp = subprocess.run(['sensors'], capture_output=True, text=True)
        temp_val = 0.0
        # According to manufacturer, temperature data will be parsed differently
        manufacturer = get_cpu_manufacturer()
        for line in temp.stdout.split('\n'):
            if manufacturer == 'AuthenticAMD' and 'Tctl' in line:
                for part in line.split():
                    part = part.replace('+', '').replace('°C', '')
                    try:
                        temp_val = float(part)
                        break
                    except ValueError:
                        continue
                break
            if manufacturer == 'GenuineIntel' and 'Package id 0:' in line:
                for part in line.split():
                    part = part.replace('+', '').replace('°C', '')
                    try:
                        temp_val = float(part)
                        break
                    except ValueError:
                        continue
                break
    except Exception:
        temp_val = 0.0

    # Get occupied RAM in MiB
    try:
        mem = subprocess.run(['free', '-m'], capture_output=True, text=True)
        for line in mem.stdout.split('\n'):
            if line.startswith('Mem:'):
                ram_free = int(line.split()[6])
                break
        else:
            ram_free = 0
    except Exception:
        ram_free = 0
    ram_used = get_total_ram_Gib()*1024 - ram_free

    return cpu_util, temp_val, ram_used

def get_gpu_stats():
    """
    Returns a list of lists, where each inner list corresponds to a GPU and contains:
     * GPU utilization percentage, 
     * GPU temperature in Celsius, 
     * GPU power draw in Watts, 
     * GPU memory used in MiB
    If any error occurs during data retrieval, the corresponding value will be set to 0. If no GPUs are detected, an empty list is returned.
    """
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=utilization.gpu,temperature.gpu,power.draw,memory.used',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True
        )
        stats = []
        for line in result.stdout.strip().split('\n'):
            parts = [p.strip() for p in line.split(',')]
            stats.append([float(p) if p not in ['N/A', ''] else 0.0 for p in parts])
        return stats
    except Exception:
        return []

##########################################################################################
# Funciones de mantenimiento del archivo de log
##########################################################################################
def create_file(log_dir, latency, avg_time, storage_limit):
    # Armar nombre de archivo
    start_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    hostname = get_hostname()
    cpu_manufacturer = get_cpu_manufacturer()
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"monitor_{hostname}_{start_ts}.csv" # can remove timestamp from filename if bothersome

    # Conteo de GPUs en la pc
    gpu_count = detect_gpus()

    # Creo archivo con metadata y cabecera
    with open(log_file, 'w', newline='') as f:
        writer = csv.writer(f)
        # write hostname, total RAM and GPU count as metadata
        total_ram_Gib = get_total_ram_Gib()
        writer.writerow([f"hostname:{hostname}", f"cpu_manufacturer:{cpu_manufacturer}", f"total_ram_gib:{total_ram_Gib:.2f}", f"gpu_count:{gpu_count}",
                         f"latency_sec:{latency}", f"avg_time_min:{avg_time}", f"storage_limit_days:{storage_limit}"])
        # write column headers
        header = ["Timestamp", "CPU_Util(%)", "CPU_Temp(C)", "RAM_Used(MiB)"]
        for g in range(gpu_count):
            header.extend([f"GPU{g}_Util(%)", f"GPU{g}_Temp(C)", f"GPU{g}_Power(W)", f"GPU{g}_Mem(MiB)"])
        writer.writerow(header)
    
    return log_file

def get_file_timespan(filename):
    """
    Returns a tuple with the first and last timestamps in the log file.
    If the file is empty or an error occurs, an IOError is raised.
    """
    with open(filename, "r") as file:

        # Retrieve first timestamp
        reader = csv.reader(file)
        next(reader) # skip metadata
        next(reader) # skip header
        try:
            timestamp_str = next(reader)[0]
            first_timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except StopIteration as e:
            raise IOError("Log empty")
        
        # Retrieve last timestamp
        last_timestamp = first_timestamp
        for line in reader:
            last_timestamp = datetime.strptime(line[0], "%Y-%m-%d %H:%M:%S")

    return first_timestamp, last_timestamp

def delete_lines_condition(file_path, less_than):
    """
    Deletes lines with timestamp less than timestamp specified.
    """
    with open(file_path, 'r') as file:
        lines = file.readlines()

    # Check the condition before eliminating
    now = datetime.now()
    eliminated = 0 
    for i, line in enumerate(lines[:]):
        if i == 0: continue # skip metadata
        if i == 1: continue # skip header
        timestamp = datetime.strptime(line.strip().split(",")[0], "%Y-%m-%d %H:%M:%S")
        delta = now - timestamp
        if delta > less_than: # increment is larger than storage limit
            lines.pop(i - eliminated) # with index correction
            eliminated += 1
        else: 
            break # don't bother loop the rest of the file once condition is not met anymore

    with open(file_path, 'w') as file:
        file.writelines(lines)

def check_storage(logfile, threshold_days):
    """
    Detects if the timespan of the log file exceeds the storage threshold.
    If it does, it deletes lines with timestamps older than the threshold.
    If the file is empty or an error occurs, it does nothing.
    """
    try:
        init, _ = get_file_timespan(logfile)
        now = datetime.now()
        delta = now - init
        if delta.days > threshold_days:
            limit_days = datetime.strptime(str(threshold_days), "%d")
            delta = timedelta(hours  =limit_days.hour, 
                            minutes=limit_days.minute, 
                            seconds=limit_days.second
                            )
            delete_lines_condition(logfile, less_than=delta)
    except IOError as e:
        pass

##########################################################################################
# Proceso principal (main)
##########################################################################################
def main(latency=5, avg_time=1, storage_limit=365, log_directory="/DATA/monitor_logs"):
    """
    latency in seconds
    avg_time in minutes
    storage_limit in days
    log_directory: directory to save log files
    """

    # Creacion del archivo de log
    log_file =create_file(log_directory, latency, avg_time, storage_limit)
    print(f"Logging to {log_file}")

    # Conteo de GPUs en la pc
    gpu_count = detect_gpus()

    # Creacion de buffers para almacenar datos a promediar
    cpu_util_buf = []
    cpu_temp_buf = []
    ram_free_buf = []
    gpu_util_buf = [[] for _ in range(gpu_count)]
    gpu_temp_buf = [[] for _ in range(gpu_count)]
    gpu_power_buf = [[] for _ in range(gpu_count)]
    gpu_mem_buf = [[] for _ in range(gpu_count)]

    # Loop indefinido para monitoreo de actividad de pc
    i = 0
    while True:
        # Recopilacion de datos de CPU y memoria RAM
        cpu_util, cpu_temp, ram_free = get_cpu_stats()
        cpu_util_buf.append(cpu_util)
        cpu_temp_buf.append(cpu_temp)
        ram_free_buf.append(ram_free)

        # Por cada GPU se recopila su estado de funcionamiento
        if gpu_count > 0:
            gpu_stats = get_gpu_stats()
            for g in range(gpu_count):
                if g < len(gpu_stats):
                    gpu_util_buf[g].append(gpu_stats[g][0])
                    gpu_temp_buf[g].append(gpu_stats[g][1])
                    gpu_power_buf[g].append(gpu_stats[g][2])
                    gpu_mem_buf[g].append(gpu_stats[g][3])

        i += 1

        # Momento de loggear la informacion al logfile (promedio de mediciones)
        if i >= (avg_time*60/latency):
            # Obtengo el timestamp actual
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Promedio datos de CPU y RAM
            avg_cpu_util = sum(cpu_util_buf) / len(cpu_util_buf) if cpu_util_buf else 0
            avg_cpu_temp = sum(cpu_temp_buf) / len(cpu_temp_buf) if cpu_temp_buf else 0
            avg_ram_free = sum(ram_free_buf) / len(ram_free_buf) if ram_free_buf else 0

            # Armo renglon de datos para el logfile
            row = [ts, f"{avg_cpu_util:.2f}", f"{avg_cpu_temp:.1f}", f"{avg_ram_free:.0f}"]

            # Incorporo datos de las GPUs
            for g in range(gpu_count):
                avg_u = sum(gpu_util_buf[g]) / len(gpu_util_buf[g]) if gpu_util_buf[g] else 0
                avg_t = sum(gpu_temp_buf[g]) / len(gpu_temp_buf[g]) if gpu_temp_buf[g] else 0
                avg_p = sum(gpu_power_buf[g]) / len(gpu_power_buf[g]) if gpu_power_buf[g] else 0
                avg_m = sum(gpu_mem_buf[g]) / len(gpu_mem_buf[g]) if gpu_mem_buf[g] else 0
                row.extend([f"{avg_u:.2f}", f"{avg_t:.1f}", f"{avg_p:.2f}", f"{avg_m:.0f}"])

            # Append al logfile
            try:
                with open(log_file, 'a', newline='') as f:
                    print(row)
                    writer = csv.writer(f)
                    writer.writerow(row)
            except FileNotFoundError:
                # En caso de no encontrar el logfile, se crea uno nuevo
                print(f"Error: Log file {log_file} not found. Attempting to recreate.")
                log_file = create_file(log_directory, latency, avg_time, storage_limit)
                print(f"Logging to {log_file}")
                with open(log_file, 'a', newline='') as f:
                    print(row)
                    writer = csv.writer(f)
                    writer.writerow(row)


            # Reinicio de datos (comienza nuevo promedio)
            cpu_util_buf = []
            cpu_temp_buf = []
            ram_free_buf = []
            gpu_util_buf = [[] for _ in range(gpu_count)]
            gpu_temp_buf = [[] for _ in range(gpu_count)]
            gpu_power_buf = [[] for _ in range(gpu_count)]
            gpu_mem_buf = [[] for _ in range(gpu_count)]
            i = 0

        # Evitamos que el logfile se llene indefinidamente
        check_storage(log_file, storage_limit)
        # Demora hasta la proxima medicion
        time.sleep(latency)

##########################################################################################
# Proceso de instalacion (reinicio automatico en reboot)
##########################################################################################

def install_autostart(latency, avg_time, storage_limit, log_directory):
    script_path = Path(__file__).resolve()
    service_content = f"""[Unit]
Description=Monitor server Stats

[Service]
Type=simple
ExecStart=/usr/bin/python3 -u {script_path} -f {latency} -n {avg_time} -s {storage_limit} -d {log_directory}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    service_path = Path("/etc/systemd/system/monitor-inspection.service")
    try:
        service_path.write_text(service_content)
        subprocess.run(["systemctl", "daemon-reload"])
        subprocess.run(["systemctl", "enable", "monitor-inspection.service"])
        subprocess.run(["systemctl", "start", "monitor-inspection.service"])
        print(f"Installed as systemd service: {service_path}")
        print("Run 'sudo systemctl status monitor-inspection' to check status")
    except PermissionError:
        print("Permission denied. Run with sudo to install autostart:")
        print(f"  sudo python3 {script_path} --install")
        sys.exit(1)


# Invocacion al main
if __name__ == "__main__":
    print("=================================================================")
    print(f"Monitor inspection process for sinc(i) servers launched with: \
        \n * {args.latency} second measurement latency \
        \n * {args.avg_time} minute time average \
        \n * {args.max_storage} day storage \
        \n * Log directory: {args.log_directory}")
    print("=================================================================")

    if args.install:
        install_autostart(
            latency=args.latency,
            avg_time=args.avg_time,
            storage_limit=args.max_storage,
            log_directory=args.log_directory
        )
    else:
        main(latency=args.latency,
            avg_time=args.avg_time,
            storage_limit=args.max_storage,
            log_directory=args.log_directory
            )
