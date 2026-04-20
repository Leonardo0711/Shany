import subprocess
import os
import sys
from pi_config import get_pscp_base_cmd, PI_CONFIG

def deploy(source_path):
    if not os.path.exists(source_path):
        print(f"Error: El archivo o carpeta '{source_path}' no existe.")
        return

    is_dir = os.path.isdir(source_path)
    full_cmd = get_pscp_base_cmd(recursive=is_dir)
    
    # Destino en la Pi
    destination = f"{PI_CONFIG['user']}@{PI_CONFIG['host']}:{PI_CONFIG['remote_path']}"
    
    full_cmd += [source_path, destination]
    
    print(f"Desplegando {source_path} a {destination}...")
    
    try:
        subprocess.run(full_cmd, check=True)
        print("¡Despliegue completado con éxito!")
    except subprocess.CalledProcessError as e:
        print(f"Error durante el despliegue: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python pi_deploy.py <ruta_archivo_o_carpeta>")
    else:
        deploy(sys.argv[1])
