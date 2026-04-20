import subprocess
from pi_config import get_ssh_base_cmd, PI_CONFIG

def check_pi():
    print(f"--- Verificando conexión a {PI_CONFIG['host']} ---")
    
    # Comandos a ejecutar en la Pi
    commands = "uptime; free -m; df -h /"
    
    full_cmd = get_ssh_base_cmd() + [commands]
    
    try:
        result = subprocess.run(full_cmd, capture_output=True, text=True, check=True)
        print("Conexión exitosa. Estado del sistema:")
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error al conectar con la Raspberry Pi: {e}")
        if e.stderr:
            print(f"Detalle del error: {e.stderr}")

if __name__ == "__main__":
    check_pi()
