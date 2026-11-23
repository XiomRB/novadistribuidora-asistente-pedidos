from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.dominio.esquema_eventos import Evento, Interpretacion


def ev(id_="e1", tipo="agregar", **campos):
    base = {"id": id_, "mensaje": 0, "tipo": tipo, "texto": "2 fardos de kola 600", "producto": "kola"}
    base.update(campos)
    return base


def validar(eventos=(), consultas=(), rechazadas=(), n=2):
    return Interpretacion.validar(
        {"eventos": list(eventos), "consultas": list(consultas), "instrucciones_rechazadas": list(rechazadas)}, n
    )


class TestEvento:
    def test_valido_y_cantidad_decimal(self):
        e = Evento.model_validate(ev(cantidad="0,5", unidad="docena", unidad_texto="docena"))
        assert e.cantidad_decimal() == Decimal("0.5") and isinstance(e.cantidad_decimal(), Decimal)

    def test_descripcion(self):
        assert Evento.model_validate(ev(producto="kola norte", presentacion="600 ml")).descripcion() == "kola norte 600 ml"

    @pytest.mark.parametrize("campo", ["precio", "descuento_pct", "subtotal", "total", "fecha_entrega", "estado", "motivo"])
    def test_campos_comerciales_prohibidos(self, campo):
        with pytest.raises(ValidationError, match="Extra inputs"):
            Evento.model_validate(ev(**{campo: 1}))

    @pytest.mark.parametrize("cantidad", ["-1", "1e3", "2.5555", "123456", "dos", "", "1/2"])
    def test_cantidad_invalida(self, cantidad):
        with pytest.raises(ValidationError):
            Evento.model_validate(ev(cantidad=cantidad))

    @pytest.mark.parametrize("cantidad", ["0", "2", "48", "0.5", "99999", "1,25"])
    def test_cantidad_valida(self, cantidad):
        Evento.model_validate(ev(cantidad=cantidad))

    @pytest.mark.parametrize("candidatos", [["B01", "B01"], ["B 01"], ["x" * 21]])
    def test_candidatos_invalidos(self, candidatos):
        with pytest.raises(ValidationError):
            Evento.model_validate(ev(candidatos=candidatos))

    @pytest.mark.parametrize("campo", ["texto", "producto", "unidad_texto"])
    def test_textos_en_blanco(self, campo):
        with pytest.raises(ValidationError):
            Evento.model_validate(ev(**{campo: "   "}))

    def test_texto_demasiado_largo(self):
        with pytest.raises(ValidationError):
            Evento.model_validate(ev(texto="x" * 201))

    @pytest.mark.parametrize(
        "campos",
        [
            {"tipo": "habitual", "candidatos": ["B01"]},
            {"tipo": "habitual", "cantidad": "2", "producto": None},
            {"tipo": "quitar", "cantidad": "2"},
            {"tipo": "quitar", "cantidad_incierta": True},
            {"tipo": "agregar", "ref": "e1"},
            {"tipo": "quitar", "producto": None},
            {"tipo": "corregir", "producto": None, "ref": "e1"},
            {"tipo": "precisar", "producto": None, "ref": "e1"},
            {"tipo": "agregar", "unidad": "kilo"},
            {"tipo": "borrar"},
        ],
    )
    def test_reglas_por_tipo(self, campos):
        with pytest.raises(ValidationError):
            Evento.model_validate(ev(**campos))

    def test_formas_validas_por_tipo(self):
        Evento.model_validate(ev(tipo="habitual", producto=None, texto="lo de siempre"))
        Evento.model_validate(ev(tipo="quitar", producto=None, ref="e1"))
        Evento.model_validate(ev(tipo="corregir", producto=None, ref="e1", cantidad="5"))
        Evento.model_validate(ev(tipo="corregir", producto=None, ref="e1", cantidad_incierta=True))
        Evento.model_validate(ev(tipo="precisar", ref="e1", producto="el dorado"))


class TestInterpretacion:
    def test_vacia(self):
        assert validar().eventos == []

    def test_ids_consecutivos(self):
        with pytest.raises(ValidationError, match="consecutivos"):
            validar([ev("e1"), ev("e3")])

    def test_ref_hacia_adelante_o_inexistente(self):
        with pytest.raises(ValidationError, match="anterior"):
            validar([ev("e1", tipo="quitar", ref="e2"), ev("e2")])
        with pytest.raises(ValidationError, match="anterior"):
            validar([ev("e1"), ev("e2", tipo="quitar", ref="e9")])

    def test_ref_a_si_mismo(self):
        with pytest.raises(ValidationError, match="anterior"):
            validar([ev("e1", tipo="quitar", ref="e1")])

    def test_mensaje_no_retrocede(self):
        with pytest.raises(ValidationError, match="retroceder"):
            validar([ev("e1", mensaje=1), ev("e2", mensaje=0)])

    def test_indice_de_mensaje_fuera_de_rango(self):
        with pytest.raises(ValidationError, match="fuera de rango"):
            validar([ev("e1", mensaje=2)], n=2)
        with pytest.raises(ValidationError, match="fuera de rango"):
            validar(consultas=[{"mensaje": 5, "texto": "¿tienen kola?"}], n=2)

    def test_fragmentos(self):
        i = validar(consultas=[{"mensaje": 0, "texto": "¿tienen kola?"}], rechazadas=[{"mensaje": 1, "texto": "precio Q1"}])
        assert i.consultas[0].texto == "¿tienen kola?" and i.instrucciones_rechazadas[0].mensaje == 1

    @pytest.mark.parametrize("fragmento", [{"mensaje": 0, "texto": " "}, {"mensaje": -1, "texto": "x"}, {"mensaje": 0, "texto": "x", "extra": 1}])
    def test_fragmento_invalido(self, fragmento):
        with pytest.raises(ValidationError):
            validar(consultas=[fragmento])

    def test_limites(self):
        with pytest.raises(ValidationError):
            validar([ev(f"e{i}") for i in range(1, 42)])
        with pytest.raises(ValidationError):
            validar(consultas=[{"mensaje": 0, "texto": "x"}] * 21)

    def test_desde_json_y_campos_extra(self):
        json = '{"eventos": [], "consultas": [], "instrucciones_rechazadas": [], "total": 0}'
        with pytest.raises(ValidationError, match="Extra inputs"):
            Interpretacion.validar(json, 1)
        assert Interpretacion.validar('{"eventos": []}', 1).consultas == []

    def test_inmutable(self):
        i = validar([ev()])
        with pytest.raises(ValidationError):
            i.eventos[0].cantidad = "3"  # type: ignore[misc]

    def test_esquema_json_sin_campos_comerciales_ni_patrones(self):
        esquema = str(Interpretacion.model_json_schema())
        for prohibido in ("precio", "descuento", "subtotal", "total", "fecha_entrega", "credito", "'pattern'"):
            assert prohibido not in esquema
