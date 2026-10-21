import argparse
import os
import re

from componentes_base import (
    ALU, BancoRegistros, MemoriaDatos, MemoriaInstrucciones,
)
from registros_pipeline import (
    RegistroEX_MEM, RegistroID_EX, RegistroIF_ID, RegistroMEM_WB,
)

OPS_TIPO_R = ("ADD", "SUB")
OPS_TIPO_I = ("ADDI", "SUBI")
_RE_REG = re.compile(r"R(?:[0-9]|[12][0-9]|3[01])")
_RE_MEM = re.compile(r"(-?\d+)\((R\d+)\)")
MAX_CICLOS = 10_000  # protección frente a bucles infinitos

# ---------------------------------------------------------------- FORMATO Y COLORES
COLOR_IF = "\033[96m"  # Cian
COLOR_ID = "\033[93m"  # Amarillo
COLOR_EX = "\033[92m"  # Verde
COLOR_MEM = "\033[95m"  # Magenta
COLOR_WB = "\033[91m"  # Rojo
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_DIM = "\033[2m"
COLOR_EVENTO = "\033[94m" # Azul brillante


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


class UnidadProceso:
    """
        Tiene 5 etapas del pipeline MIPS (IF, ID, EX, MEM, WB) en orden
        inverso de ejecución dentro de cada ciclo de reloj para garantizar el paso de
        datos transparente entre los registros inter-etapa (IF/ID, ID/EX, EX/MEM, MEM/WB).
    """

    def __init__(self, ruta_instrucciones, ruta_datos):
        # Componentes
        self.mem_inst = MemoriaInstrucciones()
        self.mem_datos = MemoriaDatos()
        self.banco = BancoRegistros()
        self.alu = ALU()

        # Registros de acoplamiento (pipeline inicialmente vacío)
        self.IF_ID = RegistroIF_ID()
        self.ID_EX = RegistroID_EX()
        self.EX_MEM = RegistroEX_MEM()
        self.MEM_WB = RegistroMEM_WB()

        # Estado
        self.PC = 0
        self.ciclo = 0
        self.registros_iniciales = {}
        self.regs_modificados = set()  # registros a mostrar en consola
        self.wb_texto = None  # instrucción que completa WB en el ciclo
        self.eventos = []  # eventos del camino de datos en el ciclo
        self.n_completadas = 0

        self.cargar_entradas(ruta_instrucciones, ruta_datos)

    def cargar_entradas(self, ruta_instrucciones, ruta_datos):
        self.mem_inst.cargar_fichero(ruta_instrucciones)
        self.registros_iniciales = self.mem_datos.cargar_datos(ruta_datos)
        for reg, valor in self.registros_iniciales.items():
            self.banco.escribir(reg, valor)
        self.regs_modificados = {r for r in self.registros_iniciales if r != "R0"}

    def mostrar_carga(self):
        print(f"\n{COLOR_BOLD}=== INSTRUCCIONES CARGADAS ==={COLOR_RESET}")
        for indice, texto in sorted(self.mem_inst.datos.items()):
            etiquetas = [e for e, i in self.mem_inst.etiquetas.items() if i == indice]
            marca = f"   {COLOR_DIM}<- {', '.join(etiquetas)}{COLOR_RESET}" if etiquetas else ""
            print(f"  [{indice:2d}] {texto}{marca}")

        print(f"\n{COLOR_BOLD}=== ETIQUETAS ==={COLOR_RESET}")
        for nombre, indice in self.mem_inst.etiquetas.items():
            print(f"  {nombre} -> {indice}")

        print(f"\n{COLOR_BOLD}=== REGISTROS INICIALES ==={COLOR_RESET}")
        regs = ", ".join(f"{r}={self.banco.leer(r)}"
                         for r in sorted(self.registros_iniciales, key=lambda r: int(r[1:])) or ["R0=0"])
        print(f"  {regs}")

        print(f"\n{COLOR_BOLD}=== MEMORIA DE DATOS INICIAL ==={COLOR_RESET}")
        mem = ", ".join(f"MEM[{a}]={v}" for a, v in sorted(self.mem_datos.datos.items()))
        print(f"  {mem if mem else '(vacía)'}")
        print(f"\n{COLOR_BOLD}PC{COLOR_RESET} = {self.PC} | Pipeline vacío: "
              f"{all(r.actual is None for r in (self.IF_ID, self.ID_EX, self.EX_MEM, self.MEM_WB))}")

    def mostrar_decodificacion(self):
        print(f"\n{COLOR_BOLD}=== DECODIFICACIÓN ==={COLOR_RESET}")
        print(f"  {COLOR_DIM}{'idx':>3}  {'op':<5} {'dest':<5} {'rs':<5} {'rt':<5} inmediato/etiqueta{COLOR_RESET}")
        for indice, texto in sorted(self.mem_inst.datos.items()):
            d = decodificar(texto)
            if d["op"] in ("BEQ", "J") and d["inmediato"] not in self.mem_inst.etiquetas:
                raise ValueError(f"'{texto}': etiqueta no definida '{d['inmediato']}'")
            print(f"  {indice:>3}  {d['op']:<5} {str(d['reg_destino'] or '-'):<5} "
                  f"{str(d['rs'] or '-'):<5} {str(d['rt'] or '-'):<5} "
                  f"{'-' if d['inmediato'] is None else d['inmediato']}")

    def avanzar_reloj(self):
        """Fin de ciclo: latch() en los cuatro registros de acoplamiento."""
        for registro in (self.IF_ID, self.ID_EX, self.EX_MEM, self.MEM_WB):
            registro.latch()

    def terminado(self):
        vacio = all(r.actual is None
                    for r in (self.IF_ID, self.ID_EX, self.EX_MEM, self.MEM_WB))
        return vacio and self.PC >= len(self.mem_inst)

    # ---------------------------------------------------------------- etapas
    def etapa_wb(self):
        e = self.MEM_WB.actual
        if e is None:
            self.wb_texto = None
            return
        destino = e["reg_destino"]
        if destino is not None and destino != "R0":
            valor = e["dato_memoria"] if e["dato_memoria"] is not None else e["resultado_alu"]
            self.banco.escribir(destino, valor)
            self.regs_modificados.add(destino)
            self.eventos.append(f"WB: {destino} <- {valor}")
        self.wb_texto = e["texto"]
        self.n_completadas += 1

    def etapa_mem(self):
        e = self.EX_MEM.actual
        if e is None:
            self.MEM_WB.siguiente = None
            return
        dato = None
        if e["op"] == "LW":
            dato = self.mem_datos.leer(e["resultado_alu"])
            self.eventos.append(f"MEM: lee MEM[{e['resultado_alu']}] = {dato}")
        elif e["op"] == "SW":
            self.mem_datos.escribir(e["resultado_alu"], e["val_rt"])
            self.eventos.append(f"MEM: MEM[{e['resultado_alu']}] <- {e['val_rt']}")
        self.MEM_WB.cargar_siguiente(
            pc=e["pc"], texto=e["texto"], reg_destino=e["reg_destino"],
            resultado_alu=e["resultado_alu"], dato_memoria=dato,
        )

    def etapa_ex(self, control):
        e = self.ID_EX.actual
        if e is None:
            self.EX_MEM.siguiente = None
            return

        op = e["op"]
        val_rs = e["val_rs"]
        val_rt = e["val_rt"]

        fwd_rs, fuente_rs = control.forwarding.obtener_valor_rs(e)
        if fwd_rs is not None:
            val_rs = fwd_rs
            self.eventos.append(f"FORWARDING EX: rs ({e['rs']}) <- {fuente_rs}")

        fwd_rt, fuente_rt = control.forwarding.obtener_valor_rt(e)
        if fwd_rt is not None:
            val_rt = fwd_rt
            self.eventos.append(f"FORWARDING EX: rt ({e['rt']}) <- {fuente_rt}")

        if op in OPS_TIPO_R:
            resultado = self.alu.operar(op, val_rs, val_rt)
        elif op in OPS_TIPO_I:
            resultado = self.alu.operar(op, val_rs, e["inmediato"])
        elif op in ("LW", "SW"):
            resultado = self.alu.operar("ADD", val_rs, e["inmediato"])
        else:
            resultado = None

        self.EX_MEM.cargar_siguiente(
            pc=e["pc"], texto=e["texto"], op=op, reg_destino=e["reg_destino"],
            resultado_alu=resultado, val_rt=val_rt,
        )

    def etapa_id(self, control):
        entrada = self.IF_ID.actual
        if entrada is None:
            self.ID_EX.siguiente = None
            return

        d = decodificar(entrada["texto"])

        if control.detectar_riesgo_load_use(d, entrada["texto"]):
            self.IF_ID.siguiente = entrada
            self.ID_EX.siguiente = None
            return

        val_rs = self.banco.leer(d["rs"]) if d["rs"] else None
        val_rt = self.banco.leer(d["rt"]) if d["rt"] else None

        if d["op"] in ("BEQ", "J"):
            control.resolver_salto(d, val_rs, val_rt, entrada["texto"])

        self.ID_EX.cargar_siguiente(
            pc=entrada["pc"], texto=entrada["texto"], op=d["op"],
            reg_destino=d["reg_destino"], rs=d["rs"], rt=d["rt"],
            val_rs=val_rs, val_rt=val_rt, inmediato=d["inmediato"],
        )

    def etapa_if(self, control):
        seg = control.segmentacion
        if seg.stall:
            seg.registrar("IF: PC retenido, no se captura instrucción")
            return

        texto = self.mem_inst.leer(self.PC)
        if texto is None:
            self.IF_ID.siguiente = None
        else:
            self.IF_ID.cargar_siguiente(pc=self.PC, texto=texto)
            self.PC += 1

        if seg.destino_salto is not None:
            self.PC = seg.destino_salto
            self.IF_ID.vaciar()
            seg.registrar_flush(texto if texto is not None else "NOP")

    def _texto(self, registro):
        return registro.actual["texto"] if registro.actual else f"{COLOR_DIM}NOP{COLOR_RESET}"

    def mostrar_estado(self, control):
        regs = sorted(self.regs_modificados, key=lambda r: int(r[1:]))
        regs_txt = ", ".join(f"{r}: {self.banco.registros[r]}" for r in regs)
        mem_txt = ", ".join(f"{a}: {v}" for a, v in sorted(self.mem_datos.datos.items()))
        retenida = f" {COLOR_DIM}(retenida por stall){COLOR_RESET}" if control.segmentacion.stall else ""

        print(f"\n{COLOR_BOLD}==================== CICLO {self.ciclo} ===================={COLOR_RESET}")
        print(f"{COLOR_BOLD}PC:{COLOR_RESET} {self.PC}")
        print(f"{COLOR_BOLD}ETAPAS PIPELINE:{COLOR_RESET}")
        print(f"  {COLOR_IF}[IF ]{COLOR_RESET}  -> {self._texto(self.IF_ID)}{retenida}")
        print(f"  {COLOR_ID}[ID ]{COLOR_RESET}  -> {self._texto(self.ID_EX)}")
        print(f"  {COLOR_EX}[EX ]{COLOR_RESET}  -> {self._texto(self.EX_MEM)}")
        print(f"  {COLOR_MEM}[MEM]{COLOR_RESET}  -> {self._texto(self.MEM_WB)}")
        print(f"  {COLOR_WB}[WB ]{COLOR_RESET}  -> {self.wb_texto or f'{COLOR_DIM}NOP{COLOR_RESET}'}")
        print(f"{COLOR_BOLD}Registros modificados:{COLOR_RESET} {{{regs_txt}}}")
        print(f"{COLOR_BOLD}Memoria de datos:{COLOR_RESET}      {{{mem_txt}}}")

        for ev in self.eventos + control.segmentacion.eventos:
            print(f"  {COLOR_EVENTO}*{COLOR_RESET} {ev}")

        print(f"{COLOR_BOLD}" + "=" * 49 + f"{COLOR_RESET}")

    def mostrar_resumen(self, control):
        seg = control.segmentacion
        regs = sorted(self.regs_modificados, key=lambda r: int(r[1:]))
        print(f"\n{COLOR_BOLD}################ RESUMEN FINAL ################{COLOR_RESET}")
        print(f"Ciclos totales:            {self.ciclo}")
        print(f"Instrucciones completadas: {self.n_completadas}")
        print(f"Stalls (riesgos Load-Use): {seg.n_stalls}")
        print(f"Flushes por salto:         {seg.n_flushes}")
        if self.n_completadas:
            print(f"CPI:                       {self.ciclo / self.n_completadas:.2f}")
        print("Registros finales:         " + ", ".join(
            f"{r}={self.banco.registros[r]}" for r in regs))
        print("Memoria de datos final:    " + ", ".join(
            f"MEM[{a}]={v}" for a, v in sorted(self.mem_datos.datos.items())))


class Forwarding:
    def __init__(self, unidad_proceso):
        self.proceso = unidad_proceso
        self.habilitado = True

    def obtener_valor_rs(self, etapa_id_ex):
        if not self.habilitado:
            return None, None
        p = self.proceso
        rs = etapa_id_ex["rs"]
        if not rs or rs == "R0":
            return None, None

        ex_mem = p.EX_MEM.actual
        if ex_mem is not None and ex_mem["reg_destino"] == rs and ex_mem["reg_destino"] is not None:
            if ex_mem["op"] != "LW":
                return ex_mem["resultado_alu"], "EX/MEM"

        mem_wb = p.MEM_WB.actual
        if mem_wb is not None and mem_wb["reg_destino"] == rs and mem_wb["reg_destino"] is not None:
            val = mem_wb["dato_memoria"] if mem_wb["dato_memoria"] is not None else mem_wb["resultado_alu"]
            return val, "MEM/WB"

        return None, None

    def obtener_valor_rt(self, etapa_id_ex):
        if not self.habilitado:
            return None, None
        p = self.proceso
        rt = etapa_id_ex["rt"]
        if not rt or rt == "R0":
            return None, None

        ex_mem = p.EX_MEM.actual
        if ex_mem is not None and ex_mem["reg_destino"] == rt and ex_mem["reg_destino"] is not None:
            if ex_mem["op"] != "LW":
                return ex_mem["resultado_alu"], "EX/MEM"

        mem_wb = p.MEM_WB.actual
        if mem_wb is not None and mem_wb["reg_destino"] == rt and mem_wb["reg_destino"] is not None:
            val = mem_wb["dato_memoria"] if mem_wb["dato_memoria"] is not None else mem_wb["resultado_alu"]
            return val, "MEM/WB"

        return None, None


class Segmentacion:
    def __init__(self):
        self.stall = False
        self.destino_salto = None
        self.n_stalls = 0
        self.n_flushes = 0
        self.eventos = []

    def nuevo_ciclo(self):
        self.stall = False
        self.destino_salto = None
        self.eventos = []

    def registrar(self, mensaje):
        self.eventos.append(mensaje)

    def parar(self, mensaje):
        self.stall = True
        self.n_stalls += 1
        self.eventos.append(mensaje)

    def tomar_salto(self, destino, mensaje):
        self.destino_salto = destino
        self.eventos.append(mensaje)

    def registrar_flush(self, descartada):
        self.n_flushes += 1
        self.eventos.append(f"FLUSH: descartada '{descartada}' capturada en IF")


class UnidadControl:
    def __init__(self, unidad_proceso):
        self.proceso = unidad_proceso
        self.forwarding = Forwarding(unidad_proceso)
        self.segmentacion = Segmentacion()

    def nuevo_ciclo(self):
        self.segmentacion.nuevo_ciclo()

    def detectar_riesgo_load_use(self, decodificada, texto):
        p = self.proceso
        ex_actual = p.ID_EX.actual

        if ex_actual is not None and ex_actual["op"] == "LW":
            destino_lw = ex_actual["reg_destino"]
            fuentes_actuales = {decodificada["rs"], decodificada["rt"]}
            if destino_lw in fuentes_actuales and destino_lw is not None:
                self.segmentacion.parar(f"STALL LOAD-USE en ID: '{texto}' espera lectura de '{destino_lw}' desde LW")
                return True
        return False

    def resolver_salto(self, decodificada, val_rs, val_rt, texto):
        etiqueta = decodificada["inmediato"]
        etiquetas = self.proceso.mem_inst.etiquetas
        if etiqueta not in etiquetas:
            raise ValueError(f"'{texto}': etiqueta no definida '{etiqueta}'")
        if decodificada["op"] == "J" or val_rs == val_rt:
            destino = etiquetas[etiqueta]
            self.segmentacion.tomar_salto(
                destino, f"SALTO TOMADO: '{texto}' -> {etiqueta} (PC={destino})")
            return True, destino
        self.segmentacion.registrar(f"SALTO NO TOMADO: '{texto}'")
        return False, None


class CPU:
    def __init__(self, ruta_instrucciones, ruta_datos):
        self.unidad_proceso = UnidadProceso(ruta_instrucciones, ruta_datos)
        self.unidad_control = UnidadControl(self.unidad_proceso)

    def ejecutar_ciclo(self):
        p, c = self.unidad_proceso, self.unidad_control
        p.ciclo += 1
        p.eventos = []
        c.nuevo_ciclo()

        p.etapa_wb()
        p.etapa_mem()
        p.etapa_ex(c)
        p.etapa_id(c)
        p.etapa_if(c)
        p.avanzar_reloj()

    def ejecutar(self):
        p = self.unidad_proceso
        while True:
            self.ejecutar_ciclo()
            p.mostrar_estado(self.unidad_control)
            if p.terminado():
                break
            if p.ciclo >= MAX_CICLOS:
                raise RuntimeError(f"Se superaron {MAX_CICLOS} ciclos")
        p.mostrar_resumen(self.unidad_control)


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description="Simulador MIPS segmentado de 5 etapas con Forwarding")
    parser.add_argument("-i", "--instrucciones",
                        default=os.path.join(base, "instrucciones.txt"))
    parser.add_argument("-d", "--datos",
                        default=os.path.join(base, "datos_iniciales.txt"))
    args = parser.parse_args()

    cpu = CPU(args.instrucciones, args.datos)
    cpu.unidad_proceso.mostrar_carga()
    cpu.unidad_proceso.mostrar_decodificacion()
    print()
    cpu.ejecutar()


if __name__ == "__main__":
    main()