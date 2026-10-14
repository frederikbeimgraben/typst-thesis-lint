"""Short names of the guidelines and books that the rules cite."""

from thesis_lint.model import SourceRef

SAT = "SAT-Richtlinie meti, Version 10.0"
VORLAGE = "Dokumentvorlage Seminararbeit, Ver. 7.4"
BRINK = "Brink 2013, Anfertigung wissenschaftlicher Arbeiten"
HW = "Hirsch-Weber/Scherer 2016, Wissenschaftliches Schreiben (UTB 4450)"
LANGE = "Lange 2018, Fachtexte lesen - verstehen - wiedergeben"
DFG = "DFG 2022, Leitlinien zur Sicherung guter wissenschaftlicher Praxis"
USER = "Project decision"
VL02 = "Steddin, SAT S2026, VL02 Grundbegriffe"
FACTSHEET = "SAT FactSheet, 2025-03-19"


def ref(source: str, page: str, quote: str = "") -> SourceRef:
    """Return a source reference."""
    return SourceRef(source, page, quote)
