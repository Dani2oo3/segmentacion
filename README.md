# Simulador MIPS Segmentado de 5 Etapas

Simulador funcional en Python de un procesador con arquitectura **MIPS de 32 bits** que implementa un cauce (pipeline) segmentado de 5 etapas (**IF**, **ID**, **EX**, **MEM**, **WB**). 

Este proyecto permite visualizar y analizar la ejecución paso a paso de instrucciones ensamblador, la decodificación de opcodes y el flujo de datos a través de los registros de desacoplamiento del pipeline.

---

## 🏗️ Arquitectura del Proyecto

El proyecto está modularizado en los siguientes componentes principales:

* **`componentes_base.py`**: Contiene la infraestructura del procesador.
  * **Memorias:** `MemoriaInstrucciones` (indexada por PC y mapeo de etiquetas) y `MemoriaDatos` (memoria RAM de lectura/escritura).
  * **BancoRegistros:** Módulo de registros $R0 \dots R31$ ($R0$ cableado a cero constante).
  * **ALU:** Unidad Aritmético Lógica para operaciones tipo R y tipo I.
  * **UnidadControl:** Generación de señales de control (`RegWrite`, `MemRead`, `MemWrite`, `EsSalto`).
* **`registros_pipeline.py`**: Define las clases para los registros de desacoplamiento entre etapas (`IF_ID`, `ID_EX`, `EX_MEM`, `MEM_WB`) encargados de propagar el estado en cada flanco de reloj (`latch`).
* **`cpu.py`**: Módulo central y punto de entrada. Integra los componentes, realiza la decodificación de las instrucciones y gestiona el ciclo de reloj y ejecución del pipeline.
* **`instrucciones.txt`**: Fichero de entrada con el código fuente en ensamblador MIPS.
* **`datos_iniciales.txt`**: Fichero de configuración para inicializar registros y memoria de datos.

---

## ⚙️ Etapas del Pipeline

El cauce simula la ejecución concurrente mediante la evaluación de etapas en orden inverso por ciclo de reloj:

1. **WB (Write-Back):** Escritura del resultado en el banco de registros.
2. **MEM (Memory):** Lectura o escritura en la memoria de datos (`LW`, `SW`).
3. **EX (Execution):** Operación en la ALU o cálculo de direcciones efectivas.
4. **ID (Instruction Decode):** Decodificación, lectura de operandos en el banco de registros y extracción de inmediatos/etiquetas.
5. **IF (Instruction Fetch):** Lectura de la instrucción en memoria apuntada por el `PC`.

---

## 🚀 Requisitos e Instalación

### Requisitos previos
* **Python 3.8+** instalado.

### Clonar el repositorio
```bash
git clone [https://github.com/Dani2oo3/segmentacion.git](https://github.com/Dani2oo3/segmentacion.git)
cd segmentacion
