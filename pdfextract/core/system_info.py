"""
Utilidades para introspección del hardware y del entorno de ejecución.
Registra CPU, RAM, GPU, VRAM, sistema operativo y versiones de librerías para benchmarking.
"""

import platform
import sys
from typing import Any, Dict
import psutil


def get_installed_version(pkg_name: str) -> str:
    """Obtiene la versión instalada de un paquete de Python o 'not_installed'."""
    try:
        import importlib.metadata
        return importlib.metadata.version(pkg_name)
    except Exception:
        return "not_installed"


def get_gpu_info() -> Dict[str, Any]:
    """
    Detecta dispositivos GPU (CUDA) disponibles y memoria VRAM.
    Retorna información estructurada de GPU.
    """
    gpu_info = {
        "available": False,
        "device_count": 0,
        "devices": []
    }

    try:
        import torch
        if torch.cuda.is_available():
            gpu_info["available"] = True
            count = torch.cuda.device_count()
            gpu_info["device_count"] = count
            for i in range(count):
                name = torch.cuda.get_device_name(i)
                total_mem = torch.cuda.get_device_properties(i).total_memory / (1024 ** 3)
                gpu_info["devices"].append({
                    "id": i,
                    "name": name,
                    "vram_gb": round(total_mem, 2)
                })
    except Exception:
        pass

    return gpu_info


def get_system_environment() -> Dict[str, Any]:
    """
    Recopila información integral del entorno para el archivo processing_metadata.json.
    """
    vm = psutil.virtual_memory()
    return {
        "os": {
            "platform": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "architecture": platform.machine(),
        },
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
        },
        "hardware": {
            "cpu_cores_physical": psutil.cpu_count(logical=False),
            "cpu_cores_logical": psutil.cpu_count(logical=True),
            "ram_total_gb": round(vm.total / (1024 ** 3), 2),
            "ram_available_gb": round(vm.available / (1024 ** 3), 2),
            "gpu": get_gpu_info(),
        },
        "libraries": {
            "docling": get_installed_version("docling"),
            "docling_core": get_installed_version("docling-core"),
            "paddlepaddle": get_installed_version("paddlepaddle"),
            "paddlepaddle_gpu": get_installed_version("paddlepaddle-gpu"),
            "paddleocr": get_installed_version("paddleocr"),
            "rapidocr": get_installed_version("rapidocr"),
            "rapid_layout": get_installed_version("rapid-layout"),
            "rapid_table": get_installed_version("rapid-table"),
            "onnxruntime": get_installed_version("onnxruntime"),
            "torch": get_installed_version("torch"),
            "transformers": get_installed_version("transformers"),
            "pypdf": get_installed_version("pypdf"),
            "pdfplumber": get_installed_version("pdfplumber"),
        }
    }
