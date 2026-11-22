import json

from queryscope.__main__ import main


def test_cli_json_output(capsys) -> None:
    code = main(["ask", "how many orders are there", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert "status" in payload
    assert payload["status"] == "answered"
    assert code == 0


def test_cli_refusal_exit_code(capsys) -> None:
    code = main(["ask", "delete all orders", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "refused"
    assert code == 2


def test_cli_explain_reports_sql(capsys) -> None:
    main(["ask", "total revenue by country", "--explain"])
    assert "SQL:" in capsys.readouterr().out
