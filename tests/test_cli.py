from tidyread.cli import main


def test_cli_writes_clean_csv(examples, tmp_path, capsys):
    out = tmp_path / "clean.csv"
    assert main([str(examples / "municipios_cp1252.csv"), "-o", str(out), "--clean-names"]) == 0
    assert "tidyread report" in capsys.readouterr().err
    text = out.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "municipio,codigo_ibge,populacao,area_km2,densidade_hab_km2,data_de_referencia"
    assert "Bragança,1501709,130122,2124.73,61.24,2022-08-01" in text


def test_cli_json_stdout(examples, capsys):
    assert main([str(examples / "municipios_cp1252.csv"), "-o", "-", "--json", "-q"]) == 0
    out, err = capsys.readouterr()
    assert err == "" and '"Município": "Bragança"' in out
