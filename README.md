# Simulador MIPS Segmentado de 5 Etapas con Forwarding

Simulador funcional en Python de un procesador con arquitectura **MIPS de 32 bits** que implementa un cauce (pipeline) segmentado de 5 etapas (**IF**, **ID**, **EX**, **MEM**, **WB**)[cite: 2]. 

Este proyecto permite visualizar y analizar detalladamente la ejecución paso a paso de código en ensamblador, la resolución de riesgos de datos mediante *Forwarding* y *Stalls*, la gestión de saltos con *Flushes*, y el estado del camino de datos en cada ciclo de reloj[cite: 2].

---

## 🏗️ Arquitectura y Componentes del Proyecto

El proyecto se encuentra modularizado en los siguientes ficheros principales:

* **`componentes_base.py`**: Contiene los bloques hardware fundamentales de la CPU[cite: 1]:
  * **Memorias:** `MemoriaInstrucciones` (gestión de carga de ficheros y resolución de etiquetas) y `MemoriaDatos` (memoria RAM de lectura/escritura con validación de alineación a múltiplos de 4)[cite: 1].
  * **BancoRegistros:** Banco de 32 registros (`R0` a `R31`), donde `R0` está permanentemente cableado a cero[cite: 1].
  * **ALU:** Unidad Aritmético-Lógica encargada de las operaciones aritméticas para instrucciones de tipo R, tipo I y cálculo de direcciones de memoria[cite: 1].
* **`registros_pipeline.py`**: Define las clases de los registros de desacoplamiento inter-etapa (`RegistroIF_ID`, `RegistroID_EX`, `RegistroEX_MEM`, `RegistroMEM_WB`) que propagan el estado y sincronizan el cauce en cada flanco de reloj mediante la función `latch()`[cite: 3].
* **`cpu.py`**: Módulo central y punto de entrada de la aplicación. Integra la unidad de proceso, la unidad de control, la lógica de riesgos y la interfaz de salida formateada por consola[cite: 2].
* **`instrucciones.txt`**: Fichero predeterminado con el código fuente en ensamblador MIPS para la ejecución principal[cite: 7].
* **`datos_iniciales.txt`**: Fichero de configuración inicial que define los valores de los registros y el estado inicial de la memoria de datos[cite: 6].
* **`aux.txt` y `aux2.txt`**: Ficheros alternativos de código ensamblador MIPS incluidos para pruebas adicionales del simulador[cite: 4, 5].

---

## ⚙️ Etapas del Pipeline y Características Avanzadas

El cauce simula la ejecución concurrente evaluando las etapas en orden inverso en cada ciclo de reloj para asegurar un traspaso transparente de datos[cite: 2]:

1. **WB (Write-Back):** Escritura de los resultados calculados en el banco de registros[cite: 2].
2. **MEM (Memory):** Operaciones de lectura (`LW`) o escritura (`SW`) en la memoria de datos[cite: 2].
3. **EX (Execution):** Operación en la ALU y aplicación de adelantamiento de datos (*Forwarding*) desde las etapas `EX/MEM` y `MEM/WB`[cite: 2].
4. **ID (Instruction Decode):** Decodificación de la instrucción, lectura de operandos en el banco de registros y resolución anticipada de saltos (`BEQ`, `J`)[cite: 2].
5. **IF (Instruction Fetch):** Captura de la instrucción desde la memoria apuntada por el registro `PC`[cite: 2].

### Gestión de Riesgos y Control
* **Forwarding (Adelantamiento):** Resuelve los riesgos de datos RAW (Read-After-Write) alimentando directamente los resultados hacia la ALU sin paradas innecesarias[cite: 2].
* **Stalls (Riesgos Load-Use):** Detección automática de dependencias críticas de tipo *Load-Use* donde el *Forwarding* no es suficiente, insertando una parada (*stall*) de forma segura[cite: 2].
* **Flushes:** Vaciado especulativo de la etapa de captura (`IF/ID`) cuando se toma un salto condicional o incondicional[cite: 2].

---

## 🎨 Interfaz de Terminal y Formato Visual

La salida por consola presenta mejoras de diseño orientadas a la legibilidad:
* **Colores ANSI fijos por etapa** (`IF`, `ID`, `EX`, `MEM`, `WB`) para seguir la pista de cada instrucción de un vistazo.
* **Trazas de eventos en color distintivo** para identificar instantáneamente la aplicación de *Forwarding*, paradas por *Stall*, saltos tomados/no tomados y *Flushes*[cite: 2].

---

## 🚀 Requisitos e Instalación

### Requisitos previos
* **Python 3.8 o superior** instalado en el sistema[cite: 8].

### Clonar e iniciar el proyecto
```bash
git clone [https://github.com/Dani2oo3/segmentacion.git](https://github.com/Dani2oo3/segmentacion.git)
cd segmentacion
