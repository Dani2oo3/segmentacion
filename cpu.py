import argparse
import os
import re

from componentes_base import (
    ALU, BancoRegistros, MemoriaDatos, MemoriaInstrucciones, UnidadControl,
)
from registros_pipeline import (
    RegistroEX_MEM, RegistroID_EX, RegistroIF_ID, RegistroMEM_WB,
)

OPS_TIPO_R = ("ADD", "SUB")  # op Rd Rs Rt
OPS_TIPO_I = ("ADDI", "SUBI")  # op Rt Rs inmediato
_RE_REG = re.compile(r"R(?:[0-9]|[12][0-9]|3[01])")
_RE_MEM = re.compile(r"(-?\d+)\((R\d+)\)")


def decodificar(texto):
    partes = texto.split()
    op, args = partes[0].upper(), partes[1:]
    campos = dict(op=op, reg_destino=None, rs=None, rt=None, inmediato=None)

    def exigir(n, formato):
        if len(args) != n:
            raise ValueError(f"'{texto}': formato esperado '{formato}'")

    def registro(valor):
        valor = valor.upper()
        if not _RE_REG.fullmatch(valor):
            raise ValueError(f"'{texto}': registro no válido '{valor}'")
        return valor

    def mem(valor, formato):
        m = _RE_MEM.fullmatch(valor.upper())
        if not m:
            raise ValueError(f"'{texto}': formato esperado '{formato}'")
        return int(m.group(1)), registro(m.group(2))

    if op in OPS_TIPO_R:
        exigir(3, f"{op} Rd, Rs, Rt")
        campos.update(reg_destino=registro(args[0]), rs=registro(args[1]),
                      rt=registro(args[2]))
    elif op in OPS_TIPO_I:
        exigir(3, f"{op} Rt, Rs, inmediato")
        campos.update(reg_destino=registro(args[0]), rs=registro(args[1]),
                      inmediato=int(args[2]))
    elif op == "LW":  # LW Rt, offset(Rs)
        exigir(2, "LW Rt, offset(Rs)")
        desplazamiento, base = mem(args[1], "LW Rt, offset(Rs)")
        campos.update(reg_destino=registro(args[0]), rs=base, inmediato=desplazamiento)
    elif op == "SW":
        exigir(2, "SW offset(Rs), Rt")
        desplazamiento, base = mem(args[0], "SW offset(Rs), Rt")
        campos.update(rs=base, rt=registro(args[1]), inmediato=desplazamiento)
    elif op == "BEQ":  # BEQ Rs, Rt, etiqueta
        exigir(3, "BEQ Rs, Rt, etiqueta")
        campos.update(rs=registro(args[0]), rt=registro(args[1]), inmediato=args[2])
    elif op == "J":  # J etiqueta
        exigir(1, "J etiqueta")
        campos.update(inmediato=args[0])
    else:
        raise ValueError(f"Instrucción no soportada: '{texto}'")
    return campos

class CPU:
    def __init__(self, ruta_instrucciones, ruta_datos):
        # Componentes
        self.mem_inst = MemoriaInstrucciones()
        self.mem_datos = MemoriaDatos()
        self.banco = BancoRegistros()
        self.alu = ALU()
        self.uc = UnidadControl()

        # Registros de acoplamiento (pipeline inicialmente vacío)
        self.IF_ID = RegistroIF_ID()
        self.ID_EX = RegistroID_EX()
        self.EX_MEM = RegistroEX_MEM()
        self.MEM_WB = RegistroMEM_WB()

        # Estado
        self.PC = 0
        self.ciclo = 0
        self.registros_iniciales = {}

        self.cargar_entradas(ruta_instrucciones, ruta_datos)

    def cargar_entradas(self, ruta_instrucciones, ruta_datos):
        self.mem_inst.cargar_fichero(ruta_instrucciones)
        self.registros_iniciales = self.mem_datos.cargar_datos(ruta_datos)
        for reg, valor in self.registros_iniciales.items():
            self.banco.escribir(reg, valor)

    def mostrar_carga(self):
        print("=== INSTRUCCIONES CARGADAS ===")
        for indice, texto in sorted(self.mem_inst.datos.items()):
            etiquetas = [e for e, i in self.mem_inst.etiquetas.items() if i == indice]
            marca = f"   <- {', '.join(etiquetas)}" if etiquetas else ""
            print(f"  [{indice:2d}] {texto}{marca}")
        print("\n=== ETIQUETAS ===")
        for nombre, indice in self.mem_inst.etiquetas.items():
            print(f"  {nombre} -> {indice}")
        print("\n=== REGISTROS INICIALES ===")
        regs = ", ".join(f"{r}={self.banco.leer(r)}"
                         for r in sorted(self.registros_iniciales, key=lambda r: int(r[1:])))
        print(f"  {regs}")
        print("\n=== MEMORIA DE DATOS INICIAL ===")
        mem = ", ".join(f"MEM[{a}]={v}" for a, v in sorted(self.mem_datos.datos.items()))
        print(f"  {mem}")
        print(f"\nPC = {self.PC} | Pipeline vacio: "
              f"{all(r.actual is None for r in (self.IF_ID, self.ID_EX, self.EX_MEM, self.MEM_WB))}")

    def mostrar_decodificacion(self):
        print("\n=== DECODIFICACIÓN ===")
        print(f"  {'idx':>3}  {'op':<5} {'dest':<5} {'rs':<5} {'rt':<5} inmediato/etiqueta")
        for indice, texto in sorted(self.mem_inst.datos.items()):
            d = decodificar(texto)
            if d["op"] in ("BEQ", "J") and d["inmediato"] not in self.mem_inst.etiquetas:
                raise ValueError(f"'{texto}': etiqueta no definida '{d['inmediato']}'")
            print(f"  {indice:>3}  {d['op']:<5} {str(d['reg_destino'] or '-'):<5} "
                  f"{str(d['rs'] or '-'):<5} {str(d['rt'] or '-'):<5} "
                  f"{'-' if d['inmediato'] is None else d['inmediato']}")
            self.uc.generar_senales(d["op"])  # comprueba que la UC conoce la operación

    def _etapa_wb(self):
        raise NotImplementedError

    def _etapa_mem(self):
        raise NotImplementedError

    def _etapa_ex(self):
        raise NotImplementedError

    def _etapa_id(self):
        raise NotImplementedError

    def _etapa_if(self):
        raise NotImplementedError

    def ejecutar_ciclo(self):
        raise NotImplementedError("Orden: WB -> MEM -> EX -> ID -> IF, luego latch()")

    def mostrar_estado(self):
        raise NotImplementedError

    def ejecutar(self):
        raise NotImplementedError


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description="Simulador MIPS segmentado de 5 etapas")
    parser.add_argument("-i", "--instrucciones",
                        default=os.path.join(base, "instrucciones.txt"))
    parser.add_argument("-d", "--datos",
                        default=os.path.join(base, "datos_iniciales.txt"))
    args = parser.parse_args()

    cpu = CPU(args.instrucciones, args.datos)
    cpu.mostrar_carga()
    cpu.mostrar_decodificacion()


if __name__ == "__main__":
    main()
