"""Shared fixtures for LocalScript tests."""

import json
from pathlib import Path

import pytest

KNOWLEDGE_PATH = Path(__file__).parent.parent / "knowledge" / "lua_domain.json"

PUBLIC_PROMPTS = [
    {
        "name": "last_email",
        "prompt": 'Из полученного списка email получи последний.\n{"wf":{"vars":{"emails":["user1@example.com","user2@example.com","user3@example.com"]}}}',
        "expected_fragments": ["wf.vars.emails", "#wf.vars.emails"],
    },
    {
        "name": "try_count",
        "prompt": 'Увеличивай значение переменной try_count_n на каждой итерации\n{"wf":{"vars":{"try_count_n":3}}}',
        "expected_fragments": ["wf.vars.try_count_n", "+ 1"],
    },
    {
        "name": "clean_fields",
        "prompt": 'Для полученных данных из предыдущего REST запроса очисти значения переменных ID, ENTITY_ID, CALL\n{"wf":{"vars":{"RESTbody":{"result":[{"ID":123,"ENTITY_ID":456,"CALL":"example_call_1","OTHER_KEY_1":"value1","OTHER_KEY_2":"value2"},{"ID":789,"ENTITY_ID":101,"CALL":"example_call_2","EXTRA_KEY_1":"value3","EXTRA_KEY_2":"value4"}]}}}}',
        "expected_fragments": ["RESTbody", "result"],
    },
    {
        "name": "iso8601",
        "prompt": 'Преобразуй время из формата YYYYMMDD и HHMMSS в строку в формате ISO 8601.\n{"wf":{"vars":{"json":{"IDOC":{"ZCDF_HEAD":{"DATUM":"20231015","TIME":"153000"}}}}}}',
        "expected_fragments": ["DATUM", "TIME"],
    },
    {
        "name": "ensure_arrays",
        "prompt": 'Как преобразовать структуру данных так, чтобы все элементы items в ZCDF_PACKAGES всегда были представлены в виде массивов, даже если они изначально не являются массивами\n{"wf":{"vars":{"json":{"IDOC":{"ZCDF_HEAD":{"ZCDF_PACKAGES":[{"items":[{"sku":"A"},{"sku":"B"}]},{"items":{"sku":"C"}}]}}}}}}',
        "expected_fragments": ["ZCDF_PACKAGES", "items"],
    },
    {
        "name": "filter_discount",
        "prompt": 'Отфильтруй элементы из массива, чтобы включить только те, у которых есть значения в полях Discount или Markdown.\n{"wf":{"vars":{"parsedCsv":[{"SKU":"A001","Discount":"10%","Markdown":""},{"SKU":"A002","Discount":"","Markdown":"5%"},{"SKU":"A003","Discount":null,"Markdown":null},{"SKU":"A004","Discount":"","Markdown":""}]}}}',
        "expected_fragments": ["Discount", "Markdown"],
    },
    {
        "name": "square",
        "prompt": "Добавь переменную с квадратом числа 5",
        "expected_fragments": ["5"],
    },
    {
        "name": "unix_timestamp",
        "prompt": 'Конвертируй время в переменной recallTime в unix-формат.\n{"wf":{"initVariables":{"recallTime":"2023-10-15T15:30:00+00:00"}}}',
        "expected_fragments": ["recallTime", "initVariables"],
    },
]


@pytest.fixture
def knowledge_entries():
    with open(KNOWLEDGE_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def public_prompts():
    return PUBLIC_PROMPTS
