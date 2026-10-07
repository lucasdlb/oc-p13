from experiments.rag.eval_v2.coach_eval import load_cases, validate_response


def test_coach_eval_has_forty_cases_and_unique_ids() -> None:
    cases = load_cases()

    assert len(cases) == 40
    assert len({case["id"] for case in cases}) == 40


def test_coach_eval_accepts_grounded_response() -> None:
    case = next(case for case in load_cases() if case["id"] == "compare-espagnole-agressif")

    result = validate_response(
        case,
        {
            "text": (
                "Reponse directe : le critere est le choix le plus agressif. "
                "Le plan propose une activite immediate et reste conditionnel a la position. "
                "On compare les coups autorises avec les donnees disponibles, sans attribuer "
                "une tactique qui ne figure pas dans les sources. La decision depend du niveau "
                "de risque accepte et de la suite jouable. Chaque option conserve une idee claire "
                "et doit etre verifiee apres la reponse adverse. "
                "Cette comparaison doit rester liee aux coups legalement disponibles, aux passages "
                "cites et au contexte de la ligne. Elle ne permet pas de conclure a un gain force "
                "sans indication explicite.\nConclusion : le choix agressif est celui qui preserve "
                "cette initiative."
            ),
            "sources": ["La ligne propose une activite immediate et une initiative durable."],
        },
    )

    assert result["passed"] is True
    assert result["issues"] == []


def test_coach_eval_reports_illegal_and_unsourced_claims() -> None:
    case = next(case for case in load_cases() if case["id"] == "explain-espagnole-001")

    result = validate_response(
        case,
        {
            "text": (
                "Le plan attaque directement et menace le roi. "
                "Conclusion : il faut rester prudent."
            ),
            "sources": [],
        },
    )

    assert result["passed"] is False
    assert any("unsourced tactical term" in issue for issue in result["issues"])
    assert any("word count outside range" in issue for issue in result["issues"])
