from dataclasses import fields
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from app.datos.carga import cargar_datos
from app.datos.modelos import Cliente
from app.dominio.errores import DatosInvalidos
from tests.fixtures import datos_sinteticos as ds


def _codigos(error: DatosInvalidos) -> set[str]:
    return {e.codigo for e in error.errores}


def _con_productos(tmp_path, modificar):
    tabla = ds.productos()
    modificar(tabla)
    return ds.escribir(tmp_path / "d", {"productos": tabla})


class TestCargaValida:
    def test_carga_completa(self, datos):
        assert set(datos.productos) == {"G01", "G02", "G03", "C01", "C02", "Q01", "L01", "S01"}
        assert len(datos.alias) == 4
        assert set(datos.clientes) == {"K01", "K02", "K03", "K04"}
        assert datos.advertencias == ()

    def test_valores_numericos_son_decimal(self, datos):
        g02 = datos.productos["G02"]
        assert g02.precio == Decimal("90.5") and isinstance(g02.precio, Decimal)
        assert g02.unidades_por_empaque == Decimal(6) and isinstance(g02.unidades_por_empaque, Decimal)
        for escala in datos.escalas["bebidas"]:
            assert isinstance(escala.cantidad_minima, Decimal) and isinstance(escala.descuento_pct, Decimal)
        k01 = datos.clientes["K01"]
        assert isinstance(k01.limite_credito, Decimal) and isinstance(k01.saldo_pendiente, Decimal)

    def test_sustituto_nulo_y_presente(self, datos):
        assert datos.productos["G01"].sustituto_sku is None
        assert datos.productos["G03"].sustituto_sku == "G02"

    def test_escalas_ordenadas_por_minimo(self, datos):
        assert [e.cantidad_minima for e in datos.escalas["bebidas"]] == [Decimal(10), Decimal(20)]
        assert "limpieza" not in datos.escalas

    def test_dias_visita_normalizados(self, datos):
        assert datos.clientes["K02"].dias_visita == frozenset({2, 5})
        assert datos.clientes["K03"].dias_visita == frozenset({6})

    def test_saldo_cero_admitido(self, datos):
        assert datos.clientes["K04"].saldo_pendiente == Decimal(0)

    def test_historial_agrupado_y_ordenado(self, datos):
        pedidos = datos.historial["K01"]
        assert [p.pedido_id for p in pedidos] == ["P-1", "P-2", "P-3"]
        assert pedidos[0].fecha_entrega == date(2026, 11, 2)
        assert [(l.sku, l.cantidad) for l in pedidos[0].lineas] == [("G01", Decimal(2)), ("C01", Decimal(1))]
        assert pedidos[2].estado == "cancelado"

    def test_datos_inmutables(self, datos):
        with pytest.raises(TypeError):
            datos.productos["X"] = None  # type: ignore[index]


class TestMinimizacionDeDatos:
    def test_cliente_sin_datos_personales(self, datos):
        assert {f.name for f in fields(Cliente)} == {"cliente_id", "dias_visita", "limite_credito", "saldo_pendiente"}
        texto = repr(datos.clientes)
        assert "Ficticia" not in texto and "Municipio" not in texto

    def test_errores_sin_datos_personales(self, tmp_path):
        tabla = ds.clientes()
        tabla.loc[0, "dias_visita"] = "lunez"
        tabla.loc[1, "saldo_pendiente"] = -5
        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(ds.escribir(tmp_path / "d", {"clientes": tabla}))
        mensaje = str(info.value) + " ".join(str(e) for e in info.value.errores)
        assert "Ficticia" not in mensaje and "Municipio" not in mensaje
        assert {e.clave for e in info.value.errores} == {"K01", "K02"}


class TestErroresDeCarga:
    @pytest.mark.parametrize("archivo", list(ds.tablas()))
    def test_archivo_faltante(self, tmp_path, archivo):
        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(ds.escribir(tmp_path / "d", omitir=(archivo,)))
        assert "ARCHIVO_FALTANTE" in _codigos(info.value)

    def test_archivo_ilegible(self, tmp_path):
        directorio = ds.escribir(tmp_path / "d")
        (directorio / "productos.parquet").write_bytes(b"no es parquet")
        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(directorio)
        assert "ARCHIVO_ILEGIBLE" in _codigos(info.value)

    def test_columna_faltante(self, tmp_path):
        tabla = ds.productos().drop(columns=["precio"])
        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(ds.escribir(tmp_path / "d", {"productos": tabla}))
        assert any(e.codigo == "COLUMNA_FALTANTE" and e.columna == "precio" for e in info.value.errores)

    @pytest.mark.parametrize(
        ("columna", "valor"),
        [("precio", 12.345), ("precio", 0.0), ("precio", -1.0), ("precio", float("nan")), ("unidades_por_empaque", 0)],
    )
    def test_numericos_invalidos_en_productos(self, tmp_path, columna, valor):
        def modificar(t):
            t[columna] = t[columna].astype(object)
            t.loc[0, columna] = valor

        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(_con_productos(tmp_path, modificar))
        assert any(e.columna == columna and e.clave == "G01" for e in info.value.errores)

    def test_sku_duplicado(self, tmp_path):
        tabla = pd.concat([ds.productos(), ds.productos().iloc[[0]]], ignore_index=True)
        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(ds.escribir(tmp_path / "d", {"productos": tabla}))
        assert "SKU_DUPLICADO" in _codigos(info.value)

    @pytest.mark.parametrize(("valor", "codigo"), [("ZZZ", "SUSTITUTO_INEXISTENTE"), ("G03", "SUSTITUTO_PROPIO")])
    def test_sustituto_invalido(self, tmp_path, valor, codigo):
        def modificar(t):
            t.loc[t.sku == "G03", "sustituto_sku"] = valor

        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(_con_productos(tmp_path, modificar))
        assert codigo in _codigos(info.value)

    def test_disponible_no_booleano(self, tmp_path):
        def modificar(t):
            t["disponible"] = ["si" if v else "no" for v in t["disponible"]]

        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(_con_productos(tmp_path, modificar))
        assert any(e.columna == "disponible" for e in info.value.errores)

    def test_texto_obligatorio_vacio(self, tmp_path):
        def modificar(t):
            t.loc[0, "categoria"] = "  "

        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(_con_productos(tmp_path, modificar))
        assert any(e.codigo == "VALOR_FALTANTE" and e.columna == "categoria" for e in info.value.errores)

    @pytest.mark.parametrize(
        ("columna", "valor"), [("descuento_pct", 101), ("descuento_pct", -1), ("cantidad_minima", 0)]
    )
    def test_escala_invalida(self, tmp_path, columna, valor):
        tabla = ds.precios_escala()
        tabla.loc[0, columna] = valor
        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(ds.escribir(tmp_path / "d", {"precios_escala": tabla}))
        assert any(e.columna == columna for e in info.value.errores)

    def test_escala_duplicada_contradictoria(self, tmp_path):
        tabla = pd.concat(
            [ds.precios_escala(), pd.DataFrame([("bebidas", 10, 4)], columns=ds.precios_escala().columns)],
            ignore_index=True,
        )
        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(ds.escribir(tmp_path / "d", {"precios_escala": tabla}))
        assert "ESCALA_DUPLICADA" in _codigos(info.value)

    @pytest.mark.parametrize(
        ("columna", "valor", "codigo"),
        [
            ("dias_visita", "lunes,juebes", "DIA_INVALIDO"),
            ("dias_visita", " , ", "SIN_DIAS_VISITA"),
            ("limite_credito", -1, "VALOR_INVALIDO"),
            ("saldo_pendiente", 10.005, "VALOR_INVALIDO"),
        ],
    )
    def test_cliente_invalido(self, tmp_path, columna, valor, codigo):
        tabla = ds.clientes()
        tabla[columna] = tabla[columna].astype(object)
        tabla.loc[0, columna] = valor
        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(ds.escribir(tmp_path / "d", {"clientes": tabla}))
        assert any(e.codigo == codigo and e.clave == "K01" for e in info.value.errores)

    def test_cliente_duplicado(self, tmp_path):
        tabla = pd.concat([ds.clientes(), ds.clientes().iloc[[0]]], ignore_index=True)
        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(ds.escribir(tmp_path / "d", {"clientes": tabla}))
        assert "CLIENTE_DUPLICADO" in _codigos(info.value)

    @pytest.mark.parametrize(
        ("columna", "valor", "codigo"),
        [("estado", "devuelto", "ESTADO_INVALIDO"), ("cantidad", 0, "VALOR_INVALIDO"), ("fecha_entrega", None, "FECHA_INVALIDA")],
    )
    def test_historial_invalido(self, tmp_path, columna, valor, codigo):
        tabla = ds.historial_pedidos()
        tabla.loc[0, columna] = valor
        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(ds.escribir(tmp_path / "d", {"historial_pedidos": tabla}))
        assert codigo in _codigos(info.value)

    def test_pedido_incoherente(self, tmp_path):
        tabla = ds.historial_pedidos()
        tabla.loc[1, "estado"] = "cancelado"  # misma P-1 con estados distintos
        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(ds.escribir(tmp_path / "d", {"historial_pedidos": tabla}))
        assert "PEDIDO_INCOHERENTE" in _codigos(info.value)

    def test_reune_todos_los_problemas(self, tmp_path):
        productos = ds.productos()
        productos["precio"] = productos["precio"].astype(object)
        productos.loc[0, "precio"] = 1.234
        clientes = ds.clientes()
        clientes.loc[0, "dias_visita"] = "feriado"
        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(ds.escribir(tmp_path / "d", {"productos": productos, "clientes": clientes}))
        assert {"VALOR_INVALIDO", "DIA_INVALIDO"} <= _codigos(info.value)


class TestAdvertencias:
    def test_alias_y_historial_con_sku_inexistente(self, tmp_path):
        alias = pd.concat([ds.sinonimos(), pd.DataFrame([("NOPE", "fantasma")], columns=["sku", "alias"])], ignore_index=True)
        historial = ds.historial_pedidos()
        historial.loc[0, "sku"] = "VIEJO"
        datos = cargar_datos(ds.escribir(tmp_path / "d", {"sinonimos": alias, "historial_pedidos": historial}))
        codigos = {a.codigo for a in datos.advertencias}
        assert codigos == {"ALIAS_SKU_INEXISTENTE", "HISTORIAL_SKU_INEXISTENTE"}
        assert len(datos.alias) == 4
        # D42: la línea con sku desconocido se conserva; su tratamiento corresponde a E1b.
        assert datos.historial["K01"][0].lineas[0].sku == "VIEJO"
