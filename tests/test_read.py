import codecs
import datetime as dt

import pytest

import tidyread
from tidyread import fix_mojibake, read, read_text


def test_ibge_like_export(examples):
    t = read(examples / "municipios_cp1252.csv", clean_names=True)
    d = t.detection
    assert d.encoding == "cp1252" and d.delimiter == ";" and d.decimal == ","
    assert len(d.skipped_top) == 2 and len(d.skipped_bottom) == 2
    assert t.columns == [
        "municipio",
        "codigo_ibge",
        "populacao",
        "area_km2",
        "densidade_hab_km2",
        "data_de_referencia",
    ]
    first = t.records()[0]
    assert first == {
        "municipio": "Bragança",
        "codigo_ibge": 1501709,
        "populacao": 130122,
        "area_km2": 2124.73,
        "densidade_hab_km2": 61.24,
        "data_de_referencia": dt.date(2022, 8, 1),
    }
    viseu = t.records()[-1]
    assert viseu["populacao"] is None and viseu["densidade_hab_km2"] is None


def test_us_style_utf8_bom():
    data = codecs.BOM_UTF8 + b'name,amount,date\n"Smith, J.","1,234.50",03/25/2024\nDoe,12.00,12/31/2024\n'
    t = read(data)
    assert t.detection.encoding == "utf-8-sig"
    assert t.detection.delimiter == "," and t.detection.decimal == "."
    assert t.detection.dayfirst is False and not t.detection.dayfirst_guessed
    assert t.records() == [
        {"name": "Smith, J.", "amount": 1234.5, "date": dt.date(2024, 3, 25)},
        {"name": "Doe", "amount": 12.0, "date": dt.date(2024, 12, 31)},
    ]


def test_utf16_tab_separated_excel_unicode_text():
    text = "produto\tpreço\nCafé\t12,50\nAçaí\t8,00\n"
    t = read(codecs.BOM_UTF16_LE + text.encode("utf-16-le"))
    assert t.detection.encoding == "utf-16" and t.detection.delimiter == "\t"
    assert t.column("preço") == [12.5, 8.0]
    assert t.column("produto") == ["Café", "Açaí"]


def test_mojibake_is_repaired():
    garbled = "cidade;estado\nSÃ£o Paulo;SP\nBelÃ©m;PA\nâ€œAspasâ€\x9d;X\n"
    t = read(garbled.encode("utf-8"))
    assert t.column("cidade") == ["São Paulo", "Belém", "“Aspas”"]
    assert t.detection.mojibake_fixes == 4
    assert fix_mojibake("Ação normal")[1] == 0


def test_leading_zeros_and_excel_text_trick_stay_text():
    t = read_text('cep;codigo;valor\n01310-100;="00123";1\n68600-000;="00456";2\n')
    assert t.column("codigo") == ["00123", "00456"]
    assert t.dtypes == {"cep": "str", "codigo": "str", "valor": "int"}


def test_currency_percent_negatives():
    csv = "item;preco;variacao;saldo\na;R$ 1.234,56;12,5%;(1.000,00)\nb;R$ 10,00;-3,0%;1.234,00-\n"
    t = read_text(csv)
    assert t.column("preco") == [1234.56, 10.0]
    assert t.column("variacao") == [12.5, -3.0]
    assert t.detection.columns[2].percent
    assert t.column("saldo") == [-1000.0, -1234.0]


def test_column_with_point_decimals_inside_comma_file():
    csv = "local;valor;latitude\nA;1.234,5;-1.0523\nB;2,25;-1.06\n"
    t = read_text(csv)
    assert t.detection.decimal == ","
    assert t.column("valor") == [1234.5, 2.25]
    assert t.column("latitude") == [-1.0523, -1.06]


def test_booleans_and_nulls():
    t = read_text("id;ativo;obs\n1;Sim;NA\n2;Não;#N/D\n3;;ok\n")
    assert t.column("ativo") == [True, False, None]
    assert t.column("obs") == [None, None, "ok"]


def test_datetimes_and_iso():
    t = read_text("quando,iso\n31/12/2024 23:59,2024-12-31T23:59:00Z\n01/01/2025 08:00,2025-01-01T08:00:00Z\n")
    assert t.detection.dayfirst is True
    assert t.column("quando")[0] == dt.datetime(2024, 12, 31, 23, 59)
    assert t.column("iso")[1] == dt.datetime(2025, 1, 1, 8, 0, tzinfo=dt.timezone.utc)


def test_ambiguous_dates_follow_option():
    csv = "d\n01/02/2024\n03/04/2024\n"
    assert read_text(csv, dayfirst=True).column("d")[0] == dt.date(2024, 2, 1)
    assert read_text(csv, dayfirst=False).column("d")[0] == dt.date(2024, 1, 2)


def test_no_header_is_detected():
    t = read_text("1;2,5;abc\n2;3,5;def\n")
    assert not t.detection.header
    assert t.columns == ["column_1", "column_2", "column_3"]
    assert t.column("column_2") == [2.5, 3.5]


def test_year_header_row():
    t = read_text("Estado;2010;2022\nPA;7.581.051;8.120.131\nAP;669.526;733.759\n")
    assert t.detection.header
    assert t.columns == ["Estado", "2010", "2022"]
    assert t.column("2022") == [8120131, 733759]


def test_ragged_rows_and_trailing_empty_columns():
    t = read_text("a;b;;\n1;2;;\n3;4;;\n5;6;7;\n")
    assert t.columns == ["a", "b", "column_3"]  # 4th column is always empty → dropped
    assert t.detection.dropped_empty_columns == 1
    assert t.column("column_3") == [None, None, 7]
    ragged = read_text("a;b\n1;2\n3;4;extra\n")
    assert ragged.detection.ragged_rows == 1 and ragged.columns == ["a", "b"]


def test_duplicate_and_empty_header_names():
    t = read_text("nome;nome;;x\nA;B;C;1\n")
    assert t.columns == ["nome", "nome_2", "column_3", "x"]


def test_overrides():
    t = read_text("a|b\n1|2\n", delimiter="|", header=True)
    assert t.records() == [{"a": 1, "b": 2}]


def test_mostly_numeric_column_warns():
    rows = "\n".join(f"{i};{i * 10}" for i in range(20))
    t = read_text("id;valor\n" + rows + "\n99;erro\n")
    assert t.dtypes["valor"] == "str"
    assert any("numeric" in w for w in t.detection.warnings)


def test_exports_roundtrip(tmp_path):
    t = read_text("nome;data;valor\nAna;31/12/2024;1,5\n")
    assert t.to_csv() == "nome,data,valor\nAna,2024-12-31,1.5\n"
    out = tmp_path / "x.json"
    t.to_json(out)
    assert '"data": "2024-12-31"' in out.read_text(encoding="utf-8")
    assert "2 columns" not in repr(t) and "1 rows × 3 columns" in repr(t)


def test_report_mentions_everything(examples):
    r = read(examples / "municipios_cp1252.csv").report()
    for word in ("cp1252", "semicolon", "decimal ','", "skipped", "footer", "5 rows × 6 columns"):
        assert word in r


def test_to_pandas():
    pd = pytest.importorskip("pandas")
    t = read_text("n;v;d;b\n1;1,5;01/02/2024;sim\n;;;não\n")
    df = t.to_pandas()
    assert str(df["n"].dtype) == "Int64"
    assert df["v"].dtype == "float64"
    assert str(df["b"].dtype) == "boolean"
    assert pd.api.types.is_datetime64_any_dtype(df["d"])


def test_version():
    assert tidyread.__version__
