import re

class Memoria:
    def __init__(self):
        self.datos = {}

    def leer(self, direccion):
        return self.datos.get(direccion, 0)

    def escribir(self, direccion, valor):
        self.datos[direccion] = valor

class MemoriaInstrucciones(Memoria):

    _RE_ETIQUETA = re.compile(r"^([A-Za-z_]\w*)\s*:\s*(.*)$") #

    def __init__(self):
        super().__init__()
        self.etiquetas = {}

    def leer(self, direccion):
        return self.datos.get(direccion)

    def __len__(self):
        return len(self.datos)

    def cargar_fichero(self, ruta):
        self.datos.clear()
        self.etiquetas.clear()
        indice = 0
        with open(ruta, encoding="utf-8") as f:
            for numero, linea in enumerate(f, start=1):
                linea = linea.split("#")[0].replace(",", "").strip()
                if not linea:
                    continue
                while True:  # una línea puede llevar una o varias etiquetas
                    m = self._RE_ETIQUETA.match(linea)
                    if not m:
                        break
                    nombre, linea = m.group(1), m.group(2).strip()
                    if nombre in self.etiquetas:
                        raise ValueError(f"Línea {numero}: etiqueta duplicada '{nombre}'")
                    self.etiquetas[nombre] = indice
                if linea:
                    self.datos[indice] = linea
                    indice += 1

class MemoriaDatos(Memoria):

    _RE_REG = re.compile(r"^(R\d+)\s*=\s*(-?\d+)$", re.IGNORECASE)
    _RE_MEM = re.compile(r"^MEM\[\s*(\d+)\s*\]\s*=\s*(-?\d+)$", re.IGNORECASE)

    @staticmethod
    def _validar(direccion):
        if direccion % 4 != 0:
            raise ValueError(
                f"Dirección de memoria no alineada (debe ser múltiplo de 4): {direccion}")

    def leer(self, direccion):
        self._validar(direccion)
        return self.datos.get(direccion, 0)

    def escribir(self, direccion, valor):
        self._validar(direccion)
        self.datos[direccion] = valor

    def cargar_datos(self, ruta):

        registros = {}
        with open(ruta, encoding="utf-8") as f:
            for numero, linea in enumerate(f, start=1):
                linea = linea.split("#")[0].strip()
                if not linea:
                    continue
                m = self._RE_MEM.match(linea)
                if m:
                    self.escribir(int(m.group(1)), int(m.group(2)))
                    continue
                m = self._RE_REG.match(linea)
                if m:
                    registros[m.group(1).upper()] = int(m.group(2))
                    continue
                raise ValueError(f"{ruta}, línea {numero}: formato no válido '{linea}'")
        return registros

class BancoRegistros:

    def __init__(self):
        self.registros = {f"R{i}": 0 for i in range(32)}

    def _validar(self, reg):
        if reg not in self.registros:
            raise ValueError(f"Registro desconocido: {reg}")

    def leer(self, reg):
        self._validar(reg)
        return 0 if reg == "R0" else self.registros[reg]

    def escribir(self, reg, valor):
        self._validar(reg)
        if reg != "R0":
            self.registros[reg] = valor

def _num(valor):
    return int(valor)

class ALU:

    def operar(self, operacion, op1, op2):
        if operacion in ("ADD", "ADDI"):
            res = op1 + op2
        elif operacion in ("SUB", "SUBI"):
            res = op1 - op2
        else:
            raise ValueError(f"Operación de ALU no soportada: {operacion}")
        return _num(res)

class UnidadControl:

    OPS_ALU = ("ADD", "ADDI", "SUB", "SUBI")

    def generar_senales(self, op):
        senales = {"RegWrite": 0, "MemRead": 0, "MemWrite": 0, "EsSalto": 0}
        if op in self.OPS_ALU:
            senales["RegWrite"] = 1
        elif op == "LW":
            senales["RegWrite"] = 1
            senales["MemRead"] = 1
        elif op == "SW":
            senales["MemWrite"] = 1
        elif op in ("BEQ", "J"):
            senales["EsSalto"] = 1
        else:
            raise ValueError(f"Instrucción no soportada: {op}")
        return senales
