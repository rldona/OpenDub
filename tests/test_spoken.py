import pytest

from opentranslator import clone
from opentranslator.spoken import spell_numbers


@pytest.mark.parametrize("text, said", [
    ("192 por 192.", "ciento noventa y dos por ciento noventa y dos."),
    ("Subimos 2x2, 4 x 4.", "Subimos dos por dos, cuatro por cuatro."),
    ("Cuesta 1.000 euros, un 25% más.", "Cuesta mil euros, un veinticinco por ciento más."),
    ("Mide 3,5 metros o 3.5 pies.", "Mide tres coma cinco metros o tres coma cinco pies."),
    ("0,05 segundos", "cero coma cero cinco segundos"),
    ("El 1º y la 2ª.", "El primero y la segunda."),
    ("En 2026.", "En dos mil veintiséis."),
    ("Sin cifras.", "Sin cifras."),
])
def test_spell_numbers(text, said):
    assert spell_numbers(text) == said


@pytest.mark.parametrize("text, heard", [
    # whisper writes back figures for clips that said the words: not errors
    ("Cinco por cinco por cinco va bien.", "5 x 5 x 5 va bien."),
    ("Llego. Cuatro por cuatro.", "Llego 4x4"),
    ("Podemos usar seis o cinco.", "Podemos usar 6 o 5."),
])
def test_quality_check_reads_figures_as_words(text, heard):
    assert clone.cer(text, heard) <= 0.05
