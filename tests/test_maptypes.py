import datetime as dt

import pytest

from gridded_climo.query import Query, describe, unsupported_reason
from gridded_climo.ui.maptypes import BY_ID, MAP_TYPES, VARIABLES, first_type, source_note, swatch_css, types_for


def test_registry_covers_every_variable_and_type():
    assert set(VARIABLES) == {t.variable for t in MAP_TYPES}
    assert [t.id for t in types_for("temperature")] == ["tdates", "tsum", "tnormal", "tdep"]
    assert {t.group for t in types_for("precipitation")} == {"Rain", "Snow"}
    assert first_type("sun") == "sun" and len(BY_ID) == len(MAP_TYPES) == 12


@pytest.mark.parametrize("t", MAP_TYPES, ids=lambda t: t.id)
def test_every_type_has_a_swatch_and_source_note(t):
    assert swatch_css(t.ramp).startswith("linear-gradient(") and source_note(t.id, "station", True)


def test_cold_and_warm_titles():
    assert describe(Query(when="first", element="mint", op="le", value=32)) == "Average Date of First Low of 32°F or Colder"
    assert describe(Query(when="first", element="maxt", op="ge", value=70)) == "Average Date of First High of 70°F or Warmer"
    assert unsupported_reason(Query(when="first", element="maxt", op="ge", value=70, method="station")) is None
