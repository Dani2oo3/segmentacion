class RegistroPipeline:
    CAMPOS = ()

    def __init__(self):
        self.actual = None      # None equivale a una burbuja / NOP
        self.siguiente = None   # Datos calculados de la etapa anterior

    def cargar_siguiente(self, **campos):
        if set(campos) != set(self.CAMPOS):
            raise ValueError(
                f"{type(self).__name__}: campos esperados {sorted(self.CAMPOS)}, "
                f"recibidos {sorted(campos)}"
            )
        self.siguiente = campos

    def latch(self):
        self.actual = self.siguiente
        self.siguiente = None

    def vaciar(self):
        # Inyecta una burbuja (NOP) descartando actual y siguiente.
        self.actual = None
        self.siguiente = None

class RegistroIF_ID(RegistroPipeline):
    CAMPOS = ("pc", "texto")

class RegistroID_EX(RegistroPipeline):
    CAMPOS = ("pc", "texto", "op", "reg_destino", "rs", "rt",
              "val_rs", "val_rt", "inmediato", "senales")

class RegistroEX_MEM(RegistroPipeline):
    CAMPOS = ("pc", "texto", "op", "reg_destino", "resultado_alu",
              "val_rt", "senales")

class RegistroMEM_WB(RegistroPipeline):
    CAMPOS = ("pc", "texto", "reg_destino", "resultado_alu",
              "dato_memoria", "senales")
