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
OPS_CON_ALU = OPS_TIPO_R + OPS_TIPO_I + ("LW", "SW")
_RE_REG = re.compile(r"R(?:[0-9]|[12][0-9]|3[01])")
_RE_MEM = re.compile(r"(-?\d+)\((R\d+)\)")
MAX_CICLOS = 10000  # protección frente a bucles infinitos

ETAPAS = ("IF", "ID", "EX", "MEM", "WB")
COLORES_ETAPA = {
    "IF": "\033[46m\033[30m",   # Fondo cian, texto negro
    "ID": "\033[43m\033[30m",   # Fondo amarillo, texto negro
    "EX": "\033[42m\033[30m",   # Fondo verde, texto negro
    "MEM": "\033[45m\033[30m",  # Fondo magenta, texto negro
    "WB": "\033[47m\033[30m",   # Fondo gris claro, texto negro
}
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_DIM = "\033[2m"
COLOR_EVENTO = "\033[94m"  # Azul brillante
ANCHO_INST = 25


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
    Camino de datos MIPS segmentado de 5 etapas (IF, ID, EX, MEM, WB).
    Las etapas se ejecutan en orden inverso dentro de cada ciclo para que cada
    una lea el contenido "actual" de los registros de acoplamiento (IF/ID,
    ID/EX, EX/MEM, MEM/WB) y escriba en su "siguiente".

    Para mostrar el estado, cada etapa anota (instrucción, detalle) en
    self.vista MIENTRAS se ejecuta, de modo que lo impreso es exactamente lo
    que ocurrió en ese ciclo (y no el contenido de los registros ya latcheados).
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
        self.pc_inicio = 0
        self.ciclo = 0
        self.registros_iniciales = {}
        self.regs_modificados = set()  # registros a mostrar en consola
        self.eventos = []  # eventos del camino de datos en el ciclo
        self.vista = {}    # etapa -> (texto instrucción | None, detalle)
        self.n_completadas = 0

        self.cargar_entradas(ruta_instrucciones, ruta_datos)

    def cargar_entradas(self, ruta_instrucciones, ruta_datos):
        self.mem_inst.cargar_fichero(ruta_instrucciones)
        self.registros_iniciales = self.mem_datos.cargar_datos(ruta_datos)
        for reg, valor in self.registros_iniciales.items():
            self.banco.escribir(reg, valor)
        self.regs_modificados = {r for r in self.registros_iniciales if r != "R0"}

    def iniciar_ciclo(self):
        self.eventos = []
        self.pc_inicio = self.PC
        self.vista = {e: (None, "Etapa inactiva (NOP)") for e in ETAPAS}

    def _ver(self, etapa, texto, detalle):
        self.vista[etapa] = (texto, detalle)

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
        orden = sorted(self.registros_iniciales, key=lambda r: int(r[1:]))
        regs = ", ".join(f"{r}={self.banco.leer(r)}" for r in orden) or "(todos a 0)"
        print(f"  {regs}")

        print(f"\n{COLOR_BOLD}=== MEMORIA DE DATOS INICIAL ==={COLOR_RESET}")
        mem = ", ".join(f"MEM[{a}]={v}" for a, v in sorted(self.mem_datos.datos.items()))
        print(f"  {mem if mem else '(vacía)'}")
        print(f"\n{COLOR_BOLD}PC{COLOR_RESET} = {self.PC} | Pipeline vacío: "
              f"{all(r.actual is None for r in (self.IF_ID, self.ID_EX, self.EX_MEM, self.MEM_WB))}")

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
            return
        destino = e["reg_destino"]
        if destino is not None and destino != "R0":
            valor = e["dato_memoria"] if e["dato_memoria"] is not None else e["resultado_alu"]
            self.banco.escribir(destino, valor)
            self.regs_modificados.add(destino)
            detalle = f"Escribe {destino} <- {valor}"
        else:
            detalle = "No escribe en el banco de registros"
        self.n_completadas += 1
        self._ver("WB", e["texto"], detalle)

    def etapa_mem(self):
        e = self.EX_MEM.actual
        if e is None:
            self.MEM_WB.siguiente = None
            return
        dato = None
        direccion = e["resultado_alu"]
        if e["op"] == "LW":
            dato = self.mem_datos.leer(direccion)
            detalle = f"Lee MEM[{direccion}] = {dato}"
        elif e["op"] == "SW":
            self.mem_datos.escribir(direccion, e["val_rt"])
            detalle = f"Escribe MEM[{direccion}] <- {e['val_rt']}"
        else:
            detalle = "Sin acceso a memoria"
        self.MEM_WB.cargar_siguiente(
            pc=e["pc"], texto=e["texto"], reg_destino=e["reg_destino"],
            resultado_alu=e["resultado_alu"], dato_memoria=dato,
        )
        self._ver("MEM", e["texto"], detalle)

    def etapa_ex(self, control):
        e = self.ID_EX.actual
        if e is None:
            self.EX_MEM.siguiente = None
            return

        op = e["op"]
        val_rs = e["val_rs"]
        val_rt = e["val_rt"]

        # Forwarding a la ALU solo para instrucciones que usan la ALU
        # (BEQ y J ya se resolvieron en ID; no tiene sentido adelantar nada).
        if op in OPS_CON_ALU:
            fwd_rs, fuente_rs = control.forwarding.valor_ex(e["rs"])
            if fwd_rs is not None:
                val_rs = fwd_rs
                self.eventos.append(f"FORWARDING EX: rs ({e['rs']}) <- {fuente_rs}")

            fwd_rt, fuente_rt = control.forwarding.valor_ex(e["rt"])
            if fwd_rt is not None:
                val_rt = fwd_rt
                self.eventos.append(f"FORWARDING EX: rt ({e['rt']}) <- {fuente_rt}")

        if op in OPS_TIPO_R:
            resultado = self.alu.operar(op, val_rs, val_rt)
            detalle = f"ALU {op}({val_rs}, {val_rt}) = {resultado}"
        elif op in OPS_TIPO_I:
            resultado = self.alu.operar(op, val_rs, e["inmediato"])
            detalle = f"ALU {op}({val_rs}, {e['inmediato']}) = {resultado}"
        elif op in ("LW", "SW"):
            resultado = self.alu.operar("ADD", val_rs, e["inmediato"])
            detalle = f"Dirección: {val_rs} + {e['inmediato']} = {resultado}"
        else:
            resultado = None
            detalle = "Sin operación en ALU (salto ya resuelto en ID)"

        self.EX_MEM.cargar_siguiente(
            pc=e["pc"], texto=e["texto"], op=op, reg_destino=e["reg_destino"],
            resultado_alu=resultado, val_rt=val_rt,
        )
        self._ver("EX", e["texto"], detalle)

    def etapa_id(self, control):
        entrada = self.IF_ID.actual
        if entrada is None:
            self.ID_EX.siguiente = None
            return

        texto = entrada["texto"]
        d = decodificar(texto)

        if control.detectar_riesgo_load_use(d, texto):
            self.IF_ID.siguiente = entrada
            self.ID_EX.siguiente = None
            self._ver("ID", texto, "STALL: depende de un LW que está en EX (burbuja)")
            return

        # Lectura de registros. El WB de este mismo ciclo ya escribió en el banco
        # (escritura en la 1ª mitad del ciclo, lectura en la 2ª), así que no hace
        # falta forwarding desde WB. Solo BEQ necesita forwarding en ID, porque
        # compara aquí mismo.
        val_rs = self.banco.leer(d["rs"]) if d["rs"] else None
        val_rt = self.banco.leer(d["rt"]) if d["rt"] else None

        if d["op"] == "BEQ":
            fwd_rs, fuente_rs = control.forwarding.valor_id(d["rs"])
            if fwd_rs is not None:
                val_rs = fwd_rs
                self.eventos.append(f"FORWARDING ID: rs ({d['rs']}) <- {fuente_rs}")
            fwd_rt, fuente_rt = control.forwarding.valor_id(d["rt"])
            if fwd_rt is not None:
                val_rt = fwd_rt
                self.eventos.append(f"FORWARDING ID: rt ({d['rt']}) <- {fuente_rt}")

        operandos = []
        if d["rs"]:
            operandos.append(f"{d['rs']}={val_rs}")
        if d["rt"]:
            operandos.append(f"{d['rt']}={val_rt}")
        detalle = "Lee " + ", ".join(operandos) if operandos else "Sin lectura de registros"

        if d["op"] in ("BEQ", "J"):
            tomado, destino = control.resolver_salto(d, val_rs, val_rt, texto)
            if d["op"] == "J":
                detalle = f"Salto incondicional a {d['inmediato']} (PC={destino})"
            elif tomado:
                detalle += f" -> IGUALES: salto a {d['inmediato']} (PC={destino})"
            else:
                detalle += " -> distintos: no salta"

        self.ID_EX.cargar_siguiente(
            pc=entrada["pc"], texto=texto, op=d["op"],
            reg_destino=d["reg_destino"], rs=d["rs"], rt=d["rt"],
            val_rs=val_rs, val_rt=val_rt, inmediato=d["inmediato"],
        )
        self._ver("ID", texto, detalle)

    def etapa_if(self, control):
        seg = control.segmentacion
        if seg.stall:
            pendiente = self.mem_inst.leer(self.PC)
            self._ver("IF", pendiente,
                      f"STALL: PC={self.PC} retenido, se vuelve a leer después")
            return

        texto = self.mem_inst.leer(self.PC)
        if texto is None:
            self.IF_ID.siguiente = None
            detalle = "Fin de programa: no hay más instrucciones"
        else:
            self.IF_ID.cargar_siguiente(pc=self.PC, texto=texto)
            detalle = f"Lee instrucción en PC={self.PC}"
            self.PC += 1

        if seg.destino_salto is not None:
            self.PC = seg.destino_salto
            self.IF_ID.vaciar()
            seg.registrar_flush(texto if texto is not None else "NOP")
            detalle = f"DESCARTADA por salto (flush); PC <- {self.PC}"
        self._ver("IF", texto, detalle)

    # ------------------------------------------------------------- consola
    @staticmethod
    def _celda(texto):
        if texto is None:
            return f"{COLOR_DIM}{'NOP':<{ANCHO_INST}}{COLOR_RESET}"
        return f"{texto:<{ANCHO_INST}}"

    def mostrar_estado(self, control):
        regs = sorted(self.regs_modificados, key=lambda r: int(r[1:]))
        regs_txt = ", ".join(f"{r}: {self.banco.registros[r]}" for r in regs)
        mem_txt = ", ".join(f"{a}: {v}" for a, v in sorted(self.mem_datos.datos.items()))

        print(f"\n{COLOR_BOLD}{'=' * 40} CICLO {self.ciclo} {'=' * 40}{COLOR_RESET}")
        print(f"{COLOR_BOLD}PC al inicio del ciclo:{COLOR_RESET} {self.pc_inicio}"
              f"   ->   {COLOR_BOLD}PC siguiente:{COLOR_RESET} {self.PC}")
        print(f"{COLOR_BOLD}{'ETAPA':<5}  | {'INSTRUCCIÓN':<{ANCHO_INST}} | DETALLES / ACCIÓN INTERNA{COLOR_RESET}")
        print("-" * 100)
        for etapa in ETAPAS:
            texto, detalle = self.vista[etapa]
            print(f"{COLORES_ETAPA[etapa]}[{etapa:<3}]{COLOR_RESET}  | "
                  f"{self._celda(texto)} | {detalle}")
        print("-" * 100)
        print(f"{COLOR_BOLD}Registros:        {COLOR_RESET} {{{regs_txt}}}")
        print(f"{COLOR_BOLD}Memoria de datos: {COLOR_RESET} {{{mem_txt}}}")

        eventos = self.eventos + control.segmentacion.eventos
        if eventos:
            print(f"{COLOR_BOLD}Eventos del ciclo:{COLOR_RESET}")
            for ev in eventos:
                print(f"  {COLOR_EVENTO}*{COLOR_RESET} {ev}")
        print(f"{COLOR_BOLD}{'=' * 100}{COLOR_RESET}")

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

    @staticmethod
    def _dato(reg_mem_wb):
        """Valor que escribirá en el banco una instrucción en/tras MEM."""
        if reg_mem_wb["dato_memoria"] is not None:
            return reg_mem_wb["dato_memoria"]
        return reg_mem_wb["resultado_alu"]

    def valor_ex(self, reg):
        """Forwarding hacia la entrada de la ALU (etapa EX).
        Se busca de la instrucción más reciente a la más antigua."""
        if not self.habilitado or not reg or reg == "R0":
            return None, None
        p = self.proceso

        ex_mem = p.EX_MEM.actual            # instrucción que está en MEM
        if ex_mem is not None and ex_mem["reg_destino"] == reg:
            if ex_mem["op"] == "LW":        # su dato aún no existe: lo evita el stall
                return None, None
            return ex_mem["resultado_alu"], "EX/MEM"

        mem_wb = p.MEM_WB.actual            # instrucción que está en WB
        if mem_wb is not None and mem_wb["reg_destino"] == reg:
            return self._dato(mem_wb), "MEM/WB"

        return None, None

    def valor_id(self, reg):
        """Forwarding hacia el comparador de BEQ (etapa ID).
        - Instrucción en EX: resultado de la ALU de este mismo ciclo (EX_MEM.siguiente).
        - Instrucción en MEM: su salida de este ciclo (MEM_WB.siguiente), que incluye
          el dato leído si es un LW.
        - Instrucción en WB: ya lo ha escrito el banco antes de leer en ID."""
        if not self.habilitado or not reg or reg == "R0":
            return None, None
        p = self.proceso

        ex = p.EX_MEM.siguiente
        if ex is not None and ex["reg_destino"] == reg:
            if ex["op"] == "LW":            # lo evita el stall load-use
                return None, None
            return ex["resultado_alu"], "EX (ALU)"

        mem = p.MEM_WB.siguiente
        if mem is not None and mem["reg_destino"] == reg:
            return self._dato(mem), "MEM (salida)"

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
        ex_actual = self.proceso.ID_EX.actual  # instrucción que está en EX

        if ex_actual is not None and ex_actual["op"] == "LW":
            destino_lw = ex_actual["reg_destino"]
            fuentes = {decodificada["rs"], decodificada["rt"]}
            if destino_lw is not None and destino_lw != "R0" and destino_lw in fuentes:
                self.segmentacion.parar(
                    f"STALL LOAD-USE en ID: '{texto}' espera lectura de '{destino_lw}' desde LW")
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
        p.iniciar_ciclo()
        c.nuevo_ciclo()

        p.etapa_wb()
        p.etapa_mem()
        p.etapa_ex(c)
        p.etapa_id(c)
        p.etapa_if(c)
        # Se imprime ANTES del latch: así cada etapa muestra lo que ha hecho
        p.mostrar_estado(c)
        p.avanzar_reloj()

    def ejecutar(self):
        p = self.unidad_proceso
        while True:
            self.ejecutar_ciclo()
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
    print()
    cpu.ejecutar()


if __name__ == "__main__":
    main()