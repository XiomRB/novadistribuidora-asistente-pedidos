"""Detector de omisiones (E1b-2b): señales S1–S4, D60, cobertura por posición, D61 y D59."""

from itertools import combinations

import pytest

from app.dominio.consultas import oraciones
from app.dominio.omisiones import Senal, TipoSenal
from app.dominio.texto import Span
from tests.fixtures.historial_e1b2 import ev
from tests.fixtures.pedido_e1b2b import cargar_recursos, frag, lineas, pendientes, procesar


@pytest.fixture(scope="module")
def rec(tmp_path_factory):
    return cargar_recursos(tmp_path_factory.mktemp("omisiones"))[1]


def senales(rec, mensaje):
    return [(s.tipo.value, mensaje[s.span.inicio : s.span.fin]) for s in rec.detector.senales([mensaje])]


# ====================================================================== señales


class TestSenales:
    def test_s1_sustantivo_del_grupo_con_plural_y_diminutivo(self, rec):
        assert senales(rec, "gaseosas, galletitas y cafecito") == [
            ("S1", "gaseosas"), ("S1", "galletitas"), ("S1", "cafecito"),
        ]

    def test_s1_alias_y_nombre_completo(self, rec):
        assert ("S1", "frijol negro") in senales(rec, "y 2 de frijol negro")
        assert ("S1", "cafe monte molido") in senales(rec, "el cafe monte molido")

    def test_s1_error_leve_solo_con_evidencia_adyacente(self, rec):
        assert senales(rec, "friijol negro") == [("S1", "friijol")]
        assert senales(rec, "gaseosaa 600") == [("S1", "gaseosaa")]
        assert senales(rec, "frijool") == []  # sin evidencia adyacente no hay señal

    @pytest.mark.parametrize(
        "mensaje",
        ["doña Luz le manda saludos", "Claro que sí, gracias", "la Luna está bonita", "saludos a Monte y a Oro", "con Sol y buen tiempo"],
    )
    def test_d60_marca_o_variante_suelta_no_es_senal(self, rec, mensaje):
        assert senales(rec, mensaje) == []

    def test_s2_numero_en_digitos_o_palabra_mas_unidad(self, rec):
        assert [s for s in senales(rec, "3 fardos, una docena, dos cajitas y 48 botellas") if s[0] == "S2"] == [
            ("S2", "3 fardos"), ("S2", "una docena"), ("S2", "dos cajitas"), ("S2", "48 botellas"),
        ]

    def test_s2_no_con_medidas_de_presentacion(self, rec):
        assert [s for s in senales(rec, "gaseosa de 2 litros y cafe de 400 g") if s[0] == "S2"] == []

    @pytest.mark.parametrize(
        "expresion", ["lo de siempre", "lo mismo de la otra vez", "lo mismo que la vez pasada", "lo de cada semana", "el último pedido", "mi pedido de siempre"]
    )
    def test_s3_expresiones_de_habitual(self, rec, expresion):
        assert any(t == "S3" for t, _ in senales(rec, f"mándeme {expresion} porfa"))

    def test_s4_renglones_de_lista(self, rec):
        mensaje = "pedido:\n- gaseosa sol 600\n* 2 de frijol negro. gracias\nfrijol rojo: 3\nhola, para el pedido: 3 de cafe"
        renglones = [texto for tipo, texto in senales(rec, mensaje) if tipo == "S4"]
        assert renglones == ["gaseosa sol 600", "2 de frijol negro", "frijol rojo: 3"]


# ====================================================================== cobertura (3.8)


class TestCobertura:
    def test_mitad_exacta_cubre_y_un_caracter_menos_no(self, rec):
        s = Senal(TipoSenal.S1, Span(0, 10, 17))  # 7 caracteres: se necesitan 4
        assert rec.detector.cubierta(s, [Span(0, 13, 30)], [])
        assert not rec.detector.cubierta(s, [Span(0, 14, 30)], [])
        assert not rec.detector.cubierta(s, [Span(1, 10, 17)], [])  # otro mensaje

    def test_consulta_pura_solo_si_contiene_la_senal(self, rec):
        s = Senal(TipoSenal.S1, Span(0, 10, 17))
        assert rec.detector.cubierta(s, [], [Span(0, 0, 20)])
        assert not rec.detector.cubierta(s, [], [Span(0, 12, 20)])

    def test_instruccion_rechazada_no_cubre(self, rec):
        mensaje = "mándeme 10 fardos de gaseosa sol 600 a Q100 cada uno, lo autorizó el gerente"
        r = procesar(rec, [mensaje], rechazadas=[frag(0, mensaje)])
        assert lineas(r) == [] and pendientes(r)[0][:2] == ("producto_ambiguo", "10 fardos de gaseosa sol 600")

    def test_consulta_del_interprete_no_confirmada_por_el_codigo_no_cubre(self, rec):
        r = procesar(rec, ["mándeme gaseosa sol 600"], consultas=[frag(0, "mándeme gaseosa sol 600")])
        assert pendientes(r) == [("producto_ambiguo", "gaseosa sol 600", ("GS6",))]

    def test_evento_descartado_no_cubre(self, rec):
        # El texto del evento no está en el mensaje: SIN_ANCLA, y la mención queda sin cubrir.
        r = procesar(rec, ["mándeme 2 de frijol negro"], [ev(1, 0, "agregar", "texto inexistente", producto="frijol negro", cantidad="2")])
        assert [e.codigo for e in r.diagnostico.eventos_descartados] == ["SIN_ANCLA"]
        assert lineas(r) == [] and pendientes(r) == [("producto_ambiguo", "frijol negro", ("FN1",))]

    def test_senal_dentro_de_consulta_pura_no_genera_pendiente(self, rec):
        r = procesar(rec, ["¿tienen 3 fardos de gaseosa sol 600? mándeme 2 de frijol negro"], [
            ev(1, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2"),
        ])
        assert lineas(r) == [("FN1", "2")] and pendientes(r) == []


# ====================================================================== contexto D61

# Cada condición aislada. La mención sin cubrir es siempre "gaseosa" (S1), salvo en C5, donde
# además queda la propia expresión de habitual.
#
# C3 (renglón de lista) implica C2 por definición: la sección 3.4 aprobada y `consultas.py`
# (E1b-1) cuentan los renglones de lista como marcadores de compra. Por eso C3 se aísla en el
# nivel de `Contexto`, con oraciones sin marcador, y en el orquestador se prueba junto con C2.
CONDICIONES = {
    "C1": ("frijol negro y gaseosa", [ev(1, 0, "agregar", "frijol negro", producto="frijol negro")]),
    "C2": ("mándeme gaseosa", []),
    "C3": ("- gaseosa", []),
    "C4": ("gaseosa en 3 fardos", []),
    "C5": ("gaseosa y lo de siempre", []),
}
NOMBRES = ("C1", "C2", "C3", "C4", "C5")


def activas(ctx):
    return {k for k, v in zip(NOMBRES, (ctx.c1_evento, ctx.c2_compra, ctx.c3_lista, ctx.c4_cantidad, ctx.c5_habitual)) if v}


def sin_marcadores(mensaje):
    from dataclasses import replace

    return [replace(o, marcador_compra=False) for o in oraciones([mensaje])]


class TestContextoD61:
    @pytest.mark.parametrize("condicion", sorted(CONDICIONES))
    def test_cada_condicion_sola_genera_el_pendiente(self, rec, condicion):
        mensaje, eventos = CONDICIONES[condicion]
        r = procesar(rec, [mensaje], eventos)
        ctx = rec.detector.contexto(rec.detector.senales([mensaje]), oraciones([mensaje]), bool(eventos))
        assert activas(ctx) == ({"C2", "C3"} if condicion == "C3" else {condicion})
        assert any("gaseosa" in texto and motivo == "producto_ambiguo" for motivo, texto, _ in pendientes(r))
        assert r.clasificacion.value == "PEDIDO"

    def test_c3_aislada_en_el_contexto(self, rec):
        ctx = rec.detector.contexto(rec.detector.senales(["- gaseosa"]), sin_marcadores("- gaseosa"), False)
        assert activas(ctx) == {"C3"} and ctx.hay_pedido

    @pytest.mark.parametrize("condicion", NOMBRES)
    def test_cada_condicion_sola_basta_en_el_contexto(self, rec, condicion):
        mensaje, eventos = CONDICIONES[condicion]
        lista = oraciones([mensaje]) if condicion == "C2" else sin_marcadores(mensaje)
        ctx = rec.detector.contexto(rec.detector.senales([mensaje]), lista, bool(eventos))
        assert activas(ctx) == {condicion} and ctx.hay_pedido

    def test_ninguna_condicion_en_el_contexto(self, rec):
        ctx = rec.detector.contexto(rec.detector.senales(["la gaseosa llegó caliente"]), oraciones(["la gaseosa llegó caliente"]), False)
        assert activas(ctx) == set() and not ctx.hay_pedido

    @pytest.mark.parametrize("mensaje", ["la gaseosa llegó caliente", "gracias, el aceite estaba bueno", "el frijol de la vez anterior salió con piedras"])
    def test_sin_ninguna_condicion_no_se_genera_nada(self, rec, mensaje):
        r = procesar(rec, [mensaje])
        assert r.cierre.lineas == () and r.cierre.pendientes == ()
        assert r.clasificacion.value == "CONSULTA" and r.cierre.estado.value == "fuera_de_alcance"
        assert [o.codigo for o in r.diagnostico.omisiones] == ["SIN_CONTEXTO"]

    @pytest.mark.parametrize("pareja", list(combinations(sorted(CONDICIONES), 2)))
    def test_combinaciones_de_a_dos(self, rec, pareja):
        mensajes = [CONDICIONES[c][0] for c in pareja]
        eventos = [dict(e, mensaje=mensajes.index(CONDICIONES[c][0])) for c in pareja for e in CONDICIONES[c][1]]
        r = procesar(rec, mensajes, eventos)
        assert sum("gaseosa" in texto for _, texto, _ in pendientes(r)) == 2

    def test_todas_juntas(self, rec):
        mensajes = [CONDICIONES[c][0] for c in sorted(CONDICIONES)]
        r = procesar(rec, mensajes, [dict(CONDICIONES["C1"][1][0], mensaje=0)])
        assert sum("gaseosa" in texto for _, texto, _ in pendientes(r)) == 5

    def test_contexto_dentro_de_una_consulta_pura_no_cuenta(self, rec):
        # S2 y el marcador de compra quedan dentro de la consulta: el comentario no genera nada.
        r = procesar(rec, ["¿me pueden decir si hay 3 fardos de gaseosa? el frijol llegó bien"])
        assert r.cierre.pendientes == () and r.clasificacion.value == "CONSULTA"


# ====================================================================== pendientes (D05, D59)


class TestPendientesDeOmision:
    def test_d59_texto_es_exactamente_el_tramo_de_la_senal(self, rec):
        mensaje = "Hola, mándeme 2 de frijol negro y una caja de aceite. Gracias, saludos a la familia"
        r = procesar(rec, [mensaje], [ev(1, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2")])
        ((motivo, texto, opciones),) = pendientes(r)
        assert (motivo, texto, opciones) == ("producto_ambiguo", "una caja de aceite", ("AC1", "AC2"))
        (omision,) = r.diagnostico.omisiones
        assert mensaje[omision.posicion[1] : omision.posicion[2]] == texto and texto != mensaje

    def test_d05_nunca_crea_lineas_ni_cantidades(self, rec):
        r = procesar(rec, ["mándeme 3 fardos de gaseosa sol 600"])
        assert r.cierre.lineas == () and r.cierre.estado.value == "requiere_revision"
        assert pendientes(r) == [("producto_ambiguo", "3 fardos de gaseosa sol 600", ("GS6",))]

    def test_menciones_separadas_por_y_son_pendientes_distintos(self, rec):
        r = procesar(rec, ["mándeme gaseosa sol 600 y frijol negro"])
        assert [t for _, t, _ in pendientes(r)] == ["gaseosa sol 600", "frijol negro"]

    def test_habitual_omitido_sin_opciones(self, rec):
        r = procesar(rec, ["mándeme lo de siempre"], cliente="K01")
        assert pendientes(r) == [("producto_ambiguo", "lo de siempre", ())]

    def test_diagnostico_de_omisiones_sin_texto(self, rec):
        r = procesar(rec, ["mándeme 3 fardos de gaseosa ZQXMARCA"])
        assert "ZQXMARCA" not in repr(r.diagnostico) and r.diagnostico.omisiones[0].senal == "S1+S2"


# ====================================================================== revisión del PR #5
#
# Correcciones autorizadas en la revisión del PR #5 (antes documentadas con xfail estricto):
# - S1 aproximada: un número solo es evidencia si es una presentación compatible con el grupo,
#   y un signo de puntuación entre la palabra y la evidencia la anula.
# - C2: una oración cuyo único marcador de compra es el patrón de lista de E1b-1 solo cuenta si
#   es una lista válida (renglón S4 con una señal S1, o dos o más renglones S4 en el mensaje).

# Los seis falsos positivos de la revisión (catálogo real); aquí, sus equivalentes sintéticos.
FALSOS_POSITIVOS_S1 = ["Claro, 2 de frijol negro", "claro 2 veces", "lechee 3 dias", "aceitee 5 de la tarde", "papeel 7 veces", "detergentee, 2"]


class TestS1Aproximada:
    """Coincidencia aproximada (>= 80 %) del sustantivo del grupo, solo con evidencia adyacente.

    Correcto: un error leve del grupo seguido de una marca, una variante o una presentación del
    mismo grupo es señal; sin evidencia, con evidencia de otro grupo, con un número que no es una
    presentación del grupo o con puntuación entre medio, no lo es."""

    @pytest.mark.parametrize(
        ("mensaje", "senal"),
        [("friijol negro", "friijol"), ("gaseosaa 600", "gaseosaa"), ("gaseosaa 600 ml", "gaseosaa"), ("gaseosaa de 2 litros", "gaseosaa"),
         ("lechee nieve", "lechee"), ("aceitee 750 ml", "aceitee")],
    )
    def test_error_leve_con_evidencia_adyacente(self, rec, mensaje, senal):
        assert senales(rec, mensaje) == [("S1", senal)]

    @pytest.mark.parametrize("mensaje", ["friijol", "gaseosaa", "frijool por favor", "friijol y nada más"])
    def test_sin_evidencia_adyacente_no_es_senal(self, rec, mensaje):
        assert senales(rec, mensaje) == []

    @pytest.mark.parametrize("mensaje", ["frijool sol", "papeel sol", "lechee luna", "gaseosaa campo"])
    def test_evidencia_de_otro_grupo_no_cuenta(self, rec, mensaje):
        # "sol" es marca de la gaseosa, "luna" de las galletas y "campo" del frijol.
        assert senales(rec, mensaje) == []

    @pytest.mark.parametrize("mensaje", ["gaseosaa 750", "lechee 600 ml", "cafee 2 litros"])
    def test_presentacion_de_otro_grupo_no_cuenta(self, rec, mensaje):
        # 750 ml es del aceite, 600 ml de la gaseosa y 2 L de la gaseosa: ninguno del grupo parecido.
        assert senales(rec, mensaje) == []

    def test_no_confunde_grupos_en_la_misma_frase(self, rec):
        assert senales(rec, "friijol negro y gaseosaa sol") == [("S1", "friijol"), ("S1", "gaseosaa")]

    @pytest.mark.parametrize("mensaje", FALSOS_POSITIVOS_S1)
    def test_regresion_numero_que_no_es_presentacion_o_puntuacion(self, rec, mensaje):
        parecidas = {"claro", "lechee", "aceitee", "papeel", "detergentee"}
        assert [t for _, t in senales(rec, mensaje) if t.casefold() in parecidas] == []

    @pytest.mark.parametrize("mensaje", ["friijol, negro", "gaseosaa: 600", "gaseosaa (600)"])
    def test_puntuacion_entre_la_palabra_y_la_evidencia(self, rec, mensaje):
        assert [s for s in senales(rec, mensaje) if s[0] == "S1"] == []

    def test_grupos_de_menos_de_5_letras_no_admiten_error_leve(self, rec):
        assert senales(rec, "cafee 400 g") == [] and senales(rec, "cafe 400 g")[0] == ("S1", "cafe")

    def test_claro_al_inicio_no_genera_pendiente(self, rec):
        r = procesar(rec, ["Claro, 2 de frijol negro"], [ev(1, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2")])
        assert r.cierre.pendientes == () and r.cierre.estado.value == "confirmado"


class TestS4FrenteAC2:
    """S4 es estricta (la línea completa es «producto: número» o empieza con viñeta). C2 usa el
    marcador de compra de E1b-1, pero si su único marcador es el patrón de lista, la oración solo
    cuenta como lista válida: un renglón S4 con una señal S1, o dos o más renglones S4 en el mismo
    mensaje. C4 sigue activando el contexto por su cuenta (D61)."""

    def contexto(self, rec, mensaje):
        ctx = rec.detector.contexto(rec.detector.senales([mensaje]), oraciones([mensaje]), False)
        return activas(ctx)

    @pytest.mark.parametrize(("mensaje", "texto"), [("frijol rojo: 3", "frijol rojo: 3"), ("- gaseosa sol 600", "gaseosa sol 600")])
    def test_renglon_aislado_con_producto_activa_c2(self, rec, mensaje, texto):
        assert ("S4", texto) in senales(rec, mensaje) and self.contexto(rec, mensaje) == {"C2", "C3"}
        assert [t for _, t, _ in pendientes(procesar(rec, [mensaje]))] == [texto]

    @pytest.mark.parametrize("mensaje", ["entrega: 10", "saldo: 3"])
    def test_renglon_aislado_sin_producto_no_activa_c2(self, rec, mensaje):
        assert "C2" not in self.contexto(rec, mensaje)

    def test_dos_renglones_sin_producto_del_catalogo_activan_c2(self, rec):
        mensaje = "- recargas: 3\n- velas: 2"
        assert self.contexto(rec, mensaje) == {"C2", "C3"}
        assert [t for _, t, _ in pendientes(procesar(rec, [mensaje]))] == ["recargas: 3", "velas: 2"]

    def test_renglones_en_mensajes_distintos_no_forman_lista(self, rec):
        ctx = rec.detector.contexto(rec.detector.senales(["entrega: 10", "saldo: 3"]), oraciones(["entrega: 10", "saldo: 3"]), False)
        assert not ctx.c2_compra

    def test_otro_marcador_en_una_linea_de_lista_sigue_contando(self, rec):
        assert "C2" in self.contexto(rec, "- quiero recargas")

    @pytest.mark.parametrize("mensaje", ["saldo pendiente: 10 cajas", "entrega: 10 cajas"])
    def test_linea_que_no_es_s4_solo_activa_c4(self, rec, mensaje):
        assert all(t != "S4" for t, _ in senales(rec, mensaje))
        assert self.contexto(rec, mensaje) == {"C4"}
        assert pendientes(procesar(rec, [mensaje])) == [("producto_ambiguo", "10 cajas", ())]

    def test_reclamo_con_linea_x_n_sin_producto_es_consulta(self, rec):
        r = procesar(rec, ["saldo: 3. la gaseosa llegó caliente"])
        assert self.contexto(rec, "saldo: 3. la gaseosa llegó caliente") == set()
        assert r.clasificacion.value == "CONSULTA" and r.cierre.pendientes == () and r.cierre.lineas == ()

    def test_marcador_de_compra_normal_no_cambia(self, rec):
        assert self.contexto(rec, "mándeme gaseosa") == {"C2"} and self.contexto(rec, "y 3 de frijol negro") == {"C2"}


class TestC3RenglonDeLista:
    """Precisión autorizada de D61: C3 representa un renglón de productos o una lista, con el
    mismo criterio que C2 (renglón S4 con una señal S1, o dos o más renglones S4 en el mismo
    mensaje), no cualquier expresión con la forma «x: n»."""

    def contexto(self, rec, mensajes):
        return activas(rec.detector.contexto(rec.detector.senales(mensajes), oraciones(mensajes), False))

    @pytest.mark.parametrize("mensaje", ["entrega: 10", "saldo: 3", "- recargas: 3", "pedido: 5"])
    def test_renglon_aislado_sin_producto_es_consulta(self, rec, mensaje):
        assert self.contexto(rec, [mensaje]) == set()
        r = procesar(rec, [mensaje])
        assert r.clasificacion.value == "CONSULTA" and r.cierre.lineas == () and r.cierre.pendientes == ()

    @pytest.mark.parametrize("mensaje", ["frijol rojo: 3", "- gaseosa sol 600", "* cafe monte molido"])
    def test_renglon_aislado_con_producto_da_contexto(self, rec, mensaje):
        assert {"C2", "C3"} <= self.contexto(rec, [mensaje])
        assert procesar(rec, [mensaje]).clasificacion.value == "PEDIDO"

    @pytest.mark.parametrize("mensaje", ["- recargas: 3\n- velas: 2", "pedido:\n- recargas: 3\n- velas: 2"])
    def test_dos_renglones_de_productos_desconocidos_dan_contexto(self, rec, mensaje):
        assert {"C2", "C3"} <= self.contexto(rec, [mensaje])
        r = procesar(rec, [mensaje])
        assert r.clasificacion.value == "PEDIDO" and [t for _, t, _ in pendientes(r)] == ["recargas: 3", "velas: 2"]

    def test_dos_renglones_sin_vineta_dan_contexto(self, rec):
        assert {"C2", "C3"} <= self.contexto(rec, ["recargas: 3\nvelas: 2"])
        assert procesar(rec, ["recargas: 3\nvelas: 2"]).clasificacion.value == "PEDIDO"

    @pytest.mark.xfail(strict=True, reason="Agrupación: el salto de línea no separa menciones (corrección pendiente de autorización)")
    def test_dos_renglones_sin_vineta_son_pendientes_distintos(self, rec):
        assert [t for _, t, _ in pendientes(procesar(rec, ["recargas: 3\nvelas: 2"]))] == ["recargas: 3", "velas: 2"]

    def test_renglones_en_mensajes_distintos_no_forman_lista(self, rec):
        assert self.contexto(rec, ["entrega: 10", "saldo: 3"]) == set()

    @pytest.mark.parametrize("mensaje", ["saldo pendiente: 10 cajas", "entrega: 10 cajas"])
    def test_c4_es_independiente_de_c2_y_c3(self, rec, mensaje):
        assert self.contexto(rec, [mensaje]) == {"C4"}
        assert pendientes(procesar(rec, [mensaje])) == [("producto_ambiguo", "10 cajas", ())]

    def test_c2_y_c3_usan_el_mismo_criterio(self, rec):
        for mensajes in (["entrega: 10"], ["frijol rojo: 3"], ["- recargas: 3\n- velas: 2"], ["saldo: 3. la gaseosa llegó caliente"]):
            ctx = rec.detector.contexto(rec.detector.senales(mensajes), oraciones(mensajes), False)
            assert ctx.c2_compra == ctx.c3_lista, mensajes


class TestFinDeRenglon:
    """Un punto solo es parte de un número cuando está entre dos dígitos."""

    @pytest.mark.parametrize(
        ("mensaje", "renglon"),
        [
            ("- velas: 2. la gaseosa", "velas: 2"),
            ("- gaseosa sol 600. gracias", "gaseosa sol 600"),
            ("- gaseosa 1.5. gracias", "gaseosa 1.5"),
            ("- gaseosa 1.5 l. gracias", "gaseosa 1.5 l"),
            ("frijol rojo: 1.5", "frijol rojo: 1.5"),
            ("- frijol negro; y gracias", "frijol negro"),
            ("- frijol negro! gracias", "frijol negro"),
        ],
    )
    def test_decimales_y_puntos_finales(self, rec, mensaje, renglon):
        assert [t for tipo, t in senales(rec, mensaje) if tipo == "S4"] == [renglon]

    def test_el_pendiente_no_absorbe_la_oracion_siguiente(self, rec):
        r = procesar(rec, ["- recargas: 3\n- velas: 2. la gaseosa llegó caliente"])
        textos = [t for _, t, _ in pendientes(r)]
        assert textos[:2] == ["recargas: 3", "velas: 2"] and all("la gaseosa" not in t for t in textos)

    def test_renglon_aislado_que_termina_en_punto_no_da_contexto(self, rec):
        # "velas: 2" es un renglón aislado sin S1: el reclamo que sigue no se vuelve pedido.
        r = procesar(rec, ["- velas: 2. la gaseosa llegó caliente"])
        assert r.clasificacion.value == "CONSULTA" and r.cierre.pendientes == ()


class TestAgrupacion:
    @pytest.mark.parametrize(
        ("mensaje", "textos"),
        [
            ("mándeme gaseosa sol 600, frijol negro", ["gaseosa sol 600", "frijol negro"]),  # la coma separa
            ("mándeme gaseosa sol 600 y frijol negro", ["gaseosa sol 600", "frijol negro"]),  # "y" separa
            ("mándeme 3 fardos de gaseosa sol 600", ["3 fardos de gaseosa sol 600"]),  # "de" agrupa
            ("mándeme una docena de cloro claro", ["una docena de cloro claro"]),
            ("mándeme 2 cajas de aceite lo de siempre", ["2 cajas de aceite", "lo de siempre"]),  # S3 aparte
            ("mándeme lo de siempre de gaseosa sol", ["lo de siempre", "gaseosa sol"]),
            ("mándeme una docena de cloro claro, 2 cajas de aceite y lo de siempre", ["una docena de cloro claro", "2 cajas de aceite", "lo de siempre"]),
        ],
    )
    def test_tramos_exactos(self, rec, mensaje, textos):
        r = procesar(rec, [mensaje], cliente="K03")  # K03 no tiene historial entregado
        assert [t for _, t, _ in pendientes(r)] == textos
        for omision, texto in zip(r.diagnostico.omisiones, textos):
            assert mensaje[omision.posicion[1] : omision.posicion[2]] == texto
